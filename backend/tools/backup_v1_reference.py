"""Python v1 reference archives for SLBAK2 decryption: seals a synthetic payload with v1 backup_crypto in host-key and passphrase mode.
Usage: python -I tools/backup_v1_reference.py BACKEND_DIR OUT_DIR. Writes v1-host.slbak, v1-passphrase.slbak, payload.bin and keys.json (synthetic key/passphrase)."""
import json, os, sys, tempfile
backend, out = sys.argv[1:3]
sys.path.insert(0, backend)
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
import backup_crypto as c
payload = os.urandom(100_017)
with open(os.path.join(out, 'payload.bin'), 'wb') as s: s.write(payload)
host = bytes(range(32))
source = os.path.join(out, 'payload.bin')
for mode, passphrase in (('host', ''), ('passphrase', 'Synthetic v1 backup passphrase')):
    header = dict(format=2, algorithm='AES-256-GCM', key_mode='passphrase' if passphrase else 'host-key', kdf='scrypt-32768-8-1' if passphrase else 'hkdf-sha256',
                  salt=c.encode(os.urandom(16)), key_id='' if passphrase else c.fingerprint(host))
    key = c.derive(header, passphrase, host)
    target = os.path.join(out, f'v1-{mode}.slbak')
    if os.path.exists(target): os.remove(target)
    c.seal(source, target, key, header)
json.dump(dict(host_key=c.encode(host), passphrase='Synthetic v1 backup passphrase'), open(os.path.join(out, 'keys.json'), 'w'))
