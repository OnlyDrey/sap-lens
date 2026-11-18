"""Shared final artifact collection. Build workspaces and extracted payloads stay elsewhere."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from .layout import is_linked_output


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


SUMS = 'SHA256SUMS.txt'
MANIFESTS = 'manifests'


def _replace(path, text, encoding='utf-8'):
    """Write through a new temporary file and an atomic rename: a failed write leaves the previous file intact."""
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    try:
        with temporary.open('x', encoding=encoding, newline='\n') as writer:
            writer.write(text)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_sums(output, manifest):
    """SHA256SUMS.txt is derived from the shared inventory, so every builder of this version/commit lists every registered artifact
    and none can drop another builder's rows."""
    path = Path(output) / SUMS
    if is_linked_output(path):
        raise ValueError('Checksum list may not be linked.')
    rows = sorted((name, row['sha256']) for name, row in manifest['artifacts'].items())
    _replace(path, ''.join(f'{sha}  {name}\n' for name, sha in rows), 'ascii')


def inventory(output, version, commit):
    """The shared inventory of a managed release directory, or None for a missing/empty directory. Another identity is refused."""
    output = Path(output)
    index = output / 'release-manifest.json'
    if not output.exists() or not any(output.iterdir()):
        return None
    if is_linked_output(index) or not index.is_file():
        raise ValueError('Output directory is not empty and is not a managed release directory; nothing was changed.')
    manifest = json.loads(index.read_text(encoding='utf-8'))
    if (not isinstance(manifest, dict) or manifest.get('schema') != 1 or not isinstance(manifest.get('artifacts'), dict)
            or manifest.get('version') != version or manifest.get('source_commit') != commit):
        raise ValueError('Release output belongs to another version/source; nothing was overwritten.')
    return manifest


def bound_manifest_path(output, key, kind='build-manifest'):
    if not key or any(character not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for character in key):
        raise ValueError('Invalid manifest key.')
    return Path(output) / MANIFESTS / f'{key}-{kind}.json'


def check_bound_manifest(output, key, artifact, sha256, kind='build-manifest'):
    """True when this exact artifact is already recorded, False when nothing is. A record of another artifact or digest is a conflict."""
    path = bound_manifest_path(output, key, kind)
    if any(is_linked_output(item) for item in (path.parent, path)):
        raise ValueError('Artifact manifests may not be linked.')
    if not path.exists():
        return False
    try:
        row = json.loads(path.read_text(encoding='utf-8'))
    except ValueError:
        row = None
    if not isinstance(row, dict) or row.get('artifact') != artifact or row.get('sha256') != sha256:
        raise ValueError(f'{path.name} already describes another artifact; nothing was overwritten.')
    return True


def write_bound_manifest(output, key, artifact, sha256, version, commit, payload, kind='build-manifest'):
    """One manifest per target, bound to its artifact by name and SHA-256. Created once; never rewritten by another target or build."""
    if check_bound_manifest(output, key, artifact, sha256, kind):
        return bound_manifest_path(output, key, kind)
    path = bound_manifest_path(output, key, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = dict(schema=1, target=key, artifact=artifact, sha256=sha256, version=version, source_commit=commit, **{kind.replace('-', '_'): payload})
    with path.open('x', encoding='utf-8', newline='\n') as writer:
        json.dump(document, writer, indent=2)
        writer.write('\n')
    return path


def collect(source, output, version, commit, platform, expected):
    source, output = Path(source), Path(output)
    if any(is_linked_output(path) for path in (source, *source.parents, output, *output.parents)):
        raise ValueError('Release paths may not be linked.')
    if not source.is_file() or digest(source) != expected:
        raise ValueError('Final artifact differs from the verified checksum.')
    index = output / 'release-manifest.json'
    if is_linked_output(index):
        raise ValueError('Release manifest may not be linked.')
    manifest = json.loads(index.read_text(encoding='utf-8')) if index.exists() else dict(schema=1, version=version, source_commit=commit, artifacts={})
    if (not isinstance(manifest, dict) or manifest.get('schema') != 1 or not isinstance(manifest.get('artifacts'), dict)
            or manifest.get('version') != version or manifest.get('source_commit') != commit):
        raise ValueError('Release output belongs to another version/source; nothing was overwritten.')
    for name, row in manifest['artifacts'].items():
        sidecar = output / (name + '.sha256')
        if (not isinstance(row, dict) or not isinstance(row.get('sha256'), str) or name in ('.', '..') or Path(name).name != name or '/' in name or '\\' in name or is_linked_output(output / name)
                or is_linked_output(sidecar) or digest(output / name) != row['sha256']
                or sidecar.read_text(encoding='ascii').strip() != row['sha256'] + '  ' + name):
            raise ValueError('Existing release inventory differs.')
    target = output / source.name
    checksum = output / (source.name + '.sha256')
    if any(path.exists() or path.is_symlink() for path in (target, checksum)):
        raise ValueError('Final artifact already exists; nothing was overwritten.')
    output.mkdir(parents=True, exist_ok=True)
    created = []
    temporary = output / ('.release-' + uuid.uuid4().hex + '.json')
    try:
        with source.open('rb') as reader, target.open('xb') as writer:
            created.append(target)
            shutil.copyfileobj(reader, writer)
        if digest(target) != expected:
            raise ValueError('Collected artifact checksum differs.')
        with checksum.open('x', encoding='ascii') as writer:
            created.append(checksum)
            writer.write(f'{expected}  {source.name}\n')
        manifest['artifacts'][source.name] = dict(platform=platform, version=version, source_commit=commit, sha256=expected)
        with temporary.open('x', encoding='utf-8') as writer:
            json.dump(manifest, writer, indent=2)
            writer.write('\n')
        os.replace(temporary, index)
        write_sums(output, manifest)
    except BaseException:
        for path in created:
            path.unlink()
        raise
    finally:
        temporary.unlink(missing_ok=True)
    return target


def register_existing(path, version, commit, platform, expected):
    """Register a canonical packager's new output in an already-managed release directory."""
    path = Path(path)
    if is_linked_output(path) or digest(path) != expected:
        raise ValueError('Final artifact differs from the verified checksum.')
    checksum = path.with_name(path.name + '.sha256')
    if is_linked_output(checksum) or checksum.read_text(encoding='ascii').strip() != expected + '  ' + path.name:
        raise ValueError('Final artifact sidecar differs.')
    index = path.parent / 'release-manifest.json'
    if is_linked_output(index):
        raise ValueError('Release manifest may not be linked.')
    manifest = json.loads(index.read_text(encoding='utf-8'))
    if manifest.get('version') != version or manifest.get('source_commit') != commit or path.name in manifest['artifacts']:
        raise ValueError('Release inventory identity differs or artifact was already registered.')
    manifest['artifacts'][path.name] = dict(platform=platform, version=version, source_commit=commit, sha256=expected)
    temporary = path.parent / ('.release-' + uuid.uuid4().hex + '.json')
    try:
        with temporary.open('x', encoding='utf-8') as writer:
            json.dump(manifest, writer, indent=2)
            writer.write('\n')
        os.replace(temporary, index)
        write_sums(path.parent, manifest)
    finally:
        temporary.unlink(missing_ok=True)
