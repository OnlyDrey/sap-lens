"""Packaging guards reject malformed binaries and private distribution inputs."""
import hashlib
import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location('verify_windows_package', Path(__file__).resolve().parents[2] / 'scripts/verify-windows-package.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class WindowsPackageTests(unittest.TestCase):
    def test_archive_requires_assets_and_rejects_private_inputs(self):
        assets = {name.replace('/', '\\') for name in package.REQUIRED}
        package.validate_archive_names(assets)
        with self.assertRaises(ValueError): package.validate_archive_names({'frontend/dist/index.html'})
        for private in ['settings.json', 'data/private.csv', 'branding/private.sap-lens.json', 'sap-lens.log', '.env', 'runtime.json']:
            with self.assertRaises(ValueError): package.validate_archive_names(assets | {private})

    def test_checksum_rejects_tampering_and_wrong_filename(self):
        payload = b'synthetic executable content'
        digest = hashlib.sha256(payload).hexdigest()
        self.assertEqual(package.validate_checksum(payload, digest+'  SAP-Lens.exe\n'), digest)
        with self.assertRaises(ValueError): package.validate_checksum(payload+b'changed', digest+'  SAP-Lens.exe')
        with self.assertRaises(ValueError): package.validate_checksum(payload, digest+'  other.exe')

    def test_gui_guard_rejects_console_subsystem_and_invalid_headers(self):
        data=bytearray(256);data[:2]=b'MZ';struct.pack_into('<I',data,0x3c,64);data[64:68]=b'PE\0\0'
        struct.pack_into('<H',data,64+24+68,2);package.validate_gui(data)
        struct.pack_into('<H',data,64+24+68,3)
        with self.assertRaises(ValueError):package.validate_gui(data)
        with self.assertRaises(ValueError):package.validate_gui(b'not an executable')
