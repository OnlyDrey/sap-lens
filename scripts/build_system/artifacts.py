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
    finally:
        temporary.unlink(missing_ok=True)
