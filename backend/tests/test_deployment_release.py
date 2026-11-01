"""Offline release transactions: no GitHub calls, tags or actual packages are created."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from version import (deployment_version, make_build_info, make_deployment_info,
                     make_local_package_info, parse_build_info)

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load('deployment_release_tests', 'scripts/deployment-release.py')
packages = load('deployment_package_tests', 'scripts/deployment-package.py')
contracts = load('deployment_workflow_tests', 'scripts/check-workflows.py')
SHA = 'a' * 40


def identity(channel='beta'):
    return make_deployment_info('0.1.0', channel, '1', SHA, '123', '12', 1)


ALL = list(release.PACKAGES)


def needs(info, chosen=None):
    """The `needs` context after a run: selected jobs succeeded with verified outputs, unselected jobs were skipped."""
    chosen = ALL if chosen is None else chosen
    result = {'plan': {'result': 'success'}, 'validation': {'result': 'success'}}
    for index, (name, (key, _label, stem, ext, *_rest)) in enumerate(release.PACKAGES.items(), 1):
        if name in chosen:
            result[key] = {'result': 'success', 'outputs': {
                'artifact_id': str(index), 'package_name': f'SAP-Lens-{stem}-{info["version"]}{ext}',
                'package_sha': hashlib.sha256(key.encode()).hexdigest()}}
        else:
            result[key] = {'result': 'skipped', 'outputs': {}}
    return result


class FakeGitHub:
    """In-memory API model; also catches illegal ordering/overwrites."""
    available = release.GitHub.available

    def __init__(self):
        self.calls = []
        self.ref = None
        self.release = None
        self.fail_upload = False
        self.fail_publish = False
        self.lost_publish_reply = False
        self.unknown_after_failure = False
        self.foreign_tag_during_upload = False
        self.corrupt_digest = False
        self.publish_failed = False

    def request(self, method, path, payload=None, asset=None):
        self.calls.append((method, path, payload))
        if path.startswith('/git/ref/tags/'):
            return {'object': {'sha': self.ref}} if self.ref else None
        if method == 'GET' and path.startswith('/releases/'):
            if self.publish_failed and self.unknown_after_failure:
                raise OSError('Private network diagnostic must not escape')
            return copy.deepcopy(self.release)
        if method == 'POST' and path == '/releases':
            self.release = {**payload, 'id': 1, 'assets': [], 'html_url': 'https://github.com/example/test/releases/tag/' + payload['tag_name']}
            return copy.deepcopy(self.release)
        if method == 'POST' and '/assets?name=' in path:
            if self.fail_upload:
                raise release.DeliveryError('Synthetic asset upload failed.')
            if self.foreign_tag_during_upload:
                self.ref = 'c' * 40
            value = dict(id=len(self.release['assets']) + 1, name=asset.name,
                         size=asset.stat().st_size, state='uploaded',
                         digest='sha256:' + ('0' * 64 if self.corrupt_digest else release.sha(asset)))
            self.release['assets'].append(value)
            return value
        if method == 'POST' and path == '/git/tags':
            assert self.release['assets'], 'Never create a tag before uploading verified assets'
            assert payload['object'] == SHA
            return {'sha': 'b' * 40}
        if method == 'POST' and path == '/git/refs':
            if self.ref:
                raise release.DeliveryError('Existing reference may not be overwritten.')
            self.ref = payload['sha']
            return {'object': {'sha': self.ref}}
        if method == 'PATCH' and path == '/releases/1':
            if self.fail_publish:
                self.publish_failed = True
                raise release.DeliveryError('Synthetic publication failure.')
            self.release.update(payload)
            if self.lost_publish_reply:
                raise OSError('Response lost after publication')
            return copy.deepcopy(self.release)
        if method == 'DELETE' and path.startswith('/git/refs/tags/'):
            self.ref = None
            return
        if method == 'DELETE' and path == '/releases/1':
            self.release = None
            return
        raise AssertionError((method, path))


class DeploymentVersionTests(unittest.TestCase):
    def test_all_channels_roundtrip_and_windows_numeric_values(self):
        for channel in ('alpha', 'beta', 'rc', 'stable'):
            with self.subTest(channel=channel):
                value = identity(channel)
                self.assertEqual(value['version'], '0.1.0' if channel == 'stable' else f'0.1.0-{channel}.1')
                self.assertEqual(value['file_version'], [0, 1, 0, 0 if channel == 'stable' else 1])
                self.assertEqual(parse_build_info(value), value)
        boundary = make_deployment_info('65535.0.1', 'rc', '65535', SHA, '1', '1')
        self.assertEqual(parse_build_info(boundary)['file_version'], [65535, 0, 1, 65535])

    def test_malformed_versions_channels_and_sequences_are_rejected(self):
        for base in ('1.2', '01.2.3', '1.2.3-beta.1', '1.2.3+local', '1.2.3\n', '65536.0.0', '0.1.0;bad'):
            with self.subTest(base=base), self.assertRaises(ValueError):
                deployment_version(base, 'beta', '1')
        for number in ('', '0', '01', '-1', '1.2', '65536', '1\n'):
            with self.subTest(number=number), self.assertRaises(ValueError):
                deployment_version('0.1.0', 'beta', number)
        with self.assertRaises(ValueError):
            deployment_version('0.1.0', 'preview', '1')
        self.assertEqual(deployment_version('0.1.0', 'stable', ''), '0.1.0')
        self.assertEqual(deployment_version('0.1.0', 'stable', '4'), '0.1.0')

    def test_tampered_identity_cannot_pass_parsing(self):
        for field, value in [('schema', True), ('version', '0.1.0-rc.1'), ('file_version', [0, 1, 0, True]),
                             ('tag', 'v0.1.0'), ('source_sha', 'bad'), ('attempt', True), ('mode', 'build')]:
            data = identity(); data[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                parse_build_info(data)

    def test_legacy_desktop_and_local_identity_are_unchanged(self):
        legacy = make_build_info('beta', '0.1.0', SHA, '123', '12', 1, 4)
        self.assertEqual(legacy['version'], '0.1.0-beta-4')
        self.assertEqual(legacy['schema'], 1)
        self.assertEqual(parse_build_info(legacy), legacy)
        local = make_local_package_info('0.1.0-beta-4', SHA)
        self.assertEqual(local['version'], '0.1.0-beta-4+local.' + SHA[:12])
        self.assertEqual(parse_build_info(local), local)

    def test_build_only_prepare_resolves_identity_without_any_network_call(self):
        env = dict(GITHUB_ACTIONS='true', GITHUB_RUN_ID='123', GITHUB_RUN_NUMBER='12', GITHUB_RUN_ATTEMPT='1',
                   DEPLOYMENT_TARGET='all', DEPLOYMENT_CHANNEL='Beta', DEPLOYMENT_SEQUENCE='1', PUBLISH_RELEASE='false')
        with patch.dict(os.environ, env, clear=True), patch.object(packages, 'git_sha', return_value=SHA), \
                patch.object(packages, 'write') as write, patch('urllib.request.urlopen') as network:
            packages.prepare('0.1.0')
        self.assertEqual(write.call_args.args[1], identity())
        network.assert_not_called()

    def test_deployment_desktop_uses_sealed_admission_not_legacy_reservation(self):
        canonical = (ROOT / 'scripts/build-windows.ps1').read_text()
        orchestration = (ROOT / 'scripts/package-windows-deployment.ps1').read_text()
        self.assertIn('-Stage Package -ValidatedDeployment', orchestration)
        self.assertIn('if ($ValidatedDeployment)', canonical)
        self.assertIn('scripts/deployment-package.py require-inputs', canonical)
        self.assertIn('scripts/release-windows.py ensure-local-build', canonical)
        self.assertNotIn('ValidatedDeployment', (ROOT / '.github/workflows/build-windows.yml').read_text())

    def test_channels_generate_exact_pe_strings_and_manifest_identity(self):
        metadata = load('deployment_resource_tests', 'scripts/write-windows-metadata.py')
        for channel in ('alpha', 'beta', 'rc', 'stable'):
            info = identity(channel)
            with self.subTest(channel=channel), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with patch.object(metadata, 'ROOT', root), patch.object(metadata, 'BUILD_INFO', info), \
                        patch.object(metadata, 'VERSION', info['version']), patch.object(metadata, 'FILE_VERSION', tuple(info['file_version'])):
                    metadata.main()
                    self.assertEqual(metadata.expected_metadata()['ProductVersion'], info['version'])
                resource = (root / 'backend/build/version-info.txt').read_text()
                self.assertIn(repr(info['version']), resource)
                self.assertIn('filevers=' + repr(tuple(info['file_version'])), resource)
                source = root / 'source'; source.mkdir(); (source / 'README.md').write_text('Synthetic')
                with patch.object(packages, 'identity', return_value=info):
                    archive = packages.finish(source, 'Linux-Native-x64', root / 'output')
                self.assertIn(info['version'], archive.name)
                manifest = packages.verify_extract(archive, root / 'extracted', packages.sha(archive))
                self.assertEqual(manifest['identity'], info)

    def test_publication_context_requires_manual_same_commit_run_and_attempt(self):
        env = dict(GITHUB_ACTIONS='true', GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_SHA=SHA,
                   GITHUB_RUN_ID='123', GITHUB_RUN_NUMBER='12', GITHUB_RUN_ATTEMPT='1',
                   DEPLOYMENT_IDENTITY=json.dumps(identity()))
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(release.context(), identity())
            for key, value in [('GITHUB_EVENT_NAME', 'push'), ('GITHUB_EVENT_NAME', 'pull_request'),
                               ('GITHUB_SHA', 'c' * 40), ('GITHUB_RUN_ID', '124'),
                               ('GITHUB_RUN_NUMBER', '13'), ('GITHUB_RUN_ATTEMPT', '2')]:
                with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}), self.assertRaises(release.DeliveryError):
                    release.context()
        with patch.dict(os.environ, {'PUBLISH_RELEASE': 'false'}, clear=True), patch.object(sys, 'argv', ['tool', 'publish']):
            with self.assertRaises(release.DeliveryError):
                release.main()


class DeploymentCollectionTests(unittest.TestCase):
    def test_all_selected_targets_must_succeed_and_validation_is_required(self):
        info = identity()
        for chosen in [*([name] for name in ALL), ALL, ALL[:2], ALL[2:]]:
            data = needs(info, chosen)
            self.assertEqual(len(release.eligible(info, chosen, data)), len(chosen))
            for name in chosen:
                key = release.PACKAGES[name][0]
                for result in ('failure', 'cancelled', 'skipped'):
                    changed = copy.deepcopy(data); changed[key]['result'] = result
                    with self.subTest(chosen=chosen, key=key, result=result), self.assertRaises(release.DeliveryError):
                        release.eligible(info, chosen, changed)
            for gate in ('validation', 'plan'):
                changed = copy.deepcopy(data); changed[gate]['result'] = 'failure'
                with self.subTest(gate=gate), self.assertRaises(release.DeliveryError):
                    release.eligible(info, chosen, changed)

    def test_unselected_packages_are_skipped_never_collected_and_never_tolerated_if_they_ran(self):
        info = identity()
        for chosen in ([ALL[0]], ALL[:2], ALL[2:]):
            data = needs(info, chosen)
            rows = release.eligible(info, chosen, data)
            self.assertEqual({row['package_name'] for row in rows}, {f'SAP-Lens-{release.PACKAGES[name][2]}-{info["version"]}{release.PACKAGES[name][3]}' for name in chosen})
            for name in set(ALL) - set(chosen):
                key = release.PACKAGES[name][0]
                self.assertEqual(data[key]['result'], 'skipped')  # a skipped job is not a failure of verification or publication
                for result in ('success', 'failure', 'cancelled'):
                    changed = copy.deepcopy(data); changed[key]['result'] = result
                    with self.subTest(chosen=chosen, unselected=name, result=result), self.assertRaises(release.DeliveryError):
                        release.eligible(info, chosen, changed)  # an artifact of an unselected package (or an earlier run) is never published

    def test_invalid_platform_outputs_and_duplicates_are_rejected(self):
        info = identity()
        for field, value in [('artifact_id', ''), ('package_name', '../private.zip'), ('package_sha', 'wrong')]:
            data = needs(info); data['desktop']['outputs'][field] = value
            with self.subTest(field=field), self.assertRaises(release.DeliveryError):
                release.eligible(info, ALL, data)
        data = needs(info); data['service']['outputs']['artifact_id'] = '1'
        with self.assertRaises(release.DeliveryError):
            release.eligible(info, ALL, data)
        for bad in ([], ['windows-desktop', 'unknown']):
            with self.subTest(bad=bad), self.assertRaises(release.DeliveryError):
                release.eligible(info, bad, needs(info))

    def test_exact_asset_collection_checksum_source_manifest_and_tampering(self):
        info = identity(); data = needs(info)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for key in (row[0] for row in release.PACKAGES.values()):
                row = data[key]['outputs']; name = row['package_name']
                (directory / name).write_bytes(key.encode())
                (directory / (name + '.sha256')).write_text(row['package_sha'] + '  ' + name + '\n')
            rows = release.eligible(info, ALL, data)
            assets = release.collect(directory, info, rows)
            self.assertEqual(len(assets), 9)
            manifest = assets[-1]
            self.assertEqual(json.loads(manifest.read_text())['identity'], info)
            manifest.unlink()
            extra = directory / 'settings.json'; extra.write_text('{}')
            with self.assertRaises(release.DeliveryError): release.collect(directory, info, rows)
            extra.unlink()
            package = directory / rows[0]['package_name']; package.write_bytes(b'changed')
            with self.assertRaises(release.DeliveryError): release.collect(directory, info, rows)
            package.write_bytes(b'desktop')
            checksum = package.with_name(package.name + '.sha256'); checksum.write_text(rows[0]['package_sha'] + '  wrong.zip\n')
            with self.assertRaises(release.DeliveryError): release.collect(directory, info, rows)

    def test_workflow_contracts_reject_publication_bypasses(self):
        workflows = contracts.load_workflows(); contracts.validate(workflows)
        def mutate(change):
            data = copy.deepcopy(workflows); change(data['build-deployments.yml'])
            with self.assertRaises(ValueError): contracts.validate(data)
        mutate(lambda w: w['on'].update(push=''))
        mutate(lambda w: w['on']['workflow_dispatch']['inputs']['publish_release'].update(default='true'))
        mutate(lambda w: w['jobs']['publish'].update(**{'if': 'true'}))
        mutate(lambda w: w['jobs']['publish'].update(needs=['validation', 'desktop']))
        mutate(lambda w: w['jobs']['desktop'].update(permissions={'contents': 'write'}))
        mutate(lambda w: w['jobs']['publish']['permissions'].update(actions='write'))
        mutate(lambda w: w['jobs']['publish']['steps'][-1].update(**{'if': 'success()'}))
        mutate(lambda w: w['jobs']['desktop']['steps'][next(i for i,s in enumerate(w['jobs']['desktop']['steps']) if s.get('id')=='integrity')].update(**{'if': 'success()'}))


class DeploymentPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.asset = Path(self.temporary.name) / 'SAP-Lens-test.zip'; self.asset.write_bytes(b'synthetic verified bytes')

    def test_each_channel_publishes_complete_assets_and_correct_flags(self):
        for channel in ('alpha', 'beta', 'rc', 'stable'):
            api = FakeGitHub(); result = release.publish(api, identity(channel), [self.asset])
            self.assertFalse(result['draft']); self.assertEqual(result['prerelease'], channel != 'stable')
            self.assertEqual(api.ref, 'b' * 40)
            self.assertEqual(result['target_commitish'], SHA)
            self.assertEqual(result['make_latest'], 'true' if channel == 'stable' else 'false')
            create=next(data for method,path,data in api.calls if method=='POST' and path=='/releases')
            self.assertTrue(create['generate_release_notes'])
            self.assertTrue(create['draft'])

    def test_existing_tag_or_release_never_mutated(self):
        for existing in ('tag', 'release'):
            api = FakeGitHub()
            if existing == 'tag': api.ref = 'c' * 40
            else: api.release = {'id': 9, 'tag_name': identity()['tag'], 'draft': False}
            with self.subTest(existing=existing), self.assertRaises(release.DeliveryError):
                release.publish(api, identity(), [self.asset])
            self.assertTrue(all(method == 'GET' for method, _, _ in api.calls))

    def test_failed_upload_or_digest_creates_no_tag_and_removes_owned_draft(self):
        for setting in ('fail_upload', 'corrupt_digest'):
            api = FakeGitHub(); setattr(api, setting, True)
            with self.subTest(setting=setting), self.assertRaises(release.DeliveryError):
                release.publish(api, identity(), [self.asset])
            self.assertIsNone(api.ref); self.assertIsNone(api.release)
            self.assertFalse(any(path == '/git/refs' for _, path, _ in api.calls))

    def test_failed_publish_rolls_back_only_owned_tag_and_draft(self):
        api = FakeGitHub(); api.fail_publish = True
        with self.assertRaisesRegex(release.DeliveryError, 'rolled back'):
            release.publish(api, identity(), [self.asset])
        self.assertIsNone(api.ref); self.assertIsNone(api.release)

    def test_lost_publish_response_reconciles_without_retry_or_deletion(self):
        api = FakeGitHub(); api.lost_publish_reply = True
        self.assertFalse(release.publish(api, identity(), [self.asset])['draft'])
        self.assertEqual(sum(method == 'PATCH' for method, _, _ in api.calls), 1)
        self.assertFalse(any(method == 'DELETE' for method, _, _ in api.calls))

    def test_uncertain_remote_state_is_preserved_for_manual_reconciliation(self):
        api = FakeGitHub(); api.fail_publish = True; api.unknown_after_failure = True
        with self.assertRaisesRegex(release.DeliveryError, 'manual reconciliation'):
            release.publish(api, identity(), [self.asset])
        self.assertEqual(api.ref, 'b' * 40)
        self.assertFalse(any(method == 'DELETE' for method, _, _ in api.calls))

    def test_tag_created_by_someone_else_during_upload_is_not_deleted(self):
        api = FakeGitHub(); api.foreign_tag_during_upload = True
        with self.assertRaises(release.DeliveryError): release.publish(api, identity(), [self.asset])
        self.assertEqual(api.ref, 'c' * 40); self.assertIsNone(api.release)
        self.assertFalse(any(path.startswith('/git/refs/tags/') and method == 'DELETE' for method, path, _ in api.calls))
