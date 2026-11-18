"""Authenticated portable archive codec; no real data or installed key files."""
import copy
import json
import os
from pathlib import Path
import secrets
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import backup_crypto as crypto


class EncryptedArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='synthetic-backup-æ ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.host=secrets.token_bytes(32)
        self.source=self.root/'synthetic.tar.gz'
        self.payload=('SYNTHETIC Sensitive authorizations æøå\n'*40000).encode()
        self.source.write_bytes(self.payload)
        self.password='Synthetic recovery passphrase æøå 123!'

    def test_roundtrip_host_and_unicode_passphrase_streaming(self):
        for password in ('',self.password):
            with self.subTest(password_mode=bool(password)):
                operation=secrets.token_hex(16);plan=crypto.plan(operation,self.host,password)
                key,header=crypto.unwrap(operation,plan,self.host)
                archive=self.root/(operation+'.slbak')
                crypto.seal(self.source,archive,key,header)
                self.assertNotIn(b'SYNTHETIC Sensitive',archive.read_bytes())
                self.assertNotIn(self.password,json.dumps(plan))
                self.assertNotIn(crypto.encode(self.host),json.dumps(plan))
                result=self.root/(operation+'.plain')
                crypto.unseal(archive,result,passphrase=password,host=self.host)
                self.assertEqual(result.read_bytes(),self.payload)
                self.assertEqual(header['algorithm'],'AES-256-GCM')

    def test_same_plan_never_reuses_an_archive_nonce(self):
        plan=crypto.plan('a'*32,self.host)
        key,header=crypto.unwrap('a'*32,plan,self.host)
        first=self.root/'one';second=self.root/'two'
        one=crypto.seal(self.source,first,key,header);two=crypto.seal(self.source,second,key,header)
        self.assertNotEqual(one['nonce'],two['nonce'])
        self.assertNotEqual(first.read_bytes(),second.read_bytes())

    def test_wrong_key_password_ciphertext_and_tag_never_leave_plaintext(self):
        plan=crypto.plan('a'*32,self.host,self.password)
        key,header=crypto.unwrap('a'*32,plan,self.host)
        archive=self.root/'encrypted';crypto.seal(self.source,archive,key,header)
        output=self.root/'plain'
        with self.assertRaises(crypto.BackupCryptoError):crypto.unseal(archive,output,passphrase=self.password+'wrong')
        self.assertFalse(output.exists())
        original=archive.read_bytes()
        for where in (-1,len(original)//2):
            corrupt=bytearray(original);corrupt[where]^=1;archive.write_bytes(corrupt)
            with self.assertRaises(crypto.BackupCryptoError):crypto.unseal(archive,output,passphrase=self.password)
            self.assertFalse(output.exists())
        archive.write_bytes(original[:-20])
        with self.assertRaises(crypto.BackupCryptoError):crypto.unseal(archive,output,passphrase=self.password)
        self.assertFalse(output.exists())

    def test_pending_key_is_bound_to_operation_header_and_host(self):
        plan=crypto.plan('a'*32,self.host,self.password)
        for operation,host in [('b'*32,self.host),('a'*32,secrets.token_bytes(32))]:
            with self.assertRaises(crypto.BackupCryptoError):crypto.unwrap(operation,plan,host)
        altered=copy.deepcopy(plan);altered['header']['salt']=crypto.encode(secrets.token_bytes(16))
        with self.assertRaises(crypto.BackupCryptoError):crypto.unwrap('a'*32,altered,self.host)

    def test_malformed_duplicate_unknown_and_unbounded_headers_fail_early(self):
        plan=crypto.plan('a'*32,self.host)
        for change in [dict(format=True),dict(algorithm='AES-128-GCM'),dict(kdf='scrypt-1073741824-8-1'),dict(extra=True),dict(salt='bad')]:
            with self.assertRaises(crypto.BackupCryptoError):crypto.validate({**plan['header'],**change})
        malformed=self.root/'invalid';output=self.root/'plain'
        for raw in [b'{"format":2,"format":2}',b'{}',b'not-json',b'['*1200]:
            malformed.write_bytes(crypto.MAGIC+struct.pack('>I',len(raw))+raw+b'0'*16)
            with self.assertRaises(crypto.BackupCryptoError):crypto.unseal(malformed,output,host=self.host)
            self.assertFalse(output.exists())
        malformed.write_bytes(crypto.MAGIC+struct.pack('>I',4097))
        with self.assertRaises(crypto.BackupCryptoError):crypto.unseal(malformed,output,host=self.host)

    def test_existing_outputs_survive_and_partial_output_is_removed(self):
        plan=crypto.plan('a'*32,self.host);key,header=crypto.unwrap('a'*32,plan,self.host)
        archive=self.root/'existing';archive.write_bytes(b'preserve')
        with self.assertRaises(FileExistsError):crypto.seal(self.source,archive,key,header)
        self.assertEqual(archive.read_bytes(),b'preserve')
        archive.unlink()
        with patch.object(crypto,'MAX_ARCHIVE',10):
            with self.assertRaises(crypto.BackupCryptoError):crypto.seal(self.source,archive,key,header)
        self.assertFalse(archive.exists())
        with self.assertRaises(crypto.BackupCryptoError):crypto.seal(self.source,archive,b'x'*16,header)
        self.assertFalse(archive.exists())

    def test_key_provider_is_explicit_external_private_and_create_only(self):
        key=self.root/'host.key';data=self.root/'data';data.mkdir()
        with patch.dict(os.environ,{'SAP_LENS_BACKUP_KEY_FILE':''}):
            with self.assertRaises(crypto.BackupCryptoError):crypto.host_key(data)
        crypto.create_key(key,data)
        before=key.read_bytes()
        with self.assertRaises(FileExistsError):crypto.create_key(key,data)
        self.assertEqual(key.read_bytes(),before)
        with patch.dict(os.environ,{'SAP_LENS_BACKUP_KEY_FILE':str(key)}):self.assertEqual(len(crypto.host_key(data)),32)
        with self.assertRaises(crypto.BackupCryptoError):crypto.create_key(data/'unsafe.key',data)
        if os.name!='nt':
            key.chmod(0o644)
            with patch.dict(os.environ,{'SAP_LENS_BACKUP_KEY_FILE':str(key)}):
                with self.assertRaises(crypto.BackupCryptoError):crypto.host_key(data)
