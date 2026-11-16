"""Local secret and environment-value scan (no GitHub Actions needed). Read-only; prints file, line and rule, never the matched value.

  python scripts/check-secrets.py                 tracked files of the working tree (default)
  python scripts/check-secrets.py --history       every line ever added on any ref (local clone)
  python scripts/check-secrets.py --path DIR      every file under DIR (for example a release folder before publishing)

Rules: private key blocks with a key body, well-known token formats (GitHub, AWS, Slack, Anthropic/OpenAI style keys, JWTs), connection strings
with a password, and committed key/certificate/secret files. Personal infrastructure values (host names, addresses, user names) are not
hard-coded here, which would publish them again: list them one per line in the git-ignored file .secret-scan.local and they are reported as
"local deny list #n". A line can opt out of the token rules with the marker `secret-scan: allow` (synthetic test fixtures only).
Exit code 0 clean, 1 findings, 2 usage or Git error."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES = [
    ('private key', re.compile(r'-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----\s*(?:\\n)?[A-Za-z0-9+/=\r\n]{40,}')),
    ('GitHub token', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b')),
    ('AWS access key', re.compile(r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b')),
    ('Slack token', re.compile(r'\bxox[abprs]-[0-9A-Za-z-]{10,}')),
    ('API key (sk- style)', re.compile(r'\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}')),
    ('JSON web token', re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}')),
    # Connection-string syntax only (key=value pairs separated by semicolons), not keyword arguments such as password=value in code.
    ('connection string password', re.compile(r'(?i)(?:;\s*(?:password|pwd|accountkey|sharedaccesskey)=(?!\$|\{|<|%|\*)[^;"\'\s]{8,}'
                                              r'|\b(?:password|pwd|accountkey|sharedaccesskey)=(?!\$|\{|<|%|\*)[^;"\'\s]{8,};)')),
]
SECRET_FILES = re.compile(r'(?i)(?:^|/)(?:[^/]+\.(?:pfx|p12|key|pem|jks|keystore|kdbx|ppk)|id_(?:rsa|ed25519|ecdsa)|cert-password|api-token|\.env)$')
ALLOW = 'secret-scan: allow'
SKIP_SUFFIXES = ('.png', '.jpg', '.jpeg', '.gif', '.ico', '.webp', '.woff', '.woff2', '.ttf', '.xlsx', '.docx', '.pdf', '.zip', '.lock')
SKIP_NAMES = ('package-lock.json',)


def deny_list() -> list[str]:
    path = ROOT / '.secret-scan.local'
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding='utf-8').splitlines() if line.strip() and not line.lstrip().startswith('#')]


def scan_line(text: str, denied: list[str]) -> list[str]:
    found = [] if ALLOW in text else [name for name, pattern in RULES if pattern.search(text)]
    lowered = text.lower()
    found += [f'local deny list #{index}' for index, value in enumerate(denied, 1) if value.lower() in lowered]
    return found


def scannable(name: str) -> bool:
    return not name.endswith(SKIP_SUFFIXES) and Path(name).name not in SKIP_NAMES


def git(*args: str) -> str:
    done = subprocess.run(['git', '-C', str(ROOT), *args], capture_output=True, text=True, encoding='utf-8', errors='replace')
    if done.returncode:
        raise SystemExit(f'check-secrets: git {args[0]} failed: {done.stderr.strip()}')
    return done.stdout


def scan_files(paths: list[Path], base: Path, denied: list[str]) -> list[str]:
    findings = []
    for path in paths:
        name = path.relative_to(base).as_posix()
        if SECRET_FILES.search(name) and not name.endswith('.example'):
            findings.append(f'{name}: secret or key file')
        if not scannable(name) or not path.is_file():
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            findings += [f'{name}:{number}: {rule}' for rule in scan_line(line, denied)]
    return findings


def scan_history(denied: list[str]) -> list[str]:
    findings, commit, name = [], '', ''
    log = subprocess.Popen(['git', '-C', str(ROOT), 'log', '--all', '-p', '-U0', '--no-color', '--format=commit %h'], stdout=subprocess.PIPE, text=True,
                           encoding='utf-8', errors='replace')
    assert log.stdout
    for line in log.stdout:
        if line.startswith('commit '):
            commit = line.split()[1]
        elif line.startswith('+++ '):
            name = line[6:].rstrip('\n') if line.startswith('+++ b/') else ''
            if name and SECRET_FILES.search(name) and not name.endswith('.example'):
                findings.append(f'{commit} {name}: secret or key file')
        elif line.startswith('+') and name and scannable(name):
            findings += [f'{commit} {name}: {rule}' for rule in scan_line(line[1:], denied)]
    log.wait()
    return sorted(set(findings))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--history', action='store_true', help='scan every added line on every ref')
    parser.add_argument('--path', help='scan every file under this folder instead of the tracked files')
    args = parser.parse_args()
    denied = deny_list()
    if args.history:
        findings = scan_history(denied)
        scope = 'history of all refs'
    elif args.path:
        base = Path(args.path).resolve()
        if not base.is_dir():
            print(f'check-secrets: {base} is not a folder', file=sys.stderr)
            return 2
        findings = scan_files(sorted(p for p in base.rglob('*') if p.is_file()), base, denied)
        scope = str(base)
    else:
        findings = scan_files([ROOT / name for name in git('ls-files', '-z').split('\0') if name], ROOT, denied)
        scope = 'tracked files'
    for finding in findings:
        print(finding)
    print(f'Secret scan ({scope}, {len(denied)} local deny-list entries): {len(findings)} finding(s).')
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main())
