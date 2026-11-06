"""Validate the exact downloaded ZIP before extracting the two distribution files."""
import argparse
import hashlib
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

EXPECTED = {'SAP-Lens.exe', 'SAP-Lens.exe.sha256'}
MAX_EXE_SIZE = 512 * 1024 * 1024


def verify(download, destination, expected_digest):
    digest = expected_digest.removeprefix('sha256:')
    if not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('Missing or invalid expected ZIP digest')
    files = list(download.iterdir())
    if len(files) != 1 or files[0].is_symlink() or not files[0].is_file():
        raise ValueError('Expected exactly one downloaded archive')
    archive_path = files[0]
    with archive_path.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != digest:
            raise ValueError('Downloaded ZIP digest mismatch')
    if destination.exists() or destination.is_symlink():
        raise ValueError('Extraction destination must be new')
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) != 2 or {member.filename for member in members} != EXPECTED:
            raise ValueError('Unexpected or duplicate ZIP members')
        for member in members:
            mode = member.external_attr >> 16
            limit = MAX_EXE_SIZE if member.filename == 'SAP-Lens.exe' else 128
            if (member.orig_filename != member.filename or member.is_dir() or member.flag_bits & 1 or
                    (stat.S_IFMT(mode) not in {0, stat.S_IFREG}) or
                    not 0 < member.file_size <= limit or
                    member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
                raise ValueError('Unsafe ZIP member')
        destination.parent.mkdir(parents=True, exist_ok=True)
        # zipfile.open checks local header names and CRC. Never use extractall.
        with tempfile.TemporaryDirectory(prefix='sap-lens-zip-', dir=destination.parent) as temporary:
            staging = Path(temporary)
            for member in members:
                with archive.open(member) as source, (staging / member.filename).open('wb') as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
            destination.mkdir()
            for name in EXPECTED:
                (staging / name).replace(destination / name)
    print(f'Artifact ZIP verified: exactly two regular files; SHA-256 {digest}.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--expected-digest', required=True)
    args = parser.parse_args()
    try:
        verify(args.download, args.destination, args.expected_digest)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile):
        # Third-party archive errors may contain rejected paths; keep logs generic.
        parser.exit(1, 'Artifact ZIP verification failed.\n')


if __name__ == '__main__':
    main()
