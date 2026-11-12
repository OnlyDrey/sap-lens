"""Host-only files of a container installation: TLS certificate, private key, backup recovery key and proxy token.

Run by deploy/docker/manage.sh inside the image (no network, no data volume) against the installation's local-config directory.
Every file is created exclusively: an existing certificate, key or token is never replaced, read back or printed.
Files are owned by the installing user and readable by the container group only (0640); the certificate is public (0644).
"""
import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sys

VALID_DAYS = 825
NAME = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*')


class SetupError(ValueError):
    pass


def subject_names(hosts):
    """DNS names and IP addresses for the SAN: the public names plus the loopback names the health probe and local use need."""
    names, seen = [], set()
    for host in [*hosts, 'localhost', '127.0.0.1', '::1']:
        host = host.strip().lower().strip('[]')
        if not host or host in seen: continue
        try: address = ipaddress.ip_address(host)
        except ValueError: address = None
        if address is not None:
            if address.is_unspecified: raise SetupError('A certificate cannot name an unspecified address.')
            names.append(('ip', address))
        else:
            if len(host) > 253 or not NAME.fullmatch(host) or host.replace('.', '').isdigit(): raise SetupError('Use explicit host names or IP addresses; wildcards are not issued.')
            names.append(('dns', host))
        seen.add(host)
    return names


def exclusive(path, data, mode, owner, group):
    """Create only; a present file (or link) is left exactly as it is."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chmod(path, mode)  # before the ownership change: afterwards the file belongs to the installing user
        if owner is not None: os.chown(path, owner, group)
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise


def describe(certificate_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    certificate = x509.load_pem_x509_certificate(Path(certificate_path).read_bytes())
    try: names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound: names = []
    return dict(sha256=certificate.fingerprint(hashes.SHA256()).hex(), not_after=certificate.not_valid_after_utc.isoformat(),
                self_signed=certificate.issuer == certificate.subject,
                names=[str(item.value) for item in names], expired=certificate.not_valid_after_utc <= datetime.now(timezone.utc))


def generate_tls(directory, hosts, owner=None, group=None, now=None):
    """A self-signed ECDSA P-256 server certificate for the given names. Refuses when either file exists."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    directory = Path(directory); certificate_path, key_path = directory / 'tls.crt', directory / 'tls.key'
    if os.path.lexists(certificate_path) or os.path.lexists(key_path):
        raise SetupError('A certificate or private key already exists and is never replaced. Remove both deliberately to issue a new pair.')
    names = subject_names(hosts)
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'SAP Lens self-signed ' + str(names[0][1])[:40])])
    start = (now or datetime.now(timezone.utc)) - timedelta(minutes=5)
    san = x509.SubjectAlternativeName([x509.DNSName(value) if kind == 'dns' else x509.IPAddress(value) for kind, value in names])
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(start).not_valid_after(start + timedelta(days=VALID_DAYS))
                   .add_extension(san, critical=False).add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                   .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False, data_encipherment=False,
                                                key_agreement=False, key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
                   .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False).sign(key, hashes.SHA256()))
    exclusive(key_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()), 0o640, owner, group)
    try: exclusive(certificate_path, certificate.public_bytes(serialization.Encoding.PEM), 0o644, owner, group)
    except BaseException:
        key_path.unlink(missing_ok=True)  # only the key this call created
        raise
    return describe(certificate_path)


def install_tls(directory, certificate, key, hosts, owner=None, group=None):
    """Copy an administrator-supplied pair after proving it loads, matches, is valid now and covers the public names."""
    import ssl
    from deployment import certificate_has_name
    directory = Path(directory); certificate_path, key_path = directory / 'tls.crt', directory / 'tls.key'
    if os.path.lexists(certificate_path) or os.path.lexists(key_path):
        raise SetupError('A certificate or private key already exists and is never replaced.')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try: context.load_cert_chain(certificate, key)
    except (ssl.SSLError, OSError, ValueError): raise SetupError('The supplied certificate and private key do not load as a matching, unencrypted PEM pair.') from None
    details = describe(certificate)
    if details['expired']: raise SetupError('The supplied certificate has expired.')
    decoded = ssl._ssl._test_decode_cert(str(certificate))
    uncovered = [host for host in hosts if not certificate_has_name(decoded, host.strip().lower().strip('[]'))]
    if uncovered: raise SetupError('The supplied certificate does not cover: ' + ', '.join(uncovered))
    exclusive(key_path, Path(key).read_bytes(), 0o640, owner, group)
    try: exclusive(certificate_path, Path(certificate).read_bytes(), 0o644, owner, group)
    except BaseException:
        key_path.unlink(missing_ok=True)
        raise
    return describe(certificate_path)


def backup_key(directory, owner=None, group=None):
    path = Path(directory) / 'backup.key'
    if os.path.lexists(path): raise SetupError('A backup recovery key already exists and is never replaced.')
    import base64
    exclusive(path, base64.b64encode(secrets.token_bytes(32)) + b'\n', 0o640, owner, group)
    return dict(created=True, escrow_required=True)


def proxy_token(directory, owner=None, group=None):
    path = Path(directory) / 'proxy-token.secret'
    if os.path.lexists(path): raise SetupError('A proxy token already exists and is never replaced.')
    exclusive(path, secrets.token_urlsafe(48).encode('ascii') + b'\n', 0o640, owner, group)
    return dict(created=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('action', choices=['generate-tls', 'install-tls', 'describe-tls', 'backup-key', 'proxy-token'])
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--host', action='append', default=[])
    parser.add_argument('--certificate', type=Path); parser.add_argument('--key', type=Path)
    parser.add_argument('--owner', type=int); parser.add_argument('--group', type=int)
    args = parser.parse_args(argv)
    try:
        if args.action == 'generate-tls': result = generate_tls(args.directory, args.host, args.owner, args.group)
        elif args.action == 'install-tls':
            if not args.certificate or not args.key: raise SetupError('Specify --certificate and --key.')
            result = install_tls(args.directory, args.certificate, args.key, args.host, args.owner, args.group)
        elif args.action == 'describe-tls': result = describe(args.directory / 'tls.crt')
        elif args.action == 'backup-key': result = backup_key(args.directory, args.owner, args.group)
        else: result = proxy_token(args.directory, args.owner, args.group)
    except SetupError as error:
        print(str(error), file=sys.stderr); return 1
    except (OSError, ValueError) as error:
        # Paths and file content never reach the terminal or a log.
        print(f'Host file setup failed safely ({type(error).__name__}); existing files were not changed.', file=sys.stderr); return 1
    print(json.dumps(result)); return 0


if __name__ == '__main__':
    sys.exit(main())
