"""Guards for the scripts directory layout: no stale script paths, shipped files keep their bundle-relative paths, every script compiles."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
HISTORY = {'docs/development/PROGRESS.md', 'docs/development/REPOSITORY_AUDIT.md'}   # describe the old layout on purpose
SKIP_SUFFIXES = ('.png', '.ico', '.xlsx', 'package-lock.json')


def tracked():
    return [name for name in subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).split('\n') if name and not name.endswith(SKIP_SUFFIXES)]


class ScriptLayout(unittest.TestCase):
    def test_every_scripts_path_named_in_active_files_exists(self):
        pattern = re.compile(r'(?<![\w.-])scripts/((?:[\w.-]+/)*[\w-]+\.(?:py|ps1|mjs|json|txt))(?![\w-])')
        files = set(tracked())
        missing = []
        for name in sorted(files - HISTORY):
            path = ROOT / name
            if not path.is_file():
                continue
            for match in pattern.finditer(path.read_text(encoding='utf-8', errors='ignore')):
                relative = 'scripts/' + match.group(1)
                if relative not in files and not (ROOT / relative).exists():
                    missing.append(f'{name}: {relative}')
        # fixtures that build throw-away repositories name scripts that exist only inside the fixture
        allowed = {'backend/tests/test_build_diagnostics.py: scripts/tool.mjs', 'backend/tests/test_build_diagnostics.py: scripts/__pycache__/c.py'}
        # this file names the same fixture paths in the allowlist above
        allowed |= {'backend/tests/test_scripts_layout.py: scripts/tool.mjs', 'backend/tests/test_scripts_layout.py: scripts/__pycache__/c.py'}
        # a path that must NOT be ignored by Git is named as a probe; it is never a real script
        allowed |= {'backend/tests/test_artifact_layout.py: scripts/Trace-SAPLensPowerShell.ps1', 'backend/tests/test_scripts_layout.py: scripts/Trace-SAPLensPowerShell.ps1'}
        self.assertEqual([item for item in missing if item not in allowed], [])

    def test_shipped_scripts_keep_their_bundle_relative_paths(self):
        source = (ROOT / 'scripts/deployment-package.py').read_text(encoding='utf-8')
        listed = re.search(r"selected\+=\[('scripts/[^\]]+)\]", source).group(1)
        self.assertEqual(sorted(re.findall(r"'(scripts/[\w.-]+)'", listed)), ['scripts/deployment-package.py', 'scripts/install-linux-server.py', 'scripts/run-installed-server.py'])
        for name in ('deployment-package.py', 'install-linux-server.py', 'run-installed-server.py'):
            self.assertTrue((ROOT / 'scripts' / name).is_file(), 'a bundled script must sit where the bundle expects it')
        installer = (ROOT / 'scripts/install-linux-server.py').read_text(encoding='utf-8')
        self.assertIn("BUNDLE / 'scripts' / (name + '.py')", installer)
        self.assertIn('Path(__file__).resolve().parents[1]', installer)

    def test_the_service_bundle_sources_have_not_moved(self):
        for relative in ('scripts/manage-server-service.ps1', 'deploy/windows/LICENSE-WinSW.txt', 'deploy/windows/ServiceManager.cs', 'deploy/windows/desktop-installer.iss', 'docs/deployment/WINDOWS_SERVICE.md'):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_moved_scripts_find_the_repository_two_levels_up(self):
        for directory in ('packaging', 'deployment', 'testing'):
            for script in sorted((ROOT / 'scripts' / directory).glob('*.py')):
                text = script.read_text(encoding='utf-8')
                with self.subTest(script=script.name):
                    self.assertNotIn('parents[1]', text, 'a script one level deeper must use parents[2]')
                    compile(text, str(script), 'exec')

    def test_every_script_compiles(self):
        for script in sorted((ROOT / 'scripts').rglob('*.py')):
            if '__pycache__' not in script.parts:
                compile(script.read_text(encoding='utf-8'), str(script), 'exec')

    def test_the_top_level_keeps_only_entrypoints_shipped_files_and_windows_scripts(self):
        top = sorted(path.name for path in (ROOT / 'scripts').iterdir() if path.is_file())
        self.assertEqual([name for name in top if name.endswith('.py')],
                         ['build.py', 'check-docs.py', 'check-workflows.py', 'deployment-package.py', 'install-linux-server.py', 'run-installed-server.py', 'run-tests.py', 'validate.py'])


if __name__ == '__main__':
    unittest.main()
