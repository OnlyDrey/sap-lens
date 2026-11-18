"""Synthetic TLS certificates for tests, generated in-process (no OpenSSL command-line tool, so the tests also run on Windows)."""
from datetime import datetime, timedelta, timezone
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def issue(directory, name, san, days=30, bits=2048, curve=None, start=None, common_name='localhost'):
    """Write <name>.crt and <name>.key (unencrypted PEM) and return their paths as strings.

    san uses the OpenSSL notation ('DNS:localhost,IP:127.0.0.1'); an empty value issues no SAN extension. start is the
    notBefore offset from now (default five minutes ago); bits selects RSA, curve ('p256', 'p384') an EC key instead.
    """
    key = ec.generate_private_key(dict(p256=ec.SECP256R1, p384=ec.SECP384R1)[curve]()) if curve else rsa.generate_private_key(public_exponent=65537, key_size=bits)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    begin = datetime.now(timezone.utc) + (start if start is not None else timedelta(minutes=-5))
    builder = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
               .not_valid_before(begin).not_valid_after(begin + timedelta(days=days))
               .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
               .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False))
    names = []
    for entry in filter(None, (part.strip() for part in san.split(','))):
        kind, value = entry.split(':', 1)
        names.append(x509.IPAddress(ipaddress.ip_address(value)) if kind == 'IP' else x509.DNSName(value))
    if names: builder = builder.add_extension(x509.SubjectAlternativeName(names), critical=False)
    certificate = builder.sign(key, hashes.SHA256())
    directory = Path(directory); cert_path, key_path = directory / f'{name}.crt', directory / f'{name}.key'
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    return str(cert_path), str(key_path)
