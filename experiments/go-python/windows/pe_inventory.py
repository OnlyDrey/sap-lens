"""Static PE inventory of a Windows runtime tree, runnable on Linux. Reads headers only; nothing is executed or trust-validated.

  python pe_inventory.py TREE [--json OUT]
Reports per file: machine type, whether an embedded Authenticode certificate table exists (NOT whether the signature is valid or trusted: that needs
Get-AuthenticodeSignature on Windows), size and SHA-256. A present table is not evidence of acceptance by any App Control policy.
"""
import argparse
import collections
import hashlib
import json
import struct
from pathlib import Path


def pe_info(path):
    with open(path, 'rb') as stream:
        head = stream.read(4096)
        if head[:2] != b'MZ':
            return None
        offset = struct.unpack_from('<I', head, 0x3C)[0]
        if offset + 160 > len(head):
            stream.seek(offset)
            head = stream.read(512)
            offset = 0
        if head[offset:offset + 4] != b'PE\0\0':
            return None
        machine = struct.unpack_from('<H', head, offset + 4)[0]
        optional = offset + 24
        magic = struct.unpack_from('<H', head, optional)[0]
        directories = optional + (112 if magic == 0x20B else 96)
        cert_offset, cert_size = struct.unpack_from('<II', head, directories + 4 * 8)
        return {'machine': {0x8664: 'amd64', 0x14C: 'x86', 0xAA64: 'arm64'}.get(machine, hex(machine)), 'certificate_table': cert_size > 0}


def inventory(tree):
    tree = Path(tree)
    rows = []
    for path in sorted(tree.rglob('*')):
        if path.is_file() and path.suffix.lower() in ('.exe', '.dll', '.pyd'):
            info = pe_info(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            kind = {'.exe': 'exe', '.dll': 'dll', '.pyd': 'pyd'}[path.suffix.lower()]
            rows.append({'path': path.relative_to(tree).as_posix(), 'kind': kind, 'size': path.stat().st_size, 'sha256': digest, **(info or {'machine': 'not-pe', 'certificate_table': False})})
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('tree')
    parser.add_argument('--json')
    args = parser.parse_args()
    rows = inventory(args.tree)
    summary = collections.Counter((row['kind'], 'cert-table' if row['certificate_table'] else 'no-cert-table') for row in rows)
    result = {'files': len(rows), 'by_kind_and_state': {f'{k}:{s}': n for (k, s), n in sorted(summary.items())}, 'machines': sorted({row['machine'] for row in rows}),
              'with_certificate_table': [row['path'] for row in rows if row['certificate_table']], 'total_image_bytes': sum(row['size'] for row in rows)}
    print(json.dumps(result, indent=1))
    if args.json:
        Path(args.json).write_text(json.dumps({**result, 'images': rows}, indent=1) + '\n')


if __name__ == '__main__':
    main()
