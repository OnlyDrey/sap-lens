"""Dependency/wheel closure, runtime integrity and reproducibility. No network except where the wheel cache is already populated."""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import ROOT, RUNTIME
import common

REPOSITORY = ROOT.parents[1]
LOCK = json.loads((ROOT / 'runtime' / 'lock.json').read_text())


def pins():
    result = {}
    for line in (REPOSITORY / 'backend' / 'requirements.txt').read_text().splitlines():
        line = line.split('#')[0].strip()
        if line and not line.startswith('-'):
            name, version = re.split(r'==', line.split(';')[0].strip())
            result[re.sub(r'[-_.]+', '-', name).lower()] = version
    return result


class LockClosure(unittest.TestCase):
    def test_every_backend_pin_is_locked_for_both_platforms_at_the_same_version(self):
        direct = pins()
        for platform in ('linux', 'windows'):
            locked = {re.sub(r'[-_.]+', '-', w['name']).lower(): w['version'] for w in LOCK['wheels'][platform]}
            for name, version in direct.items():
                self.assertEqual(locked.get(name), version, f'{name} on {platform}')

    def test_lock_is_closed_over_wheel_metadata(self):
        """Every unconditional Requires-Dist of every locked wheel is itself locked (needs the populated wheel cache)."""
        import zipfile
        for platform, wheels in LOCK['wheels'].items():
            names = {re.sub(r'[-_.]+', '-', w['name']).lower() for w in wheels}
            if not names >= set(pins()):
                self.fail(f'direct pins missing on {platform}')
            for wheel in wheels:
                paths = list(common.CACHE.rglob(wheel['file']))
                if not paths:
                    self.skipTest('wheel cache not populated')
                with zipfile.ZipFile(paths[0]) as archive:
                    metadata = next(archive.read(n).decode() for n in archive.namelist() if n.endswith('.dist-info/METADATA'))
                for line in metadata.splitlines():
                    if line.startswith('Requires-Dist:') and 'extra ==' not in line:
                        spec = line.split(':', 1)[1].strip()
                        required = re.sub(r'[-_.]+', '-', re.split(r'[ ;<>=!~(\[]', spec)[0]).lower()
                        if ';' in spec and required not in names:
                            continue  # environment-marked and not selected for this platform
                        self.assertIn(required, names, f'{wheel["file"]} requires {required} on {platform}')

    def test_only_hashed_binary_wheels(self):
        for platform, wheels in LOCK['wheels'].items():
            for wheel in wheels:
                self.assertTrue(wheel['file'].endswith('.whl'), wheel['file'])
                self.assertRegex(wheel['sha256'], r'^[0-9a-f]{64}$')
                if not re.search(r'-(py3|py2\.py3)-none-any\.whl$', wheel['file']):
                    tag = 'win_amd64' if platform == 'windows' else 'manylinux'
                    self.assertIn(tag, wheel['file'], f'wrong platform tag: {wheel["file"]}')
                    self.assertIn('cp312', wheel['file'].replace('abi3', 'cp312') if 'abi3' in wheel['file'] else wheel['file'])

    def test_interpreter_pins_are_hashed_and_https(self):
        for platform, archive in LOCK['python']['archives'].items():
            self.assertRegex(archive['sha256'], r'^[0-9a-f]{64}$')
            self.assertTrue(archive['url'].startswith('https://'), platform)
            self.assertIn('3.12', LOCK['python']['version'])

    def test_no_wheel_file_duplicated_with_different_hash(self):
        for wheels in LOCK['wheels'].values():
            self.assertEqual(len({w['file'] for w in wheels}), len(wheels))

    def test_cached_wheels_match_the_lock_when_present(self):
        cache = common.CACHE
        checked = 0
        for platform, wheels in LOCK['wheels'].items():
            for wheel in wheels:
                for path in cache.rglob(wheel['file']):
                    self.assertEqual(common.sha256_file(path), wheel['sha256'], path.name)
                    checked += 1
        if not checked:
            self.skipTest('wheel cache not populated')


class SafeExtraction(unittest.TestCase):
    def test_traversal_and_absolute_members_are_refused(self):
        for bad in ('../x', 'a/../../x', '/etc/passwd', 'C:/x', '..\\x'):
            with self.assertRaises(SystemExit, msg=bad):
                common.safe_member_path(bad)

    def test_good_paths_are_normalised(self):
        self.assertEqual(common.safe_member_path('./a//b'), 'a/b')


class Integrity(unittest.TestCase):
    def setUp(self):
        if not (RUNTIME / 'manifest.json').is_file():
            self.skipTest('assembled runtime missing')
        self.copy = Path(tempfile.mkdtemp(prefix='poc-integrity-'))
        # A small synthetic tree keeps the tamper tests fast; the real tree is verified once below.
        (self.copy / 'a').mkdir()
        (self.copy / 'a' / 'x.py').write_text('print(1)\n')
        (self.copy / 'b.bin').write_bytes(b'\0' * 10)
        (self.copy / 'manifest.json').write_text(json.dumps(common.tree_manifest(self.copy)))

    def tearDown(self):
        shutil.rmtree(self.copy, ignore_errors=True)

    def test_intact_tree_verifies(self):
        self.assertEqual(common.verify_tree(self.copy), [])

    def test_changed_file_is_detected(self):
        (self.copy / 'a' / 'x.py').write_text('print(2)\n')
        self.assertEqual(common.verify_tree(self.copy), ['changed: a/x.py'])

    def test_missing_file_is_detected(self):
        (self.copy / 'b.bin').unlink()
        self.assertEqual(common.verify_tree(self.copy), ['missing: b.bin'])

    def test_unexpected_file_is_detected(self):
        (self.copy / 'evil.pyd').write_bytes(b'x')
        self.assertEqual(common.verify_tree(self.copy), ['unexpected: evil.pyd'])

    def test_missing_manifest_is_a_problem_not_a_pass(self):
        (self.copy / 'manifest.json').unlink()
        self.assertTrue(common.verify_tree(self.copy))

    def test_assembled_runtime_is_intact_and_has_no_foreign_paths(self):
        self.assertEqual(common.verify_tree(RUNTIME), [])
        manifest = json.loads((RUNTIME / 'manifest.json').read_text())
        for record in manifest['files']:
            if record['type'] == 'link':
                self.assertFalse(record['target'].startswith('/'), record)
        # No SAP data, settings, logs or credentials ship in the runtime.
        forbidden = re.compile(r'(^|/)(\.env|.*\.log|settings\.json|.*\.pem|.*\.key)$')
        self.assertEqual([r['path'] for r in manifest['files'] if forbidden.search(r['path']) and 'site-packages' not in r['path'] and '/test' not in r['path']
                          and 'lib/python3.12' not in r['path']], [])


class Reproducibility(unittest.TestCase):
    def test_two_assemblies_are_identical(self):
        if not any(common.CACHE.rglob('*.whl')):
            self.skipTest('wheel cache not populated')
        base = Path(tempfile.mkdtemp(prefix='poc-repro-'))
        try:
            results = []
            for index in ('a', 'b'):
                completed = subprocess.run([sys.executable, str(ROOT / 'runtime' / 'assemble.py'), '--platform', 'linux', '--prune', '--source-commit', 'fixed',
                                            '--out', str(base / index / 'tree'), '--archive', str(base / f'{index}.tar.gz')],
                                           capture_output=True, text=True, timeout=600)
                self.assertEqual(completed.returncode, 0, completed.stderr[-500:])
                results.append(json.loads(completed.stdout.strip().splitlines()[-1]))
            self.assertEqual(results[0]['root_sha256'], results[1]['root_sha256'])
            self.assertEqual(results[0]['archive_sha256'], results[1]['archive_sha256'])
            self.assertEqual(common.sha256_file(base / 'a.tar.gz'), common.sha256_file(base / 'b.tar.gz'))
        finally:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
