"""Installer resource guards; native compilation/SCM acceptance is not simulated."""
import importlib.util
from pathlib import Path
import sys
import struct
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from version import BUILD_INFO, make_deployment_info
spec=importlib.util.spec_from_file_location('installer_resources',ROOT/'scripts/verify-desktop-installer.py')
rules=importlib.util.module_from_spec(spec);spec.loader.exec_module(rules)


def installer_resource_fixture(info, product_name='SAP Lens'):
    """Non-runnable PE with real resource tables and Inno-style padded strings.

    No vendor binary is shipped or executed. pefile must parse the bytes itself;
    an adapter mock cannot hide padding or fixed-version parsing defects.
    """
    def align(value):return value+b'\0'*((-len(value))%4)
    def node(key,value=b'',children=(),text=True):
        header=align(b'\0'*6+(key+'\0').encode('utf-16le'))
        result=align(header+value)+b''.join(align(child) for child in children)
        return struct.pack('<HHH',len(result),len(value)//2 if text else len(value),int(text))+result[6:]
    strings=[node(key,(value.ljust(50)+'\0').encode('utf-16le'))
             for key,value in [('ProductName',product_name),('ProductVersion',info['version'])]]
    a,b,c,d=info['file_version'];ms=a<<16|b;ls=c<<16|d
    fixed=struct.pack('<13I',0xfeef04bd,0x10000,ms,ls,ms,ls,0x3f,0,4,1,0,0,0)
    resource=node('VS_VERSION_INFO',fixed,[node('StringFileInfo',children=[node('000004b0',children=strings)])],text=False)
    directory=bytearray(88)
    for offset,identifier,target in [(0,16,24),(24,1,48),(48,1033,72)]:
        struct.pack_into('<IIHHHH',directory,offset,0,0,0,0,0,1)
        struct.pack_into('<II',directory,offset+16,identifier,target|(0x80000000 if offset!=48 else 0))
    struct.pack_into('<IIII',directory,72,0x1000+88,len(resource),1200,0)
    contents=bytes(directory)+resource;raw_size=(len(contents)+511)&~511
    data=bytearray(512+raw_size);data[:2]=b'MZ';struct.pack_into('<I',data,0x3c,128)
    data[128:132]=b'PE\0\0';struct.pack_into('<HHIIIHH',data,132,0x8664,1,0,0,0,240,0x22)
    optional=152;struct.pack_into('<H',data,optional,0x20b)
    struct.pack_into('<II',data,optional+32,0x1000,512)
    struct.pack_into('<II',data,optional+56,0x2000,512);struct.pack_into('<H',data,optional+68,2)
    struct.pack_into('<I',data,optional+108,16);struct.pack_into('<II',data,optional+128,0x1000,len(contents))
    section=optional+240;data[section:section+8]=b'.rsrc\0\0\0'
    struct.pack_into('<IIII',data,section+8,len(contents),0x1000,raw_size,512)
    struct.pack_into('<I',data,section+36,0x40000040);data[512:512+len(contents)]=contents
    return bytes(data)


@unittest.skipUnless(importlib.util.find_spec('pefile'), 'Install build requirements for real PE resource tests')
class RealInstallerResourceTests(unittest.TestCase):
    def test_actual_pe_parser_and_cli_verify_every_channel_with_padding(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'synthetic-setup.exe'
            for channel in ('alpha','beta','rc','stable'):
                info=make_deployment_info('0.1.0',channel,'1','a'*40,'1','1',1)
                path.write_bytes(installer_resource_fixture(info))
                with self.subTest(channel=channel):
                    rules.verify(path,info)
                    result=subprocess.run([sys.executable,str(ROOT/'scripts/verify-desktop-installer.py'),
                        '--installer',str(path),'--compiler-fixture-channel',channel],capture_output=True,text=True)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertIn('no application payload',result.stdout)
                path.write_bytes(installer_resource_fixture(info,product_name='Other product'))
                with self.assertRaises(rules.InstallerValidationError):rules.verify(path,info)


class InstallerResourceTests(unittest.TestCase):
    def image(self,version=None,signed=False,numeric=None,subsystem=2,product_numeric=None,padded=False):
        values=numeric or BUILD_INFO['file_version']
        product=product_numeric or BUILD_INFO['file_version']
        strings={b'ProductName':b'SAP Lens',b'ProductVersion':(version or BUILD_INFO['version']).encode()}
        if padded:strings={key:value+b' '*max(0,50-len(value))+b'\x00' for key,value in strings.items()}
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

    def test_fixed_width_inno_padding_is_accepted_but_changed_identity_is_not(self):
        # The pinned Inno 7 resource template is space-padded and is updated
        # in-place (Compiler.ExeUpdateFunc.UpdateStringValue).
        self.verify(self.image(padded=True));self.assertTrue(self.closed)
        for value in ('99.0.0',' '+BUILD_INFO['version'],BUILD_INFO['version']+'\x00extra'):
            with self.subTest(value=value),self.assertRaises(rules.InstallerValidationError):
                self.verify(self.image(version=value,padded=True))
            self.assertTrue(self.closed)

    def test_duplicate_or_missing_version_resources_are_rejected(self):
        for kind in ('duplicate-strings','missing-fixed','duplicate-fixed'):
            image=self.image(padded=True)
            if kind=='duplicate-strings':image.FileInfo.append(image.FileInfo[0])
            elif kind=='missing-fixed':image.VS_FIXEDFILEINFO=[]
            else:image.VS_FIXEDFILEINFO*=2
            with self.subTest(kind=kind),self.assertRaises(rules.InstallerValidationError):self.verify(image)

    def test_cli_explains_controlled_failures_without_dumping_third_party_errors(self):
        for error,expected in ((rules.InstallerValidationError('Installer numeric file version differs.'),'numeric file version'),
                               (ValueError('synthetic-private-path'),'private details omitted')):
            with patch.object(sys,'argv',['verify','--installer','synthetic.exe']),patch.object(rules,'verify',side_effect=error):
                import contextlib,io
                output=io.StringIO()
                with contextlib.redirect_stderr(output),self.assertRaises(SystemExit) as failed:rules.main()
                self.assertEqual(failed.exception.code,1);self.assertIn(expected,output.getvalue())
                self.assertNotIn('synthetic-private-path',output.getvalue())

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

    def test_pascal_section_cannot_use_ini_style_comment_lines(self):
        source=(ROOT/'deploy/windows/desktop-installer.iss').read_text()
        code=source.split('[Code]',1)[1]
        self.assertFalse(any(line.lstrip().startswith(';') for line in code.splitlines()),
                         'INI comments in Pascal code break the native Inno compiler.')


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
