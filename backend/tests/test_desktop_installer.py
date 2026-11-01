"""Installer resource guards; native compilation/SCM acceptance is not simulated."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from version import BUILD_INFO, make_deployment_info
spec=importlib.util.spec_from_file_location('installer_resources',ROOT/'scripts/verify-desktop-installer.py')
rules=importlib.util.module_from_spec(spec);spec.loader.exec_module(rules)


class InstallerResourceTests(unittest.TestCase):
    def image(self,version=None,signed=False,numeric=None,subsystem=2,product_numeric=None):
        values=numeric or BUILD_INFO['file_version']
        product=product_numeric or BUILD_INFO['file_version']
        strings={b'ProductName':b'SAP Lens',b'ProductVersion':(version or BUILD_INFO['version']).encode()}
        self.closed=False
        def close():self.closed=True
        return SimpleNamespace(OPTIONAL_HEADER=SimpleNamespace(Subsystem=subsystem,DATA_DIRECTORY=[SimpleNamespace(VirtualAddress=1 if signed else 0,Size=1 if signed else 0)]),
                               FileInfo=[[SimpleNamespace(StringTable=[SimpleNamespace(entries=strings)])]],
                               VS_FIXEDFILEINFO=[SimpleNamespace(FileVersionMS=values[0]<<16|values[1],FileVersionLS=values[2]<<16|values[3],
                                   ProductVersionMS=product[0]<<16|product[1],ProductVersionLS=product[2]<<16|product[3])],close=close)

    def verify(self,image):
        parser=SimpleNamespace(PE=lambda _:image,DIRECTORY_ENTRY={'IMAGE_DIRECTORY_ENTRY_SECURITY':0})
        with patch.dict(sys.modules,{'pefile':parser}):rules.verify(Path('synthetic-setup.exe'))

    def test_valid_installer_identity_and_unsigned_gui_resources(self):
        self.verify(self.image());self.assertTrue(self.closed)

    def test_changed_version_signature_numeric_or_console_resources_rejected(self):
        for values in [dict(version='99.0.0'),dict(signed=True),dict(numeric=[99,0,0,0]),dict(product_numeric=[99,0,0,0]),dict(subsystem=3)]:
            with self.subTest(values=values),self.assertRaises(ValueError):self.verify(self.image(**values))
            self.assertTrue(self.closed)

    def test_installer_channels_keep_numeric_resources_and_full_text_versions(self):
        source=(ROOT/'deploy/windows/desktop-installer.iss').read_text()
        setup=source.split('[Setup]',1)[1].split('[Tasks]',1)[0]
        directives=dict(line.split('=',1) for line in setup.splitlines() if '=' in line)
        for channel in ('alpha','beta','rc','stable'):
            info=make_deployment_info('0.1.0',channel,'1','a'*40,'123','12',1)
            with self.subTest(channel=channel):
                values={key:value.replace('{#NumericVersion}','.'.join(map(str,info['file_version'])))
                        .replace('{#FullVersion}',info['version']) for key,value in directives.items()}
                for key in ('VersionInfoVersion','VersionInfoProductVersion'):
                    self.assertEqual(list(map(int,values[key].split('.'))),info['file_version'])
                for key in ('AppVersion','VersionInfoTextVersion','VersionInfoProductTextVersion'):
                    self.assertEqual(values[key],info['version'])

    def test_installer_recipe_preserves_data_and_requires_webview_without_downloading_it(self):
        source=(ROOT/'deploy/windows/desktop-installer.iss').read_text()
        self.assertIn('PrivilegesRequired=lowest',source)
        self.assertIn('AppMutex=Local\\SAPLensDesktop',source)
        self.assertNotIn('\n[UninstallDelete]',source)
        self.assertIn('--maintenance backup',source)
        self.assertIn('--maintenance version-check',source)
        self.assertIn('86.0.622.0',source)
        self.assertNotIn('DownloadTemporaryFile',source)


class DesktopDistributionTests(unittest.TestCase):
    def test_outer_bundle_still_requires_canonical_portable_and_installer_verifiers(self):
        import hashlib,json,tempfile
        distribution_spec=importlib.util.spec_from_file_location('desktop_distribution',ROOT/'scripts/verify-desktop-distribution.py')
        distribution=importlib.util.module_from_spec(distribution_spec);distribution_spec.loader.exec_module(distribution)
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);installer=f'SAP-Lens-Windows-Desktop-x64-{BUILD_INFO["version"]}-Setup.exe'
            digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
            for name in ['SAP-Lens.exe',installer,'LICENSE.md','LICENSE-Inno-Setup.txt','README.md']:(directory/name).write_bytes(b'synthetic')
            for name in ['SAP-Lens.exe',installer]:(directory/(name+'.sha256')).write_text(digest(directory/name)+'  '+name+'\n')
            report=dict(identity=BUILD_INFO,signing='disabled',native_installer_smoke='passed: synthetic helper fixture',installer_sha256=digest(directory/installer),payload_sha256=digest(directory/'SAP-Lens.exe'))
            (directory/'installer-verification.json').write_text(json.dumps(report))
            files={p.name:digest(p) for p in directory.iterdir()}
            (directory/'package-manifest.json').write_text(json.dumps(dict(schema=1,platform='Windows-Desktop-x64',identity=BUILD_INFO,files=files)))
            original=distribution.load
            from unittest.mock import Mock
            native=Mock()
            def load(name):return SimpleNamespace(verify=native) if name=='verify-desktop-installer' else original(name)
            with patch.object(distribution,'load',side_effect=load),patch.object(distribution.subprocess,'run') as portable:
                distribution.verify(directory)
                native.assert_called_once_with(directory/installer)
                self.assertIn(str(ROOT/'scripts/verify-windows-package.py'),portable.call_args.args[0])
            (directory/'unexpected.csv').write_text('synthetic')
            with self.assertRaises(ValueError):distribution.verify(directory)
            (directory/'unexpected.csv').unlink()
            (directory/installer).write_bytes(b'tampered')
            with self.assertRaises(ValueError):distribution.verify(directory)
