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
spec=importlib.util.spec_from_file_location('installer_resources',ROOT/'scripts/packaging/verify-desktop-installer.py')
rules=importlib.util.module_from_spec(spec);spec.loader.exec_module(rules)


def installer_resource_fixture(info, product_name='SAP Lens', description='SAP Lens Setup'):
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
             for key,value in [('ProductName',product_name),('ProductVersion',info['version']),('FileDescription',description)]]
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
                    result=subprocess.run([sys.executable,str(ROOT/'scripts/packaging/verify-desktop-installer.py'),
                        '--installer',str(path),'--compiler-fixture-channel',channel],capture_output=True,text=True)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertIn('no application payload',result.stdout)
                path.write_bytes(installer_resource_fixture(info,product_name='Other product'))
                with self.assertRaises(rules.InstallerValidationError):rules.verify(path,info)


@unittest.skipUnless(importlib.util.find_spec('pefile'), 'Install build requirements for real PE resource tests')
class PayloadBoundIdentityTests(unittest.TestCase):
    """An installer is verified against the identity bound to its payload EXE, not the checkout's current identity (a stale or newer checkout must
    neither reject a genuine installer nor accept a mismatched one)."""
    SHA = 'c' * 64

    def record(self, directory, info, sha=None, **changes):
        value = {'schema': 1, 'artifact': 'SAP-Lens.exe', 'exe_sha256': sha or self.SHA,
                 'identity': {key: info[key] for key in ('version', 'file_version', 'source_sha')}, **changes}
        (Path(directory) / f'{sha or self.SHA}.json').write_text(__import__('json').dumps(value), encoding='utf-8')

    def info(self, text='1.0.0-beta.2', sha='d' * 40):
        from version import make_local_deployment_info
        return make_local_deployment_info(text, sha)

    def test_an_installer_from_an_older_commit_verifies_against_its_bound_identity_for_every_channel(self):
        from version import release_file_version
        with tempfile.TemporaryDirectory() as directory:
            for text in ('1.0.0', '1.0.0-alpha.1', '1.0.0-beta.2', '1.0.0-rc.3'):
                info = self.info(text)
                self.assertEqual(info['file_version'], release_file_version(text))
                self.record(directory, info)
                bound = rules.bound_identity(self.SHA, directory)
                installer = Path(directory) / 'setup.exe'
                installer.write_bytes(installer_resource_fixture(info))
                with self.subTest(version=text):
                    rules.verify(installer, bound)
                    other = dict(info, file_version=[*info['file_version'][:3], info['file_version'][3] + 1])
                    installer.write_bytes(installer_resource_fixture(other))
                    with self.assertRaisesRegex(rules.InstallerValidationError, 'numeric file version differs'):
                        rules.verify(installer, bound)

    def test_the_reported_mismatch_is_a_fallback_identity_not_the_installer(self):
        # [1,0,0,2] installer vs the former development fallback [1,0,0,0]: the strict comparison still rejects it, and the fallback now follows the contract.
        import version
        info = self.info('1.0.0-beta.2')
        with tempfile.TemporaryDirectory() as directory:
            installer = Path(directory) / 'setup.exe'
            installer.write_bytes(installer_resource_fixture(info))
            old_fallback = dict(version.local_build_info(), file_version=[1, 0, 0, 0], version='1.0.0-beta.2')
            with self.assertRaisesRegex(rules.InstallerValidationError, 'numeric file version differs'):
                rules.verify(installer, old_fallback)
            with patch.object(version, 'product_version', return_value='1.0.0-beta.2'):
                rules.verify(installer, version.local_build_info())

    def test_missing_foreign_tampered_and_contract_violating_records_are_refused(self):
        info = self.info()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(rules.InstallerValidationError, 'No build identity is bound'):
                rules.bound_identity(self.SHA, directory)
            for label, build in (('another payload', lambda: self.record(directory, info, exe_sha256='e' * 64)),
                                 ('schema', lambda: self.record(directory, info, schema=2)),
                                 ('numeric contract', lambda: self.record(directory, dict(info, file_version=[1, 0, 0, 0]))),
                                 ('numeric base', lambda: self.record(directory, dict(info, file_version=[1, 0, 1, 2]))),
                                 ('numeric type', lambda: self.record(directory, dict(info, file_version=[1, 0, 0, True]))),
                                 ('source', lambda: self.record(directory, dict(info, source_sha='short'))),
                                 ('extra field', lambda: self.record(directory, info, identity={**{k: info[k] for k in ('version', 'file_version', 'source_sha')}, 'extra': 1}))):
                build()
                with self.subTest(case=label), self.assertRaisesRegex(rules.InstallerValidationError, 'malformed|violates'):
                    rules.bound_identity(self.SHA, directory)
            (Path(directory) / f'{self.SHA}.json').write_text('{not json')
            with self.assertRaises(rules.InstallerValidationError):
                rules.bound_identity(self.SHA, directory)
            for bad in ('xyz', 'C' * 64, '../x', None):
                with self.subTest(sha=bad), self.assertRaisesRegex(rules.InstallerValidationError, 'not a SHA-256'):
                    rules.bound_identity(bad, directory)

    def test_the_cli_uses_the_bound_identity_and_fails_closed_without_one(self):
        info = self.info()
        script = str(ROOT / 'scripts/packaging/verify-desktop-installer.py')
        with tempfile.TemporaryDirectory() as directory:
            installer = Path(directory) / 'setup.exe'
            installer.write_bytes(installer_resource_fixture(info))
            missing = subprocess.run([sys.executable, script, '--installer', str(installer), '--payload-sha256', 'f' * 64], capture_output=True, text=True)
            self.assertEqual(missing.returncode, 1)
            self.assertIn('No build identity is bound', missing.stderr)
            both = subprocess.run([sys.executable, script, '--installer', str(installer), '--payload-sha256', 'f' * 64, '--compiler-fixture-channel', 'beta'], capture_output=True, text=True)
            self.assertEqual(both.returncode, 1)

    def test_the_acceptance_harness_verifies_with_the_payload_binding(self):
        harness = (ROOT / 'scripts/test-desktop-installer.ps1').read_text(encoding='utf-8')
        self.assertEqual(harness.count('--payload-sha256 $payloadSha'), 2)
        self.assertIn("package-verification.json')", harness)
        self.assertLess(harness.index('$payloadSha='), harness.index('--installer $Installer --payload-sha256'))


class InstallerResourceTests(unittest.TestCase):
    def image(self,version=None,signed=False,numeric=None,subsystem=2,product_numeric=None,padded=False,description='SAP Lens Setup'):
        values=numeric or BUILD_INFO['file_version']
        product=product_numeric or BUILD_INFO['file_version']
        strings={b'ProductName':b'SAP Lens',b'ProductVersion':(version or BUILD_INFO['version']).encode(),b'FileDescription':description.encode()}
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

    def test_production_and_acceptance_resource_identities_are_not_interchangeable(self):
        identity='36C8FD0F-14CE-49D9-BA04-52E94C118C31'
        image=self.image(description='SAP Lens Acceptance '+identity)
        parser=SimpleNamespace(PE=lambda _:image,DIRECTORY_ENTRY={'IMAGE_DIRECTORY_ENTRY_SECURITY':0})
        with patch.dict(sys.modules,{'pefile':parser}):
            with self.assertRaisesRegex(ValueError,'identity resource'):rules.verify(Path('test-only.exe'))
            rules.verify(Path('test-only.exe'),acceptance_id=identity)
            with self.assertRaisesRegex(ValueError,'differ from production'):
                rules.verify(Path('test-only.exe'),acceptance_id='5DB5BC51-A860-44CA-93CA-09AE85812DF0')
        production=self.image()
        parser.PE=lambda _:production
        with patch.dict(sys.modules,{'pefile':parser}), self.assertRaisesRegex(ValueError,'identity resource'):
            rules.verify(Path('production.exe'),acceptance_id=identity)

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
    def test_installer_only_bundle_still_requires_internal_portable_and_installer_verifiers(self):
        import hashlib,json,tempfile
        distribution_spec=importlib.util.spec_from_file_location('desktop_distribution',ROOT/'scripts/packaging/verify-desktop-distribution.py')
        distribution=importlib.util.module_from_spec(distribution_spec);distribution_spec.loader.exec_module(distribution)
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'bundle';directory.mkdir();payload=Path(temporary)/'internal';payload.mkdir();(directory/'metadata').mkdir();installer=f'SAP-Lens-Windows-Desktop-x64-{BUILD_INFO["version"]}-Setup.exe'
            digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
            for name in [installer,'LICENSE.md','LICENSE-Inno-Setup.txt','README.md']:(directory/name).write_bytes(b'synthetic')
            (payload/'SAP-Lens.exe').write_bytes(b'synthetic verified payload')
            (payload/'SAP-Lens.exe.sha256').write_text(digest(payload/'SAP-Lens.exe')+'  SAP-Lens.exe\n')
            report=dict(identity=BUILD_INFO,signing='disabled',native_installer_smoke='passed: synthetic helper fixture',installer_sha256=digest(directory/installer),payload_sha256=digest(payload/'SAP-Lens.exe'))
            (directory/'metadata/installer-verification.json').write_text(json.dumps(report))
            files={p.relative_to(directory).as_posix():digest(p) for p in directory.rglob('*') if p.is_file()}
            (directory/'metadata/package-manifest.json').write_text(json.dumps(dict(schema=1,layout='installer-only-v1',platform='Windows-Desktop-x64',identity=BUILD_INFO,files=files)))
            original=distribution.load
            from unittest.mock import Mock
            native=Mock()
            def load(name):return SimpleNamespace(verify=native) if name=='verify-desktop-installer' else original(name)
            with patch.object(distribution,'load',side_effect=load),patch.object(distribution.subprocess,'run') as portable:
                distribution.verify(directory,payload)
                native.assert_called_once_with(directory/installer)
                self.assertIn(str(ROOT/'scripts/packaging/verify-windows-package.py'),portable.call_args.args[0])
            def receipt(value):
                (directory/'metadata/installer-verification.json').write_text(json.dumps(value))
                files={p.relative_to(directory).as_posix():digest(p) for p in directory.rglob('*') if p.is_file() and p.name!='package-manifest.json'}
                (directory/'metadata/package-manifest.json').write_text(json.dumps(dict(schema=1,layout='installer-only-v1',platform='Windows-Desktop-x64',identity=BUILD_INFO,files=files)))
            isolated={**report,'acceptance_mode':'isolated-app-id','test_app_id':'36C8FD0F-14CE-49D9-BA04-52E94C118C31',
                'production_app_id':'5DB5BC51-A860-44CA-93CA-09AE85812DF0','production_unchanged':True,'cleanup_complete':True,
                'executed_installer_sha256':'b'*64,'recipe_sha256':'c'*64}
            receipt(isolated)
            with patch.object(distribution,'load',side_effect=load),patch.object(distribution.subprocess,'run'):
                distribution.verify(directory,payload)
            for field,value in [('test_app_id',isolated['production_app_id']),('production_unchanged',False),('cleanup_complete',False),('executed_installer_sha256',report['installer_sha256']),('acceptance_mode','unknown')]:
                receipt({**isolated,field:value})
                with self.subTest(field=field),self.assertRaises(ValueError):distribution.verify(directory,payload)
            receipt(report)
            self.assertEqual({p.name for p in directory.iterdir()},{installer,'LICENSE.md','LICENSE-Inno-Setup.txt','README.md','metadata'})
            self.assertFalse((directory/'SAP-Lens.exe').exists())
            (directory/'unexpected.csv').write_text('synthetic')
            with self.assertRaises(ValueError):distribution.verify(directory,payload)
            (directory/'unexpected.csv').unlink()
            (directory/installer).write_bytes(b'tampered')
            with self.assertRaises(ValueError):distribution.verify(directory,payload)


class IsolatedInstallerPlans(unittest.TestCase):
    def setUp(self):
        import copy, json, os, shutil
        sys.path.insert(0, str(ROOT/'scripts'))
        from build_system import installer_acceptance
        self.helper=installer_acceptance
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.repo=self.base/'repository'
        (self.repo/'deploy/windows').mkdir(parents=True)
        shutil.copyfile(ROOT/'deploy/windows/desktop-installer.iss', self.repo/'deploy/windows/desktop-installer.iss')
        (self.repo/'backend/dist').mkdir(parents=True); (self.repo/'backend/build').mkdir()
        self.payload=self.repo/'backend/dist/SAP-Lens.exe'; self.payload.write_bytes(b'synthetic approved payload')
        (self.repo/'backend/build/package-verification.json').write_text(json.dumps({'status':'passed','exe_sha256':self.helper.digest(self.payload)}))
        (self.repo/'backend/build/build-version.json').write_text(json.dumps({'version':'0.1.0'}))
        self.installer=self.base/'production-setup.exe'; self.installer.write_bytes(b'synthetic production setup, never executed')
        self.proof=self.helper.record_production(self.installer,self.repo)
        self.local=self.base/'profile/Local'; self.prod=self.local/'Programs/SAP Lens'; self.prod.mkdir(parents=True)
        (self.prod/'SAP-Lens.exe').write_bytes(b'existing production installation')
        (self.local/'SAP Lens').mkdir(); (self.local/'SAP Lens/settings.json').write_text('{"schema_version":3}')
        self.parent=self.base/'acceptance ø'; self.parent.mkdir()
        self.environment=patch.dict(os.environ,{'LOCALAPPDATA':str(self.local),'APPDATA':str(self.base/'Roaming'),'USERPROFILE':str(self.base/'profile'),
            'SAP_LENS_CONFIG_DIR':'','SAP_LENS_BACKUP_DIR':'','SAP_LENS_DATA_DIR':''})
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.production=self.helper.production_id(self.repo)
        self.registry={self.production:{'HKCU64':{'values':{'InstallLocation':{'type':1,'value':str(self.prod)}},'written':1,'children':{}}}}
        self.native_registry_reader=self.helper.registry
        self.reader=patch.object(self.helper,'registry',side_effect=lambda identity:copy.deepcopy(self.registry.get(identity,{'HKCU64':None})))
        self.reader.start(); self.addCleanup(self.reader.stop)

    def prepare(self):
        return self.helper.prepare(self.installer, self.base/'receipt.json', self.parent, self.repo)

    def registered(self, plan):
        self.registry[plan['test_id']]={'HKCU64':{'values':{
            'InstallLocation':{'value':plan['application']},
            'UninstallString':{'value':'"'+str(Path(plan['application'])/'unins000.exe')+'"'}},'written':2,'children':{}}}

    def test_missing_or_stale_production_payload_binding_is_refused(self):
        import json
        content=self.proof.read_text(); self.proof.unlink()
        with self.assertRaisesRegex(ValueError,'provenance'):self.prepare()
        self.proof.write_text(content)
        changed=json.loads(content); changed['payload_sha256']='0'*64
        self.proof.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError,'provenance'):self.prepare()
        self.assertEqual(list(self.parent.iterdir()),[])

    def test_registered_production_is_allowed_but_new_identity_and_directory_are_isolated(self):
        path, plan=self.prepare()
        self.assertNotEqual(plan['test_id'],self.production)
        self.assertEqual(self.helper.load(path,self.repo)['test_id'],plan['test_id'])
        self.assertEqual(Path(plan['application']),Path(plan['root'])/'application')
        self.assertFalse(Path(plan['root']).is_relative_to(self.prod))
        self.helper.verify_production(plan)
        self.assertEqual((self.prod/'SAP-Lens.exe').read_bytes(),b'existing production installation')

    def test_install_reinstall_uninstall_registration_and_data_preservation(self):
        _,plan=self.prepare(); application=Path(plan['application']); application.mkdir()
        installed=application/'SAP-Lens.exe'; installed.write_bytes(self.payload.read_bytes())
        data=Path(plan['data']); data.mkdir(); settings=data/'settings.json'; settings.write_text('synthetic private state')
        for iteration in range(2):
            self.registered(plan)
            self.helper.registration(plan,True)
            self.assertEqual(self.helper.digest(installed),plan['payload_sha256'])
            self.helper.verify_production(plan)
        with self.assertRaises(ValueError):self.helper.registration(plan,False)
        del self.registry[plan['test_id']]
        self.helper.registration(plan,False)
        self.assertEqual(settings.read_text(),'synthetic private state')
        self.helper.cleanup(plan)
        self.assertFalse(Path(plan['root']).exists())
        self.assertTrue(self.prod.exists())

    def test_production_registry_file_or_data_changes_are_reported(self):
        _,plan=self.prepare()
        self.registry[self.production]['HKCU64']['written']=2
        with self.assertRaisesRegex(ValueError,'registry HKCU64'):self.helper.verify_production(plan)
        self.registry[self.production]['HKCU64']['written']=1
        (self.prod/'SAP-Lens.exe').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'SAP-Lens.exe'):self.helper.verify_production(plan)
        (self.local/'SAP Lens/settings.json').write_text('changed')
        with self.assertRaisesRegex(ValueError,'settings.json'):self.helper.verify_production(plan)

    def test_production_identity_overlap_and_unowned_registration_are_refused(self):
        import uuid
        with patch.object(self.helper.uuid,'uuid4',return_value=uuid.UUID(self.production)):
            with self.assertRaisesRegex(ValueError,'differ from production'):self.prepare()
        with self.assertRaisesRegex(ValueError,'overlaps'):
            self.helper.prepare(self.installer,self.base/'receipt.json',self.prod,self.repo)
        _,plan=self.prepare(); self.registered(plan)
        self.registry[plan['test_id']]['HKCU64']['values']['InstallLocation']['value']=str(self.prod)
        with self.assertRaisesRegex(ValueError,'does not belong'):self.helper.registration(plan,True)
        self.assertTrue((self.prod/'SAP-Lens.exe').exists())
        self.registry[plan['test_id']]['HKCU64']['values']['InstallLocation']['value']=plan['application']
        self.registry[plan['test_id']]['HKCU64']['values']['UninstallString']['value']='"'+str(self.prod/'unins000.exe')+'"'
        with self.assertRaisesRegex(ValueError,'uninstall command differs'):self.helper.registration(plan,True)

    def test_changed_payload_or_plan_identity_is_rejected(self):
        import json
        path,plan=self.prepare()
        value=json.loads(path.read_text()); value['test_id']=self.production; path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):self.helper.load(path,self.repo)
        path.write_text(json.dumps(plan)); self.payload.write_bytes(b'changed payload')
        with self.assertRaisesRegex(ValueError,'payload'):self.helper.load(path,self.repo)

    def test_cleanup_failure_retains_marker_snapshot_and_diagnostics(self):
        _,plan=self.prepare(); root=Path(plan['root']); data=root/'data'; data.mkdir()
        locked=data/'locked.bin'; locked.write_bytes(b'synthetic')
        (root/'setup.log').write_text('synthetic setup diagnostics')
        original=Path.unlink
        def remove(path,*args,**kwargs):
            if path==locked:raise PermissionError('synthetic lock')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',remove):
            with self.assertRaisesRegex(ValueError,'cleanup failed'):self.helper.cleanup(plan)
        for name in ('.owner','plan.json','setup.log'):
            self.assertTrue((root/name).exists())
        self.helper.verify_production(plan)
        self.helper.cleanup(plan)

    @unittest.skipUnless(sys.platform == 'win32', 'Native Windows registry views required')
    def test_native_test_registration_is_separate_from_production(self):
        import copy, winreg
        _,plan=self.prepare()
        key=self.helper.KEY % plan['test_id']
        self.assertNotEqual(plan['test_id'],self.production)
        self.assertFalse(any(row is not None for row in self.native_registry_reader(plan['test_id']).values()))
        created=False
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,key,0,winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as handle:
                created=True
                winreg.SetValueEx(handle,'InstallLocation',0,winreg.REG_SZ,plan['application'])
                winreg.SetValueEx(handle,'UninstallString',0,winreg.REG_SZ,'"'+str(Path(plan['application'])/'unins000.exe')+'"')
            def reader(identity):
                return copy.deepcopy(self.registry[identity]) if identity==self.production else self.native_registry_reader(identity)
            with patch.object(self.helper,'registry',side_effect=reader):
                self.helper.registration(plan,True)
                self.helper.verify_production(plan)
        finally:
            if created: winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER,key,winreg.KEY_WOW64_64KEY)
        self.assertFalse(any(row is not None for row in self.native_registry_reader(plan['test_id']).values()))

    @unittest.skipUnless(sys.platform == 'win32', 'Native Windows sharing locks required')
    def test_native_locked_file_preserves_recovery_state(self):
        _,plan=self.prepare(); root=Path(plan['root']); data=root/'data'; data.mkdir()
        locked=data/'locked.bin'; locked.write_bytes(b'synthetic')
        with locked.open('rb'):
            with self.assertRaisesRegex(ValueError,'cleanup failed'):self.helper.cleanup(plan)
        self.assertTrue((root/'plan.json').exists()); self.assertTrue((root/'.owner').exists())
        self.helper.cleanup(plan)

    def test_recipe_and_runner_keep_production_boundaries_and_never_execute_source_setup(self):
        recipe=(ROOT/'deploy/windows/desktop-installer.iss').read_text()
        script=(ROOT/'scripts/test-desktop-installer.ps1').read_text()
        self.assertEqual(self.production,'5DB5BC51-A860-44CA-93CA-09AE85812DF0')
        for guard in ('AcceptanceId must differ','AcceptanceBoundary','NoAcceptanceLinks','UsePreviousAppDir=no','InitializeUninstall'):
            self.assertIn(guard,recipe)
        self.assertIn('CloseApplications=no',recipe)
        self.assertNotIn('Start-Process -FilePath $Installer',script)
        self.assertIn('Refusing production or changed installer execution',script)
        self.assertIn('verify-production',script)
        self.assertIn('$process.Dispose()',script)
        self.assertLess(script.index("Invoke-Plan 'cleanup'"),script.index("native_installer_smoke='passed:"))
