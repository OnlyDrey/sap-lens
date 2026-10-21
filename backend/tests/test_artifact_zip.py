"""Raw ZIP integrity, exact members, CRC and extraction safety with synthetic bytes."""
import hashlib
import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest
import warnings
import zipfile

spec = importlib.util.spec_from_file_location('artifact_zip', Path(__file__).resolve().parents[2] / 'scripts/verify-artifact-zip.py')
artifact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifact)


class ArtifactZipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.download = self.root/'download'; self.download.mkdir()
        self.destination = self.root/'distribution'
        self.path = self.download/'service-filename.zip'

    def write(self, entries=None):
        with zipfile.ZipFile(self.path, 'w') as archive, warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)  # Synthetic duplicate fixture, not a deprecation.
            for name, data in entries or [('SAP-Lens.exe', b'MZsynthetic'), ('SAP-Lens.exe.sha256', b'0'*64+b'  SAP-Lens.exe\n')]:
                archive.writestr(name, data)
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_exact_distribution_verified_with_service_selected_zip_filename(self):
        digest = self.write()
        artifact.verify(self.download, self.destination, 'sha256:'+digest)
        self.assertEqual({path.name for path in self.destination.iterdir()}, artifact.EXPECTED)
        self.assertEqual((self.destination/'SAP-Lens.exe').read_bytes(), b'MZsynthetic')

    def test_missing_or_wrong_digest_and_extra_downloads_rejected(self):
        self.write()
        for digest in ('', '0'*64):
            with self.assertRaises(ValueError): artifact.verify(self.download, self.destination, digest)
        digest = self.write(); (self.download/'extra').write_bytes(b'x')
        with self.assertRaises(ValueError): artifact.verify(self.download, self.destination, digest)
        self.assertFalse(self.destination.exists())

    def test_duplicates_extra_members_and_path_traversal_rejected_before_extraction(self):
        for names in [('SAP-Lens.exe','SAP-Lens.exe'), ('SAP-Lens.exe','../SAP-Lens.exe.sha256'),
                      ('SAP-Lens.exe','SAP-Lens.exe.sha256','extra'), ('SAP-Lens.exe',),
                      ('SAP-Lens.exe','SAP-Lens.exe.sha256','folder/')]:
            with self.subTest(names=names):
                digest = self.write([(name,b'x') for name in names])
                with self.assertRaises(ValueError): artifact.verify(self.download, self.destination, digest)
                self.assertFalse(self.destination.exists())

    def test_symlink_and_oversized_checksum_rejected(self):
        link = zipfile.ZipInfo('SAP-Lens.exe'); link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for entries in [[(link,b'target'),('SAP-Lens.exe.sha256',b'x')],
                        [('SAP-Lens.exe',b'x'),('SAP-Lens.exe.sha256',b'x'*129)]]:
            digest = self.write(entries)
            with self.assertRaises(ValueError): artifact.verify(self.download, self.destination, digest)

    def test_existing_destination_is_not_overwritten(self):
        digest = self.write(); self.destination.mkdir()
        sentinel = self.destination/'sentinel'; sentinel.write_text('preserve')
        with self.assertRaises(ValueError): artifact.verify(self.download, self.destination, digest)
        self.assertEqual(sentinel.read_text(), 'preserve')

    def test_crc_failure_rejected_even_with_correct_outer_digest(self):
        self.write(); data = self.path.read_bytes().replace(b'MZsynthetic', b'MZcorrupted')
        self.path.write_bytes(data)
        with self.assertRaises(zipfile.BadZipFile):
            artifact.verify(self.download, self.destination, hashlib.sha256(data).hexdigest())
        self.assertFalse(self.destination.exists())
