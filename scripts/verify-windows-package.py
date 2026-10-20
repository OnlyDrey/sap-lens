"""Validate the exact Windows build output before local delivery/artifact upload."""
from pathlib import Path
import hashlib
import os
import struct

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {'frontend/dist/index.html', 'frontend/dist/sap-lens.png',
            'frontend/dist/favicon.png', 'frontend/dist/theme.js', 'assets/sap-lens.ico'}


def validate_archive_names(names):
    normalized = {name.replace('\\', '/').lower() for name in names}
    if not REQUIRED <= normalized:
        raise ValueError('Required product assets are missing from the package.')
    for name in normalized:
        basename = name.rsplit('/', 1)[-1]
        if (basename in {'settings.json', 'runtime.json', '.env'}
                or basename.endswith(('.csv', '.sap-lens.json', '.log'))):
            raise ValueError('Private configuration, data or logs are present in the package.')


def validate_checksum(data, manifest):
    parts = manifest.split()
    actual = hashlib.sha256(data).hexdigest()
    if len(parts) != 2 or parts[1] != 'SAP-Lens.exe' or parts[0].lower() != actual:
        raise ValueError('Executable checksum manifest does not match.')
    return actual


def validate_gui(data):
    if len(data) < 64 or data[:2] != b'MZ':
        raise ValueError('The package is not a Windows executable.')
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    if pe + 94 > len(data) or data[pe:pe+4] != b'PE\0\0':
        raise ValueError('The package has an invalid PE header.')
    if struct.unpack_from('<H', data, pe + 24 + 68)[0] != 2:
        raise ValueError('The application must use the GUI subsystem, without a console.')


def main():
    # PyInstaller is deliberately build-only, not required by ordinary API tests.
    from PyInstaller.archive.readers import CArchiveReader
    executable = ROOT / 'backend/dist/SAP-Lens.exe'
    data = executable.read_bytes()
    digest = validate_checksum(data, executable.with_suffix('.exe.sha256').read_text(encoding='ascii'))
    validate_gui(data)
    archive = CArchiveReader(str(executable))
    validate_archive_names(archive.toc)
    message = (f'GUI executable; SHA-256 {digest}; {len(archive.toc)} archive entries; '
               'required product assets present; no private configuration/CSV/log entries.')
    print(message)
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        print(f'::notice title=Windows package verified::{message}')


if __name__ == '__main__':
    main()
