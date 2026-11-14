"""Shared helpers of the runtime experiment: hashing, safe extraction, deterministic manifests. Standard library only."""
import hashlib
import json
import os
import stat
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parents[1]
CACHE = Path(os.environ.get('POC_CACHE', ROOT / '.cache'))
LOCK = ROOT / 'runtime' / 'lock.json'


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def download(url, destination, expected_sha256, expected_size=None):
    """Download once into the cache; a cached or fresh file must match the pinned hash or it is removed and refused."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and sha256_file(destination) == expected_sha256:
        return destination
    destination.unlink(missing_ok=True)
    temporary = destination.with_suffix(destination.suffix + '.part')
    with urllib.request.urlopen(url, timeout=120) as response, open(temporary, 'wb') as stream:
        while block := response.read(1 << 20):
            stream.write(block)
    if sha256_file(temporary) != expected_sha256 or (expected_size is not None and temporary.stat().st_size != expected_size):
        temporary.unlink(missing_ok=True)
        raise SystemExit(f'Hash or size mismatch for {url}; nothing was kept.')
    temporary.replace(destination)
    return destination


def safe_member_path(name):
    """Relative, forward-slash path without traversal; anything else is an error, never silently skipped."""
    parts = name.replace('\\', '/').split('/')
    if name.startswith(('/', '\\')) or '..' in parts or (parts and len(parts[0]) == 2 and parts[0][1] == ':'):
        raise SystemExit(f'Unsafe archive member: {name!r}')
    return '/'.join(part for part in parts if part not in ('', '.'))


def extract_tar_gz(archive, destination):
    with tarfile.open(archive, 'r:gz') as bundle:
        for member in bundle.getmembers():
            relative = safe_member_path(member.name)
            if not relative:
                continue
            if member.issym() or member.islnk():
                target = member.linkname.replace('\\', '/')
                resolved = os.path.normpath(os.path.join(os.path.dirname(relative), target))
                if target.startswith('/') or resolved.startswith('..'):
                    raise SystemExit(f'Unsafe link in archive: {member.name!r}')
            elif not (member.isfile() or member.isdir()):
                raise SystemExit(f'Unsupported archive member type: {member.name!r}')
            member.name = relative
            bundle.extract(member, destination, filter='data')


def extract_wheel(wheel, site_packages):
    """Unpack a wheel like an installer would (purelib/platlib into site-packages, scripts and headers skipped). Nothing is executed."""
    with zipfile.ZipFile(wheel) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            relative = safe_member_path(info.filename)
            top = relative.split('/')[0]
            if top.endswith('.data'):
                parts = relative.split('/')
                if len(parts) < 3 or parts[1] not in ('purelib', 'platlib'):
                    continue
                relative = '/'.join(parts[2:])
            target = Path(site_packages) / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))


def normalise_modes(tree):
    """Deterministic permissions: executables 0755 (by suffix or existing owner-exec bit), everything else 0644."""
    for path in sorted(Path(tree).rglob('*')):
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o755)
        else:
            executable = bool(path.stat().st_mode & stat.S_IXUSR) or path.suffix in ('.exe', '.dll', '.pyd')
            path.chmod(0o755 if executable else 0o644)


def tree_manifest(tree, extra=None):
    """Sorted per-file records plus one root hash over them. No timestamps, no host paths: the same inputs give the same root."""
    tree = Path(tree)
    files = []
    for path in sorted(tree.rglob('*'), key=lambda p: p.relative_to(tree).as_posix()):
        relative = path.relative_to(tree).as_posix()
        if relative == 'manifest.json':
            continue
        if path.is_symlink():
            files.append({'path': relative, 'type': 'link', 'target': os.readlink(path)})
        elif path.is_file():
            files.append({'path': relative, 'type': 'file', 'size': path.stat().st_size, 'executable': bool(path.stat().st_mode & stat.S_IXUSR), 'sha256': sha256_file(path)})
    canonical = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
    manifest = {'schema': 1, 'file_count': sum(1 for f in files if f['type'] == 'file'), 'bytes': sum(f.get('size', 0) for f in files),
                'root_sha256': hashlib.sha256(canonical).hexdigest(), 'files': files}
    if extra:
        manifest['inputs'] = extra
    return manifest


def verify_tree(tree):
    """Recompute and compare with manifest.json. Returns a list of problems (empty = intact): changed, missing and unexpected files."""
    tree = Path(tree)
    try:
        recorded = json.loads((tree / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ['manifest.json is missing or unreadable']
    current = tree_manifest(tree)
    wanted = {f['path']: f for f in recorded.get('files', [])}
    found = {f['path']: f for f in current['files']}
    problems = [f'missing: {p}' for p in sorted(set(wanted) - set(found))]
    problems += [f'unexpected: {p}' for p in sorted(set(found) - set(wanted))]
    problems += [f'changed: {p}' for p in sorted(set(wanted) & set(found)) if wanted[p] != found[p]]
    if recorded.get('root_sha256') != current['root_sha256'] and not problems:
        problems.append('root hash differs')
    return problems


def write_deterministic_archive(tree, destination):
    """tar.gz with fixed owner, mtime, order and gzip header: identical trees give identical bytes."""
    import gzip
    import io
    tree = Path(tree)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.PAX_FORMAT) as bundle:
        for path in sorted(tree.rglob('*'), key=lambda p: p.relative_to(tree).as_posix()):
            relative = path.relative_to(tree).as_posix()
            info = bundle.gettarinfo(str(path), arcname=relative)
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            info.mtime = 0
            info.pax_headers = {}
            if info.isfile():
                with open(path, 'rb') as stream:
                    bundle.addfile(info, stream)
            else:
                bundle.addfile(info)
    with open(destination, 'wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0, compresslevel=6) as stream:
        stream.write(buffer.getvalue())
    return sha256_file(destination)
