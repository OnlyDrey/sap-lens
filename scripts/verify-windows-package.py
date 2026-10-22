"""Fail closed on Windows package integrity; never print rejected names or contents.

Build-only pefile/PyInstaller inspect native resources and archive contents. This
is an integrity/privacy guard, not a complete secret scanner or malware detector.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import io
import json
import os
import re
import struct
import sys
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
# Direct CLI execution must not depend on pytest/unittest or PYTHONPATH setup.
sys.path.insert(0, str(ROOT / 'backend'))
REQUIRED = {'frontend/dist/index.html', 'frontend/dist/sap-lens.png',
            'frontend/dist/favicon.png', 'frontend/dist/theme.js', 'assets/sap-lens.ico', 'build-version.json'}
DISTRIBUTION = {'SAP-Lens.exe', 'SAP-Lens.exe.sha256'}


class PackageValidationError(ValueError):
    """Only these application-authored, value-free messages may reach CI logs."""


def metadata_module():
    spec = importlib.util.spec_from_file_location('windows_metadata', ROOT / 'scripts/write-windows-metadata.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_name(name):
    value = name.replace('\\', '/').casefold()
    if not value or '\x00' in value or ':' in value or any(part in {'', '.', '..'} for part in value.split('/')):
        raise PackageValidationError('Package contains an unsafe archive path.')
    return value


def validate_names(names):
    normalized = set()
    for raw in names:
        name = canonical_name(raw)
        if name in normalized:
            raise PackageValidationError('Package contains duplicate resource names.')
        normalized.add(name)
        parts = name.split('/')
        base = parts[-1]
        blocked_dirs = {'node_modules', 'tests', 'fixtures', '.git', '.ssh', '.aws', '.azure',
                        '.github', '.vscode', '.idea', '.venv', '__pycache__', '.pytest_cache', '.mypy_cache', '.cache',
                        'configuration-backups', 'user-branding', 'local-config', 'app-data'}
        if any(part in blocked_dirs for part in parts):
            raise PackageValidationError('Development or private directories are present in the package.')
        if (base == '.env' or base.startswith('.env.') or base in {
                'settings.json', 'runtime.json', 'credentials', 'credentials.json', 'credentials.yaml', 'credentials.yml', 'secrets.json', 'secrets.yaml', 'secrets.yml', '.netrc', '.npmrc', '.pypirc', '.envrc', '.git-credentials',
                'id_rsa', 'id_ed25519', 'package-lock.json', 'package.json',
                'tsconfig.json', 'pytest.ini', 'pyproject.toml', 'pipfile', 'pipfile.lock',
                'classification-profiles.json', 'import-profiles.json', 'client_secret.json'}
                or '.log.' in base or base.endswith(('.csv', '.sap-lens.json', '.log', '.map', '.pdb', '.py', '.pyi',
                                  '.ts', '.tsx', '.ipynb', '.key', '.pfx', '.p12', '.bak', '.tmp', '.exe', '.bat', '.cmd', '.ps1', '.sh'))
                or (base.endswith('.pem') and name != 'certifi/cacert.pem')):
            raise PackageValidationError('Private data, development configuration or debugging files are present in the package.')
    return normalized


def validate_archive_names(names):
    normalized = validate_names(names)
    if not REQUIRED <= normalized:
        raise PackageValidationError('Required product assets are missing from the package.')
    return normalized


def validate_checksum(data, manifest):
    match = re.fullmatch(r'([0-9a-fA-F]{64})  SAP-Lens\.exe\r?\n?', manifest)
    actual = hashlib.sha256(data).hexdigest()
    if not match or match[1].lower() != actual:
        raise PackageValidationError('Executable checksum manifest does not match.')
    return actual


def validate_gui(data):
    if len(data) < 64 or data[:2] != b'MZ':
        raise PackageValidationError('The package is not a Windows executable.')
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    if pe < 64 or pe + 24 > len(data) or data[pe:pe+4] != b'PE\0\0':
        raise PackageValidationError('The package has an invalid PE header.')
    machine, sections = struct.unpack_from('<HH', data, pe + 4)
    size = struct.unpack_from('<H', data, pe + 20)[0]
    if machine != 0x8664:
        raise PackageValidationError('The application must target Windows x64.')
    if not sections or size < 112 or pe + 24 + size + sections * 40 > len(data):
        raise PackageValidationError('The package has truncated PE headers.')
    if struct.unpack_from('<H', data, pe + 24)[0] != 0x20b:
        raise PackageValidationError('The application must use PE32+ headers.')
    if struct.unpack_from('<H', data, pe + 24 + 68)[0] != 2:
        raise PackageValidationError('The application must use the GUI subsystem, without a console.')


def validate_metadata(strings, fixed_versions, resource_counts):
    expected = metadata_module()
    if strings != expected.expected_metadata():
        raise PackageValidationError('Windows application version metadata does not match the authoritative source.')
    version = expected.FILE_VERSION
    if fixed_versions != (version, version):
        raise PackageValidationError('Windows fixed version metadata does not match the application version.')
    if resource_counts.get(16) != 1 or resource_counts.get(14) != 1 or resource_counts.get(24) != 1 or resource_counts.get(3, 0) < 1:
        raise PackageValidationError('Windows version, icon or application manifest resources are missing or duplicated.')


def validate_icon(group, icons, canonical):
    if len(group) < 6 or len(canonical) < 6:
        raise PackageValidationError('Application icon resource is truncated.')
    reserved, kind, count = struct.unpack_from('<HHH', group)
    if (reserved, kind, count) != struct.unpack_from('<HHH', canonical) or kind != 1 or not count or len(icons) != count:
        raise PackageValidationError('Application icon directory differs from the canonical icon.')
    if len(group) != 6 + count * 14 or len(canonical) < 6 + count * 16:
        raise PackageValidationError('Application icon directory is invalid.')
    for i in range(count):
        actual = struct.unpack_from('<BBBBHHIH', group, 6 + i * 14)
        expected = struct.unpack_from('<BBBBHHII', canonical, 6 + i * 16)
        if actual[:7] != expected[:7] or icons.get(actual[7]) != canonical[expected[7]:expected[7] + expected[6]]:
            raise PackageValidationError('PE application icon differs from the canonical icon.')


def validate_manifest(data):
    root = ET.fromstring(data)
    levels = root.findall('.//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel')
    if len(levels) != 1 or levels[0].get('level') != 'asInvoker' or levels[0].get('uiAccess') != 'false':
        raise PackageValidationError('Application manifest must preserve non-elevated user execution.')


def inspect_resources(data):
    # pefile is already a PyInstaller dependency on Windows; it is not an app dependency.
    import pefile
    with pefile.PE(data=data) as pe:
        if pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size:
            raise PackageValidationError('Unexpected signature certificate table; this workflow is for unsigned builds.')
        strings = {}
        for group in getattr(pe, 'FileInfo', []):
            for info in group:
                for table in getattr(info, 'StringTable', []):
                    for key, value in table.entries.items():
                        key, value = key.decode('utf-8'), value.decode('utf-8')
                        if key in strings:
                            raise PackageValidationError('Duplicate Windows version strings are present.')
                        strings[key] = value
        fixed = getattr(pe, 'VS_FIXEDFILEINFO', [])
        if len(fixed) != 1:
            raise PackageValidationError('Windows fixed version resource is missing or duplicated.')
        value = fixed[0]
        split = lambda high, low: (high >> 16, high & 65535, low >> 16, low & 65535)
        versions = (split(value.FileVersionMS, value.FileVersionLS), split(value.ProductVersionMS, value.ProductVersionLS))
        def leaves(entry):
            if hasattr(entry, 'data'):
                return 1
            return sum(leaves(child) for child in entry.directory.entries)
        counts = {}
        for entry in getattr(getattr(pe, 'DIRECTORY_ENTRY_RESOURCE', None), 'entries', []):
            if entry.id in counts:
                raise PackageValidationError('Duplicate Windows resource type is present.')
            counts[entry.id] = leaves(entry)
        validate_metadata(strings, versions, counts)
        payloads = {}
        def collect(entry, path=()):
            if hasattr(entry, 'data'):
                if path in payloads:
                    raise PackageValidationError('Duplicate Windows resource identifier is present.')
                payloads[path] = pe.get_data(entry.data.struct.OffsetToData, entry.data.struct.Size)
            else:
                for child in entry.directory.entries:
                    collect(child, path + (child.id,))
        for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            collect(entry, (entry.id,))
        icons = {path[1]: value for path, value in payloads.items() if path[0] == 3}
        if len(icons) != counts[3]:
            raise PackageValidationError('Duplicate Windows icon identifier is present.')
        validate_icon(next(value for path, value in payloads.items() if path[0] == 14),
                      icons, (ROOT / 'assets/sap-lens.ico').read_bytes())
        validate_manifest(next(value for path, value in payloads.items() if path[0] == 24))
        return strings


def validate_toc(data):
    """Inspect raw entries before PyInstaller's dict can conceal duplicate names."""
    position, names = 0, []
    header = struct.calcsize('!IIIIBc')
    while position < len(data):
        if len(data) - position < header:
            raise PackageValidationError('PyInstaller archive table is truncated.')
        length, offset, stored, unpacked, compressed, kind = struct.unpack_from('!IIIIBc', data, position)
        if length <= header or position + length > len(data) or compressed not in (0, 1):
            raise PackageValidationError('PyInstaller archive table is malformed.')
        name = data[position + header:position + length].rstrip(b'\0').decode('utf-8')
        if not name or '\x00' in name:
            raise PackageValidationError('PyInstaller archive entry is malformed.')
        if kind != b'o':
            names.append(name)
        position += length
    validate_names(names)


def secret_check(data):
    if (re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s+[A-Za-z0-9+/=\r\n]{40,}', data)
            or re.search(rb'gh[pousr]_[A-Za-z0-9]{30,}', data)
            or re.search(rb'AKIA[A-Z0-9]{16}', data)):
        raise PackageValidationError('A potential embedded credential was found; values withheld.')


def inspect_archive(executable, frontend):
    from PyInstaller.archive.readers import CArchiveReader
    class CheckedReader(CArchiveReader):
        @classmethod
        def _parse_toc(cls, data):
            validate_toc(data)
            return super()._parse_toc(data)
    archive = CheckedReader(str(executable))
    names = validate_archive_names(archive.toc)
    with executable.open('rb') as stream:
        stream.seek(archive._end_offset - archive._COOKIE_LENGTH)
        _, length, toc_offset, toc_length, _, _ = struct.unpack(archive._COOKIE_FORMAT, stream.read(archive._COOKIE_LENGTH))
    if archive._start_offset < 0 or toc_offset + toc_length + archive._COOKIE_LENGTH != length:
        raise PackageValidationError('PyInstaller archive layout is inconsistent.')
    if any(p.is_symlink() for p in frontend.rglob('*')):
        raise PackageValidationError('Production frontend must not include linked files.')
    expected = {canonical_name('frontend/dist/' + str(p.relative_to(frontend)).replace('\\', '/')): p
                for p in frontend.rglob('*') if p.is_file()}
    if not expected or {n for n in names if n.startswith('frontend/dist/')} != set(expected):
        raise PackageValidationError('Bundled frontend differs from the complete production build.')
    modules = []
    for name, entry in archive.toc.items():
        offset, stored, unpacked, compressed, kind = entry
        if offset < 0 or stored < 0 or offset + stored > toc_offset:
            raise PackageValidationError('PyInstaller archive entry exceeds its package bounds.')
        # Read every CArchive member to check decompression/readability, but do not execute it.
        contents = archive.extract(name)
        if len(contents) != unpacked:
            raise PackageValidationError('PyInstaller archive member length is inconsistent.')
        if canonical_name(name) in expected and contents != expected[canonical_name(name)].read_bytes():
            raise PackageValidationError('Bundled frontend contents differ from the verified production build.')
        if canonical_name(name) == 'build-version.json':
            from version import parse_build_info
            try:
                if len(contents) > 4096: raise ValueError('Build identity is oversized.')
                embedded_version = parse_build_info(json.loads(contents))
            except (ValueError, TypeError, KeyError):
                raise PackageValidationError('Embedded build version is invalid.')
            if embedded_version != metadata_module().BUILD_INFO:
                raise PackageValidationError('Embedded build version differs from the resolved build.')
        if canonical_name(name) == 'assets/sap-lens.ico' and contents != (ROOT / 'assets/sap-lens.ico').read_bytes():
            raise PackageValidationError('Bundled application icon differs from the canonical icon.')
        if kind == 'z':
            embedded = archive.open_embedded_archive(name)
            modules.extend(embedded.toc)
            for module in embedded.toc:
                embedded.extract(module)  # Decompress compiled modules without executing them.
        if canonical_name(name) == 'base_library.zip':
            with zipfile.ZipFile(io.BytesIO(contents)) as library:
                validate_names(library.namelist())
                if library.testzip() is not None:
                    raise PackageValidationError('Python standard library archive is corrupt.')
        if canonical_name(name).endswith(('.html', '.js', '.css', '.json', '.txt', '.pem')):
            secret_check(contents)
    if not any(n.startswith('frontend/dist/assets/') and n.endswith('.js') for n in names):
        raise PackageValidationError('Production frontend JavaScript is missing.')
    if not any(n.casefold().startswith('python') and n.casefold().endswith('.dll') for n in names):
        raise PackageValidationError('Bundled Python runtime is missing.')
    if not any('webview' in n.casefold() and n.casefold().endswith('.dll') for n in names):
        raise PackageValidationError('Bundled WebView libraries are missing.')
    if 'desktop' not in names or not modules or 'main' not in modules or 'webview' not in modules or 'version' not in modules:
        raise PackageValidationError('Application entry point or embedded runtime modules are missing.')
    # No speculative exclusions: record suspicious build-only modules for review.
    review = sorted(n for n in modules if n.split('.')[0] in {'httpx', 'pip', 'pytest', 'PyInstaller'})
    return {'archive_entries': len(names), 'python_modules': len(modules), 'modules_for_review': review,
            'frontend_files': len(expected), 'archive_names': sorted(names), 'module_names': sorted(modules)}


def validate_distribution(directory, expected_sha256=None):
    if not directory.is_dir() or {p.name for p in directory.iterdir()} != DISTRIBUTION:
        raise PackageValidationError('Distribution must contain exactly the executable and its checksum manifest.')
    if any(not p.is_file() or p.is_symlink() for p in directory.iterdir()):
        raise PackageValidationError('Distribution contains non-regular files.')
    executable = directory / 'SAP-Lens.exe'
    data = executable.read_bytes()
    if not data:
        raise PackageValidationError('Executable is empty.')
    digest = validate_checksum(data, (directory / 'SAP-Lens.exe.sha256').read_text(encoding='ascii'))
    if expected_sha256 and digest != expected_sha256:
        raise PackageValidationError('Downloaded artifact differs from the verified executable.')
    return data, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distribution', type=Path, default=ROOT / 'backend/dist')
    parser.add_argument('--expected-sha256')
    parser.add_argument('--report', type=Path, default=ROOT / 'backend/build/package-verification.json')
    args = parser.parse_args()
    phase = 'build-identity'
    try:
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            from version import parse_build_info
            if parse_build_info(json.loads(os.environ.get('SAP_LENS_EXPECTED_BUILD_JSON',''))) != metadata_module().BUILD_INFO:
                raise PackageValidationError('Build metadata changed after workflow resolution.')
        if metadata_module().BUILD_INFO['mode'] == 'local':
            raise PackageValidationError('A generated build identity is required to verify a distribution.')
        phase = 'distribution-checksum'
        data, digest = validate_distribution(args.distribution, args.expected_sha256)
        phase = 'pe-headers'
        validate_gui(data)
        phase = 'pe-resources'
        metadata = inspect_resources(data)
        phase = 'pyinstaller-archive'
        inventory = inspect_archive(args.distribution / 'SAP-Lens.exe', ROOT / 'frontend/dist')
        report = {'status': 'passed', 'version': metadata['ProductVersion'], 'format': 'one-file',
                  'size_bytes': len(data), 'exe_sha256': digest, 'signing': 'unsigned (not configured)', **inventory}
        phase = 'verification-report'
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(f'Windows x64 GUI package verified; SHA-256 {digest}; {inventory["archive_entries"]} archive entries.')
    except Exception as error:
        # Third-party parser exceptions can embed untrusted filenames or binary values.
        if isinstance(error, PackageValidationError):
            message = 'PackageValidationError; package-policy rejection: ' + str(error)
        else:
            # Never echo parser messages, traceback paths, or arbitrary exception class names.
            categories = {ImportError: 'dependency/import setup', ModuleNotFoundError: 'dependency/import setup',
                          AttributeError: 'application/parser interface', TypeError: 'application/parser interface',
                          ValueError: 'malformed input or parser compatibility', UnicodeError: 'malformed input encoding',
                          OSError: 'filesystem/input access', EOFError: 'truncated input',
                          struct.error: 'malformed binary structure', ET.ParseError: 'malformed manifest',
                          zipfile.BadZipFile: 'corrupt embedded archive'}
            kind = next((kind for kind in (type(error), *type(error).__mro__[1:]) if kind in categories), None)
            message = (f'{kind.__name__}; {categories[kind]}' if kind else 'UnexpectedException; application/parser failure')
        parser.exit(1, f'Windows package inspection failed [phase={phase}]: {message}. Details withheld for privacy.\n')


if __name__ == '__main__':
    main()
