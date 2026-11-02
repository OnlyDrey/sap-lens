"""Cross-platform, synthetic positive/negative package verification contracts."""
import hashlib
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT / 'backend'))
spec = importlib.util.spec_from_file_location('verify_windows_package', ROOT / 'scripts/verify-windows-package.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def synthetic_pe():
    data = bytearray(1024)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 64)
    data[64:68] = b'PE\0\0'
    struct.pack_into('<HH', data, 68, 0x8664, 1)
    struct.pack_into('<H', data, 84, 240)
    struct.pack_into('<H', data, 88, 0x20b)
    struct.pack_into('<H', data, 156, 2)
    return data


class WindowsPackageTests(unittest.TestCase):
    def test_archive_requires_complete_canonical_assets(self):
        assets = [name.replace('/', '\\') for name in package.REQUIRED]
        package.validate_archive_names(assets + ['webview/lib/WebView2Loader.dll', 'certifi/cacert.pem', 'example/config.json'])
        with self.assertRaises(ValueError):
            package.validate_archive_names(['frontend/dist/index.html'])

    def test_private_and_development_inputs_rejected_without_disclosing_names(self):
        assets = list(package.REQUIRED)
        for private in ['employee-directory/snapshot.json', 'account-review.json', 'settings.json', 'data/private.csv', 'branding/private.sap-lens.json', 'sap-lens.log',
                        'credentials.yaml', '.npmrc', 'secrets.yml', 'sap-lens.log.1', '.env', '.env.production.local', 'runtime.json', 'credentials.json',
                        'key.pem', 'signing.pfx', 'key.key', 'frontend/dist/assets/source.js.map', 'debug.pdb',
                        'node_modules/pkg/index.js', 'tests/fixture.json', 'fixtures/data.json', '__pycache__/x.pyc',
                        '.git/config', '.aws/credentials', 'app-data/profile.json', 'frontend/vite.config.ts',
                        'backend/source.py', 'unexpected.exe']:
            with self.subTest(private=private), self.assertRaises(ValueError) as error:
                package.validate_archive_names(assets + [private])
            self.assertNotIn(private, str(error.exception))

    def test_duplicate_and_unsafe_archive_names(self):
        assets = list(package.REQUIRED)
        for bad in ['frontend\\dist\\INDEX.HTML', '/absolute', '../escape', 'a/../escape', 'C:/data', 'a//b', 'bad\x00name']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                package.validate_archive_names(assets + [bad])

    def test_checksum_rejects_tampering_wrong_filename_and_extra_lines(self):
        payload = b'synthetic executable content'
        digest = hashlib.sha256(payload).hexdigest()
        self.assertEqual(package.validate_checksum(payload, digest+'  SAP-Lens.exe\n'), digest)
        for data, manifest in [(payload+b'changed', digest+'  SAP-Lens.exe'), (payload, digest+'  other.exe'),
                               (payload, digest+'  SAP-Lens.exe\nextra'), (payload, digest+' SAP-Lens.exe')]:
            with self.assertRaises(ValueError):
                package.validate_checksum(data, manifest)

    def test_pe_guard_checks_architecture_magic_truncation_and_console(self):
        package.validate_gui(synthetic_pe())
        for offset, value in [(68, 0x14c), (70, 0), (84, 10), (88, 0x10b), (156, 3)]:
            data = synthetic_pe()
            struct.pack_into('<H', data, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                package.validate_gui(data)
        for data in [b'', b'not an executable', synthetic_pe()[:160]]:
            with self.assertRaises(ValueError):
                package.validate_gui(data)
        data = synthetic_pe(); struct.pack_into('<I', data, 0x3c, 0xfffffff0)
        with self.assertRaises(ValueError): package.validate_gui(data)

    def test_metadata_uses_authoritative_version_and_existing_identity(self):
        metadata = package.metadata_module()
        version = metadata.FILE_VERSION
        resources = {16: 1, 14: 1, 24: 1, 3: 2}
        package.validate_metadata(metadata.expected_metadata(), (version, version), resources)
        for key in metadata.expected_metadata():
            values = metadata.expected_metadata(); values[key] = 'changed'
            with self.subTest(key=key), self.assertRaises(ValueError):
                package.validate_metadata(values, (version, version), resources)
        with self.assertRaises(ValueError): package.validate_metadata(metadata.expected_metadata(), (((version[0]+1)%65536,*version[1:]), version), resources)
        for key in [16, 14, 24]:
            for count in [0, 2]:
                with self.assertRaises(ValueError):
                    package.validate_metadata(metadata.expected_metadata(), (version, version), {**resources, key: count})

    def test_pe_icon_matches_canonical_resource_bytes(self):
        canonical = (ROOT / 'assets/sap-lens.ico').read_bytes()
        count = struct.unpack_from('<H', canonical, 4)[0]
        group, icons = bytearray(canonical[:6]), {}
        for i in range(count):
            entry = struct.unpack_from('<BBBBHHII', canonical, 6 + 16*i)
            group.extend(struct.pack('<BBBBHHIH', *entry[:7], i+1))
            icons[i+1] = canonical[entry[7]:entry[7]+entry[6]]
        package.validate_icon(group, icons, canonical)
        with self.assertRaises(ValueError): package.validate_icon(group, {**icons, 9999:b'unexpected'}, canonical)
        icons[1] += b'tampered'
        with self.assertRaises(ValueError): package.validate_icon(group, icons, canonical)
        with self.assertRaises(ValueError): package.validate_icon(b'', {}, canonical)

    def test_manifest_requires_user_execution_without_elevation(self):
        template = '<assembly xmlns="urn:schemas-microsoft-com:asm.v1"><trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges><requestedExecutionLevel level="{}" uiAccess="false"/></requestedPrivileges></security></trustInfo></assembly>'
        package.validate_manifest(template.format('asInvoker').encode())
        for level in ['requireAdministrator', 'highestAvailable']:
            with self.assertRaises(ValueError): package.validate_manifest(template.format(level).encode())
        with self.assertRaises(ValueError): package.validate_manifest(b'<assembly/>')

    def test_raw_archive_toc_detects_duplicate_entries_before_dictionary_conversion(self):
        def entry(name):
            raw = name.encode() + b'\0'
            return struct.pack('!IIIIBc', 18+len(raw), 0, 1, 1, 0, b'x') + raw
        package.validate_toc(entry('frontend/dist/index.html'))
        for data in [entry('a') + entry('A'), b'bad', struct.pack('!IIIIBc', 0, 0, 0, 0, 0, b'x')]:
            with self.assertRaises(ValueError): package.validate_toc(data)

    def test_secret_signatures_do_not_echo_values_and_allow_public_certificates(self):
        package.secret_check(b'-----BEGIN CERTIFICATE-----\n' + b'A'*100)
        for value in [b'-----BEGIN PRIVATE KEY-----\n'+b'A'*100, b'ghp_'+b'a'*36, b'AKIA'+b'A'*16]:
            with self.assertRaises(ValueError) as error: package.secret_check(value)
            self.assertNotIn(value.decode(), str(error.exception))

    def test_distribution_round_trip_requires_exact_files_and_original_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            data = bytes(synthetic_pe()); digest = hashlib.sha256(data).hexdigest()
            (directory/'SAP-Lens.exe').write_bytes(data)
            (directory/'SAP-Lens.exe.sha256').write_text(digest+'  SAP-Lens.exe\n')
            self.assertEqual(package.validate_distribution(directory, digest), (data, digest))
            with self.assertRaises(ValueError): package.validate_distribution(directory, '0'*64)
            (directory/'extra.zip').write_bytes(b'zip')
            with self.assertRaises(ValueError): package.validate_distribution(directory)
            (directory/'extra.zip').unlink(); (directory/'SAP-Lens.exe').write_bytes(b'')
            with self.assertRaises(ValueError): package.validate_distribution(directory)

    @unittest.skipUnless(importlib.util.find_spec('PyInstaller'), 'PyInstaller is a build-only dependency')
    def test_real_pyinstaller_archive_reader_detects_frontend_tampering_and_corruption(self):
        from PyInstaller.archive.writers import CArchiveWriter, ZlibArchiveWriter
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); frontend = root/'frontend'; frontend.mkdir()
            for name in ['index.html', 'sap-lens.png', 'favicon.png', 'theme.js', 'assets/app.js']:
                path = frontend/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'synthetic asset')
            source = root/'entry.py'; source.write_text('pass\n')
            pyz = root/'PYZ.pyz'
            ZlibArchiveWriter(str(pyz), [('main', str(source), 'PYMODULE'), ('webview', str(source), 'PYMODULE'), ('version', str(source), 'PYMODULE')], {name: compile('pass', name+'.py', 'exec') for name in ['main','webview','version']})
            entries = [('frontend/dist/'+str(p.relative_to(frontend)), str(p), True, 'x') for p in frontend.rglob('*') if p.is_file()]
            entries += [('assets/sap-lens.ico', str(ROOT/'assets/sap-lens.ico'), True, 'x'), ('desktop', str(source), True, 's'), ('PYZ.pyz', str(pyz), False, 'z'),
                        ('python312.dll', str(source), True, 'b'), ('webview/WebView2Loader.dll', str(source), True, 'b')]
            import json
            from types import SimpleNamespace
            from version import make_build_info
            info = make_build_info('beta','0.1.0','a'*40,'1','1',1,1)
            identity = root/'build-version.json'; identity.write_text(json.dumps(info))
            entries += [('build-version.json',str(identity),True,'x')]
            guard = patch.object(package,'metadata_module',return_value=SimpleNamespace(BUILD_INFO=info))
            guard.start(); self.addCleanup(guard.stop)
            executable = root/'synthetic.pkg'
            CArchiveWriter(str(executable), entries, 'python312.dll')
            inventory = package.inspect_archive(executable, frontend)
            self.assertEqual(inventory['frontend_files'], 5)
            self.assertEqual(set(inventory['module_names']), {'main', 'webview', 'version'})
            changed = dict(info, version='0.1.0-beta-2', tag='v0.1.0-beta-2', file_version=[0,1,0,2])
            identity.write_text(json.dumps(changed))
            CArchiveWriter(str(executable), entries, 'python312.dll')
            with self.assertRaises(ValueError): package.inspect_archive(executable, frontend)
            identity.write_text(json.dumps(info))
            CArchiveWriter(str(executable), entries, 'python312.dll')
            (frontend/'assets/app.js').write_bytes(b'tampered')
            with self.assertRaises(ValueError): package.inspect_archive(executable, frontend)
            (frontend/'assets/app.js').write_bytes(b'synthetic asset')
            (frontend/'assets/extra.js').write_bytes(b'new asset')
            with self.assertRaises(ValueError): package.inspect_archive(executable, frontend)
            (frontend/'assets/extra.js').unlink()
            executable.write_bytes(b'not a PyInstaller archive')
            with self.assertRaises(Exception): package.inspect_archive(executable, frontend)

    def test_resource_parser_adapter_validates_full_version_icon_and_manifest(self):
        from contextlib import nullcontext
        from types import SimpleNamespace as NS
        import sys
        canonical = (ROOT/'assets/sap-lens.ico').read_bytes()
        count = struct.unpack_from('<H', canonical, 4)[0]
        group = bytearray(canonical[:6]); resources = []
        for i in range(count):
            entry = struct.unpack_from('<BBBBHHII', canonical, 6+16*i)
            group.extend(struct.pack('<BBBBHHIH', *entry[:7], i+1))
            resources.append((3, i+1, canonical[entry[7]:entry[7]+entry[6]]))
        manifest = b'<assembly xmlns="urn:schemas-microsoft-com:asm.v1"><trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges><requestedExecutionLevel level="asInvoker" uiAccess="false"/></requestedPrivileges></security></trustInfo></assembly>'
        resources += [(14,1,bytes(group)), (16,1,b'version'), (24,1,manifest)]
        payloads, roots = {}, {}
        for index, (kind, identifier, payload) in enumerate(resources):
            payloads[index] = payload
            leaf = NS(id=1033, data=NS(struct=NS(OffsetToData=index, Size=len(payload))))
            roots.setdefault(kind, []).append(NS(id=identifier, directory=NS(entries=[leaf])))
        metadata = package.metadata_module()
        entries = {key.encode():value.encode() for key,value in metadata.expected_metadata().items()}
        a,b,c,d = metadata.FILE_VERSION
        pe = NS(OPTIONAL_HEADER=NS(DATA_DIRECTORY=[NS(Size=0) for _ in range(16)]), FileInfo=[[NS(StringTable=[NS(entries=entries)])]],
                VS_FIXEDFILEINFO=[NS(FileVersionMS=(a<<16)|b, FileVersionLS=(c<<16)|d, ProductVersionMS=(a<<16)|b, ProductVersionLS=(c<<16)|d)],
                DIRECTORY_ENTRY_RESOURCE=NS(entries=[NS(id=kind, directory=NS(entries=children)) for kind,children in roots.items()]),
                get_data=lambda offset,size: payloads[offset])
        with patch.dict(sys.modules, {'pefile':NS(PE=lambda **kwargs:nullcontext(pe))}):
            self.assertEqual(package.inspect_resources(b'synthetic'), metadata.expected_metadata())
            pe.DIRECTORY_ENTRY_RESOURCE.entries[0].directory.entries.append(pe.DIRECTORY_ENTRY_RESOURCE.entries[0].directory.entries[0])
            with self.assertRaises(ValueError): package.inspect_resources(b'synthetic')
            pe.DIRECTORY_ENTRY_RESOURCE.entries[0].directory.entries.pop()
            entries[b'ProductName'] = b'wrong'
            with self.assertRaises(ValueError): package.inspect_resources(b'synthetic')

    def test_ci_verifier_rejects_build_identity_changed_after_resolution(self):
        import io,json,sys
        from contextlib import redirect_stderr
        from types import SimpleNamespace
        from version import make_build_info
        expected=make_build_info('beta','0.1.0','a'*40,'1','1',1,1)
        changed=make_build_info('beta','0.1.0','a'*40,'1','1',1,2)
        with patch.dict(package.os.environ,{'GITHUB_ACTIONS':'true','SAP_LENS_EXPECTED_BUILD_JSON':json.dumps(expected)}),patch.object(package,'metadata_module',return_value=SimpleNamespace(BUILD_INFO=changed)),patch.object(package,'validate_distribution') as distribution,patch.object(sys,'argv',['verify-windows-package.py']),redirect_stderr(io.StringIO()) as output:
            with self.assertRaises(SystemExit):package.main()
            distribution.assert_not_called()
        self.assertIn('Build metadata changed',output.getvalue())

    def test_missing_or_malformed_expected_identity_is_diagnosable_and_private(self):
        import io,json,sys
        from contextlib import redirect_stderr
        for value,reason in [('', 'missing from CI environment'),('SENSITIVE_SENTINEL','invalid'),(json.dumps({'private':'SENSITIVE_SENTINEL'}),'invalid')]:
            with self.subTest(reason=reason),patch.dict(package.os.environ,{'GITHUB_ACTIONS':'true','SAP_LENS_EXPECTED_BUILD_JSON':value}),patch.object(package,'validate_distribution') as distribution,patch.object(sys,'argv',['verify-windows-package.py']),redirect_stderr(io.StringIO()) as output:
                with self.assertRaises(SystemExit):package.main()
                distribution.assert_not_called()
                self.assertIn(reason,output.getvalue());self.assertIn('phase=build-identity',output.getvalue())
                self.assertNotIn('SENSITIVE_SENTINEL',output.getvalue())

    def test_direct_ci_cli_resolves_beta_identity_without_test_pythonpath(self):
        """Reproduce the Windows CLI process, not the test runner's import context."""
        import json, os, shutil, subprocess
        from version import make_deployment_info
        identity = make_deployment_info('1.0.0', 'beta', '1', 'a'*40, '41340859408', '23', 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'scripts').mkdir()
            (root/'backend/build').mkdir(parents=True)
            for relative in ('scripts/verify-windows-package.py', 'scripts/write-windows-metadata.py', 'backend/version.py'):
                shutil.copyfile(ROOT/relative, root/relative)
            (root/'backend/build/build-version.json').write_text(json.dumps(identity))
            env = dict(os.environ, GITHUB_ACTIONS='true', SAP_LENS_EXPECTED_BUILD_JSON=json.dumps(identity))
            env.pop('PYTHONPATH', None)
            result = subprocess.run([sys.executable, str(root/'scripts/verify-windows-package.py')],
                                    cwd=directory, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            # The intentionally absent distribution is reached only after identity validation.
            self.assertIn('phase=distribution-checksum', result.stderr)
            self.assertIn('PackageValidationError', result.stderr)
            self.assertNotIn('ModuleNotFoundError', result.stderr)
            self.assertNotIn(directory, result.stderr)

    def test_cli_does_not_echo_third_party_parser_error_values(self):
        import io
        import sys
        from contextlib import redirect_stderr
        output = io.StringIO()
        with patch.dict(package.os.environ,{'GITHUB_ACTIONS':'false'}), patch.object(package, 'metadata_module', return_value=type('Metadata',(),{'BUILD_INFO':{'mode':'beta'}})), patch.object(package, 'validate_distribution', return_value=(synthetic_pe(), 'a'*64)), patch.object(package, 'inspect_resources', side_effect=ValueError('SENSITIVE_SENTINEL')), patch.object(sys, 'argv', ['verify-windows-package.py']), redirect_stderr(output):
            with self.assertRaises(SystemExit) as error:
                package.main()
        self.assertEqual(error.exception.code, 1)
        self.assertNotIn('SENSITIVE_SENTINEL', output.getvalue())
        self.assertIn('Windows package inspection failed', output.getvalue())
        self.assertIn('phase=pe-resources', output.getvalue())
        self.assertIn('ValueError; malformed input or parser compatibility', output.getvalue())
