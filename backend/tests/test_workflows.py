"""Exercise real workflow definitions and reject dangerous trigger/policy drift."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('workflow_contracts', Path(__file__).resolve().parents[2] / 'scripts/check-workflows.py')
contracts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contracts)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflows = contracts.load_workflows()

    def test_actual_workflows_satisfy_contract(self):
        contracts.validate(self.workflows)

    def test_push_and_pull_request_trigger_matrix(self):
        for event, branch, expected in [
            ('push', 'work', (True, False, False)),
            ('push', 'main', (True, False, False)),
            ('push', 'feature/synthetic', (True, False, False)),
            ('pull_request', 'main', (True, True, False)),
            ('pull_request', 'work', (True, False, False)),
            ('pull_request', 'feature/target', (True, False, False)),
            ('workflow_dispatch', 'work', (False, False, True)),
            ('workflow_dispatch', 'main', (False, False, True)),
            ('release', 'main', (False, False, False)),
        ]:
            with self.subTest(event=event, branch=branch):
                self.assertEqual(tuple(contracts.triggered(self.workflows[name], event, branch)
                                       for name in contracts.EXPECTED), expected)

    def test_branch_path_or_manual_trigger_drift_rejected(self):
        for filename, event, value in [
            ('validate.yml', 'push', {'branches': ['work']}),
            ('validate.yml', 'pull_request', {'paths': ['backend/**']}),
            ('full-validation.yml', 'push', ''),
            ('full-validation.yml', 'workflow_dispatch', ''),
            ('full-validation.yml', 'pull_request', {'branches': ['work']}),
            ('build-windows.yml', 'push', ''),
        ]:
            changed = copy.deepcopy(self.workflows)
            changed[filename]['on'][event] = value
            with self.subTest(filename=filename, event=event), self.assertRaises(ValueError):
                contracts.validate(changed)

    def test_security_permissions_actions_and_checkout_credentials_rejected(self):
        for mutation in ('permissions', 'pin', 'credentials', 'failure'):
            changed = copy.deepcopy(self.workflows)
            fast = changed['validate.yml']
            first = fast['jobs']['fast']['steps'][0]
            if mutation == 'permissions': fast['permissions']['contents'] = 'write'
            if mutation == 'pin': first['uses'] = 'actions/checkout@main'
            if mutation == 'credentials': first['with']['persist-credentials'] = 'true'
            if mutation == 'failure': first['continue-on-error'] = 'true'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                contracts.validate(changed)

    def test_concurrency_cannot_cancel_pr_checks_or_active_manual_builds(self):
        for filename in contracts.EXPECTED:
            changed = copy.deepcopy(self.workflows)
            changed[filename]['concurrency'] = {'group': 'shared', 'cancel-in-progress': 'true'}
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                contracts.validate(changed)

    def test_missing_or_cyclic_job_dependencies_rejected(self):
        for jobs in ({'a': {'needs': 'missing'}}, {'a': {'needs': 'b'}, 'b': {'needs': 'a'}}):
            with self.assertRaises(ValueError): contracts.validate_graph(jobs)
        contracts.validate_graph({'a': {}, 'b': {'needs': ['a']}})

    def test_duplicate_yaml_keys_rejected(self):
        with self.assertRaises(ValueError):
            contracts.yaml.load('on:\n  push:\non:\n  workflow_dispatch:\n', Loader=contracts.UniqueLoader)

    def test_no_duplicate_installs_or_builds_in_frontend_job(self):
        steps = self.workflows['full-validation.yml']['jobs']['frontend']['steps']
        commands = '\n'.join(step.get('run', '') for step in steps)
        self.assertEqual(commands.count('frontend ci '), 1)
        self.assertEqual(commands.count('frontend run build'), 1)
        self.assertIn('install --with-deps chromium --only-shell', commands)

    def test_browser_cache_is_exact_platform_architecture_and_lockfile(self):
        for filename, job in [('full-validation.yml', 'frontend'), ('build-windows.yml', 'windows-exe')]:
            steps = self.workflows[filename]['jobs'][job]['steps']
            cache = next(step['with'] for step in steps if step.get('uses', '').startswith('actions/cache@'))
            self.assertNotIn('restore-keys', cache)
            for token in ('runner.os', 'runner.arch', "hashFiles('frontend/package-lock.json')"):
                self.assertIn(token, cache['key'])
            self.assertEqual(cache['path'], '${{ runner.temp }}/sap-lens-playwright')

    def test_integrity_or_test_stage_cannot_be_skipped(self):
        for stage in ('Backend', 'Browser', 'Verify', 'Smoke', 'Artifact'):
            changed = copy.deepcopy(self.workflows)
            steps = changed['build-windows.yml']['jobs']['windows-exe']['steps']
            next(step for step in steps if f'-Stage {stage}' in step.get('run', ''))['if'] = 'false'
            with self.subTest(stage=stage), self.assertRaises(ValueError): contracts.validate(changed)

    def test_wrong_artifact_or_warning_only_digest_rejected(self):
        for field, value in [('artifact-ids', 'another-run'), ('digest-mismatch', 'warn')]:
            changed = copy.deepcopy(self.workflows)
            steps = changed['build-windows.yml']['jobs']['windows-exe']['steps']
            download = next(step for step in steps if step.get('uses', '').startswith('actions/download-artifact@'))
            download['with'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): contracts.validate(changed)


    def test_release_permission_dependency_environment_and_artifact_drift_rejected(self):
        for mutation in ('permissions','needs','condition','environment','artifact'):
            changed = copy.deepcopy(self.workflows)
            job = changed['build-windows.yml']['jobs']['publish-release']
            if mutation == 'permissions': job['permissions']['actions'] = 'write'
            if mutation == 'needs': job['needs'] = []
            if mutation == 'condition': job['if'] = 'always()'
            if mutation == 'environment': job['environment']['name'] = 'unprotected'
            if mutation == 'artifact':
                next(s for s in job['steps'] if s.get('uses','').startswith('actions/download-artifact@'))['with']['artifact-ids']='unrelated'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): contracts.validate(changed)

    def test_release_inputs_keep_build_default_and_benchmarks_unchanged(self):
        for mutation in ('default','options','benchmark','version'):
            changed = copy.deepcopy(self.workflows)
            inputs = changed['build-windows.yml']['on']['workflow_dispatch']['inputs']
            if mutation == 'default': inputs['release_mode']['default']='beta'
            if mutation == 'options': inputs['release_mode']['options'].append('automatic')
            if mutation == 'benchmark': inputs['cold_cache']['default']='true'
            if mutation == 'version': inputs['version']['required']='false'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): contracts.validate(changed)
