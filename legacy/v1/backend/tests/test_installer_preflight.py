"""Installer prerequisites are checked before anything is created, and a failed staging leaves the system as it was."""
import importlib.util
import socket
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load():
    spec = importlib.util.spec_from_file_location('install_linux_server_under_test', ROOT / 'scripts/install-linux-server.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


class LinuxPreflightTests(unittest.TestCase):
    def setUp(self):
        self.module = load()

    def test_missing_venv_support_is_reported_before_any_change(self):
        real = importlib.util.find_spec
        with patch.object(self.module.importlib.util, 'find_spec', side_effect=lambda name, *a: None if name == 'ensurepip' else real(name, *a)):
            with self.assertRaises(self.module.maintenance.MaintenanceError) as raised:
                self.module.runtime_preflight(False)
        self.assertIn('python3.12-venv', str(raised.exception)); self.assertIn('nothing was changed', str(raised.exception))

    def test_a_busy_port_stops_a_fresh_install_but_not_an_upgrade(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
            holder.bind(('127.0.0.1', 0)); port = holder.getsockname()[1]
            with self.assertRaises(self.module.maintenance.MaintenanceError) as raised:
                self.module.runtime_preflight(True, port)
            self.assertIn(str(port), str(raised.exception))
            self.module.runtime_preflight(False, port)   # the running service legitimately owns its port during an upgrade

    def test_a_free_port_and_working_venv_pass(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        self.module.runtime_preflight(True, port)

    def test_a_failed_staging_removes_only_its_own_release(self):
        text = (ROOT / 'scripts/install-linux-server.py').read_text()
        self.assertIn('except BaseException:', text); self.assertIn('shutil.rmtree(release, ignore_errors=True)', text)
        # The rollback sits inside the `not same` branch, after the guard that refuses to reuse an existing release directory.
        self.assertLess(text.index("raise maintenance.MaintenanceError('A staged release already exists"), text.index('except BaseException:'))

    def test_preflight_runs_before_the_first_mutation(self):
        text = (ROOT / 'scripts/install-linux-server.py').read_text()
        body = text[text.index('def install(args, unit, marker):'):]
        for mutation in ("'useradd'", 'args.prefix.mkdir', 'shutil.copytree'):
            self.assertLess(body.index('runtime_preflight(old is None)'), body.index(mutation))

    def test_root_and_systemd_checks_remain(self):
        text = (ROOT / 'scripts/install-linux-server.py').read_text()
        for guard in ('os.geteuid() != 0', '/run/systemd/system', 'glibc 2.35+', "platform.machine() != 'x86_64'"): self.assertIn(guard, text)


class WindowsInstallerContractTests(unittest.TestCase):
    """No PowerShell or Inno Setup runs on this host: these are static guards, not execution evidence."""
    def test_service_install_validates_the_host_before_changing_anything(self):
        text = (ROOT / 'scripts/manage-server-service.ps1').read_text()
        install = text[text.index("if ($Action -eq 'Install')"):]
        first_change = min(install.index(token) for token in ('New-Item', 'sc.exe', 'icacls') if token in install)
        for guard in ('Is64BitOperatingSystem', 'Get-NetTCPConnection', 'already exists'):
            self.assertLess(install.index(guard), first_change, guard)
        self.assertIn('IsInRole', text)

    def test_desktop_installer_is_per_user_x64_windows10_and_checks_webview2(self):
        text = (ROOT / 'deploy/windows/desktop-installer.iss').read_text()
        for setting in ('PrivilegesRequired=lowest', 'ArchitecturesAllowed=x64compatible', 'MinVersion=10.0', 'WebView2'): self.assertIn(setting, text)
        self.assertNotIn('python', text.lower().replace('pythonw', ''))        # the packaged desktop needs no Python, pip, Node or npm

    def test_packaged_applications_do_not_require_developer_tooling(self):
        for relative in ('deploy/windows/desktop-installer.iss', 'deploy/linux/sap-lens.service'):
            text = (ROOT / relative).read_text().lower()
            for tool in ('npm', 'node.exe', 'pyinstaller', 'pip install'): self.assertNotIn(tool, text, relative)


if __name__ == '__main__':
    unittest.main()
