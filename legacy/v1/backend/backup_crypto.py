"""Versioned streaming AES-256-GCM envelope around the canonical backup archive.

No archive is processed before authentication. Pending keys are wrapped with a
separately provisioned host key, never persisted as plaintext or next to archives.
"""
from contextlib import contextmanager
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC=b'SLBAK2\r\n'
MAX_ARCHIVE=2*1024*1024*1024
BLOCK=1024*1024
BASE={'format','algorithm','key_mode','kdf','salt','key_id'}


class BackupCryptoError(ValueError):
    pass


def encode(value):return base64.b64encode(value).decode('ascii')


def decode(value,size):
    try:
        if not isinstance(value,str) or len(value)>4*(size+2)//3+4:raise ValueError()
        raw=base64.b64decode(value,validate=True)
        if len(raw)!=size:raise ValueError()
        return raw
    except (ValueError,TypeError):raise BackupCryptoError('Invalid encrypted backup metadata.') from None


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')


def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise BackupCryptoError('Duplicate encrypted backup metadata.')
        result[key]=value
    return result


def validate(header, *, nonce=False):
    if not isinstance(header,dict) or set(header)!=BASE|({'nonce'} if nonce else set()):raise BackupCryptoError('Unsupported encrypted backup metadata.')
    if type(header['format']) is not int or header['format']!=2 or header['algorithm']!='AES-256-GCM':raise BackupCryptoError('Unsupported encrypted backup format.')
    expected={'passphrase':'scrypt-32768-8-1','host-key':'hkdf-sha256'}.get(header['key_mode'])
    if not expected or header['kdf']!=expected:raise BackupCryptoError('Unsupported backup key derivation.')
    decode(header['salt'],16)
    identity=header['key_id']
    if (header['key_mode']=='passphrase' and identity!='') or (header['key_mode']=='host-key' and (not isinstance(identity,str) or len(identity)!=16 or any(c not in '0123456789abcdef' for c in identity))):raise BackupCryptoError('Invalid backup key identity.')
    if nonce:decode(header['nonce'],12)
    return header


def fingerprint(key):return hashlib.sha256(key).hexdigest()[:16]


def expand(key,salt,info):return HKDF(algorithm=hashes.SHA256(),length=32,salt=salt,info=info).derive(key)


def derive(header,passphrase='',host_key=None):
    if header['key_mode']=='passphrase':
        if not isinstance(passphrase,str) or not 12<=len(passphrase)<=1024 or len(passphrase.encode('utf-8'))>4096:raise BackupCryptoError('Use the original backup passphrase (12–1024 characters).')
        return Scrypt(salt=decode(header['salt'],16),length=32,n=32768,r=8,p=1).derive(passphrase.encode('utf-8'))
    if host_key is None or len(host_key)!=32 or fingerprint(host_key)!=header['key_id']:raise BackupCryptoError('The matching separately stored recovery key is required.')
    return expand(host_key,decode(header['salt'],16),b'SAP Lens portable archive v2')


def safe_key_path(value,data=None):
    from maintenance import linked
    path=Path(value).expanduser()
    if not path.is_absolute() or any(linked(p) for p in (path,*path.parents)):raise BackupCryptoError('Use an absolute, non-linked protected recovery-key file.')
    if data is not None and path.resolve().is_relative_to(Path(data).resolve()):raise BackupCryptoError('The recovery-key file must be outside application data and backup archives.')
    return path


def create_key(path,data=None):
    """Explicit LOCAL operation; never overwrite or print an existing/new key."""
    path=safe_key_path(path,data)
    if not path.parent.is_dir():raise BackupCryptoError('Create a private recovery-key directory first.')
    created=False
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);created=True
        with os.fdopen(fd,'wb') as stream:
            if os.name=='nt':
                import windows_identity
                windows_identity.make_private(path)
            stream.write(encode(secrets.token_bytes(32)).encode('ascii')+b'\n');stream.flush();os.fsync(stream.fileno())
    except BaseException:
        if created:path.unlink(missing_ok=True)
        raise
    return {'created':True,'format':'base64-256-bit-key','escrow_required':True}


def key_path(data=None):
    value=os.environ.get('SAP_LENS_BACKUP_KEY_FILE','')
    if not value and data is not None:
        pointer=Path(data)/'backup-key-location.json'
        try:
            if pointer.is_symlink() or pointer.is_junction() or pointer.stat().st_size>4096:raise ValueError()
            stored=json.loads(pointer.read_bytes())
            if stored.get('schema')!=1:raise ValueError()
            value=stored['path']
        except FileNotFoundError:pass
        except (ValueError,OSError,KeyError,TypeError):raise BackupCryptoError('The host backup-key location is unreadable; configure it locally again.') from None
    if not value:raise BackupCryptoError('Configure a protected SAP_LENS_BACKUP_KEY_FILE outside application data; keep a separate recovery copy.')
    return safe_key_path(value,data)


def read_key(path,data=None):
    path=safe_key_path(path,data)
    try:
        from deployment import check_secret_permissions
        with path.open('rb') as stream:
            check_secret_permissions(path,os.fstat(stream.fileno()),os.environ.get('SAP_LENS_BACKUP_KEY_GROUP_READ','')=='1')
            raw=stream.read(97)
        if len(raw)>96:raise ValueError()
        return decode(raw.decode('ascii').strip(),32)
    except (ValueError,OSError,UnicodeError):raise BackupCryptoError('The protected backup recovery key is unavailable or has unsafe permissions.') from None


def host_key(data=None):return read_key(key_path(data),data)


def desktop_key(path,data):
    # Only the guarded native bridge/local CLI calls this; no server filesystem
    # path may be selected by a remote web request.
    path=safe_key_path(path,data)
    read_key(path,data)
    from config import atomic_write
    atomic_write(Path(data)/'backup-key-location.json',canonical({'schema':1,'path':str(path)}))
    return key_status(data)


def export_key(source,destination,data=None):
    value=read_key(source,data)
    destination=safe_key_path(destination,data)
    with private_output(destination) as stream:stream.write(encode(value).encode('ascii')+b'\n')
    return dict(exported=True,fingerprint=fingerprint(value),escrow_verification_required=True)


def key_status(data):
    try:
        host=host_key(data)
        marker=Path(data)/'.backup-key-confirmation.json'
        confirmed=False
        if marker.is_file() and not marker.is_symlink() and not marker.is_junction() and marker.stat().st_size<8192:
            value=json.loads(marker.read_bytes())
            confirmed=value.get('schema')==1 and value.get('fingerprint')==fingerprint(host)
        return dict(configured=True,fingerprint=fingerprint(host),escrow_verified=confirmed)
    except (ValueError,OSError,KeyError,TypeError):return dict(configured=False,escrow_verified=False)


def verify_escrow(offered,data):
    import hmac
    host=host_key(data)
    if not hmac.compare_digest(host,decode(offered.strip(),32)):raise BackupCryptoError('Recovery-key verification failed. Existing keys were not changed.')
    from config import atomic_write
    from review_identity import snapshot
    from datetime import datetime,timezone
    atomic_write(Path(data)/'.backup-key-confirmation.json',canonical(dict(schema=1,fingerprint=fingerprint(host),verified_at=datetime.now(timezone.utc).isoformat(),actor=snapshot())))
    return key_status(data)


def plan(operation,host,passphrase=''):
    if len(host)!=32:raise BackupCryptoError('Invalid host recovery key.')
    header=dict(format=2,algorithm='AES-256-GCM',key_mode='passphrase' if passphrase else 'host-key',kdf='scrypt-32768-8-1' if passphrase else 'hkdf-sha256',salt=encode(secrets.token_bytes(16)),key_id='' if passphrase else fingerprint(host))
    key=derive(header,passphrase,host)
    nonce=secrets.token_bytes(12)
    wrapping=expand(host,None,b'SAP Lens pending backup key v2')
    wrapped=AESGCM(wrapping).encrypt(nonce,key,b'SAP Lens operation '+operation.encode('ascii')+canonical(header))
    return {'header':header,'wrapped':encode(nonce+wrapped)}


def unwrap(operation,planned,host):
    try:
        if set(planned)!={'header','wrapped'} or len(host)!=32:raise ValueError()
        header=validate(planned['header']);raw=decode(planned['wrapped'],60)
        key=AESGCM(expand(host,None,b'SAP Lens pending backup key v2')).decrypt(raw[:12],raw[12:],b'SAP Lens operation '+operation.encode('ascii')+canonical(header))
        if len(key)!=32:raise ValueError()
        return key,header
    except (ValueError,TypeError,KeyError,InvalidTag):raise BackupCryptoError('Pending backup key could not be authenticated; cancel and prepare a new operation.') from None


@contextmanager
def private_output(path):
    from maintenance import directory, linked, private_file
    path=Path(path)
    directory(path.parent)
    if linked(path):raise BackupCryptoError('Linked archive output is not allowed.')
    created=False
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);created=True
        with os.fdopen(fd,'wb') as stream:
            private_file(path)
            yield stream
            stream.flush();os.fsync(stream.fileno())
    except BaseException:
        if created:path.unlink(missing_ok=True)
        raise


def seal(source,destination,key,header):
    validate(header)
    if not isinstance(key,bytes) or len(key)!=32:raise BackupCryptoError('AES-256 requires a 32-byte data key.')
    header={**header,'nonce':encode(secrets.token_bytes(12))}
    raw=canonical(header)
    cipher=Cipher(algorithms.AES(key),modes.GCM(decode(header['nonce'],12))).encryptor()
    cipher.authenticate_additional_data(MAGIC+raw)
    with private_output(destination) as output,Path(source).open('rb') as source_file:
        output.write(MAGIC+struct.pack('>I',len(raw))+raw)
        count=0
        while chunk:=source_file.read(BLOCK):
            count+=len(chunk)
            if count>MAX_ARCHIVE:raise BackupCryptoError('Portable archive exceeds the 2 GiB encrypted limit.')
            output.write(cipher.update(chunk))
        output.write(cipher.finalize());output.write(cipher.tag)
    return header


def envelope(source):
    if source.read(len(MAGIC))!=MAGIC:raise BackupCryptoError('Select a version 2 encrypted SAP Lens backup.')
    size=source.read(4)
    if len(size)!=4:raise BackupCryptoError('Truncated encrypted backup.')
    length=struct.unpack('>I',size)[0]
    if not 1<=length<=4096:raise BackupCryptoError('Invalid encrypted backup header size.')
    raw=source.read(length)
    try:header=validate(json.loads(raw,object_pairs_hook=unique),nonce=True)
    except (ValueError,TypeError,KeyError,UnicodeError,RecursionError):raise BackupCryptoError('Invalid encrypted backup metadata.') from None
    return header,raw


def unseal(source,destination,*,passphrase='',host=None,key=None):
    with Path(source).open('rb') as stream:
        header,raw=envelope(stream)
        key=key if key is not None else derive(header,passphrase,host)
        if not isinstance(key,bytes) or len(key)!=32:raise BackupCryptoError('AES-256 requires a 32-byte data key.')
        start=stream.tell();size=os.fstat(stream.fileno()).st_size;remaining=size-start-16
        if not 0<=remaining<=MAX_ARCHIVE:raise BackupCryptoError('Invalid encrypted backup size.')
        stream.seek(-16,2);tag=stream.read(16);stream.seek(start)
        cipher=Cipher(algorithms.AES(key),modes.GCM(decode(header['nonce'],12),tag)).decryptor()
        cipher.authenticate_additional_data(MAGIC+raw)
        try:
            with private_output(destination) as output:
                while remaining:
                    chunk=stream.read(min(BLOCK,remaining))
                    if not chunk:raise BackupCryptoError('Truncated encrypted backup.')
                    remaining-=len(chunk);output.write(cipher.update(chunk))
                output.write(cipher.finalize())
        except InvalidTag:raise BackupCryptoError('Backup authentication failed. Check the passphrase/recovery key and archive integrity.') from None
    return header
