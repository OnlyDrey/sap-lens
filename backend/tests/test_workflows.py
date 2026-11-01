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

    def test_trigger_matrix_fast_is_automatic_and_everything_else_is_manual(self):
        # (Fast Validation, Full Validation, Build Windows Application, Build Deployment Packages); a pull request's branch is its target.
        for event, branch, expected in [
            ('push', 'work', (True, False, False, False)),
            ('push', 'main', (True, False, False, False)),
            ('push', 'feature/synthetic', (False, False, False, False)),
            ('pull_request', 'main', (True, False, False, False)),
            ('pull_request', 'work', (False, False, False, False)),
            ('pull_request', 'feature/target', (False, False, False, False)),
            ('workflow_dispatch', 'work', (False, True, True, True)),
            ('workflow_dispatch', 'main', (False, True, True, True)),
            ('release', 'main', (False, False, False, False)),
            ('schedule', 'main', (False, False, False, False)),
            ('workflow_run', 'main', (False, False, False, False)),
        ]:
            with self.subTest(event=event, branch=branch):
                self.assertEqual(tuple(contracts.triggered(self.workflows[name], event, branch) for name in contracts.EXPECTED), expected)

    def test_branch_path_or_manual_trigger_drift_rejected(self):
        for filename, event, value in [
            ('validate.yml', 'push', {'branches': ['work']}),
            ('validate.yml', 'push', ''),
            ('validate.yml', 'pull_request', {'paths': ['backend/**']}),
            ('full-validation.yml', 'push', ''),
            ('full-validation.yml', 'pull_request', {'branches': ['main']}),
            ('full-validation.yml', 'schedule', [{'cron': '0 3 * * *'}]),
            ('full-validation.yml', 'workflow_call', ''),
            ('full-validation.yml', 'workflow_run', {'workflows': ['Fast Validation']}),
            ('build-windows.yml', 'push', ''),
            ('build-windows.yml', 'workflow_run', {'workflows': ['Full Validation']}),
            ('build-deployments.yml', 'push', ''),
            ('build-deployments.yml', 'workflow_run', {'workflows': ['Full Validation']}),
        ]:
            changed = copy.deepcopy(self.workflows)
            changed[filename]['on'][event] = value
            with self.subTest(filename=filename, event=event), self.assertRaises(ValueError):
                contracts.validate(changed)

    def test_full_regression_is_never_a_prerequisite_of_building_or_publishing(self):
        for filename, job, step in [('build-deployments.yml', 'validation', {'name': 'x', 'run': 'python scripts/run-tests.py regression --backend'}),
                                    ('build-deployments.yml', 'validation', {'name': 'x', 'run': 'python -m unittest discover -s backend/tests -v'}),
                                    ('build-deployments.yml', 'desktop', {'name': 'x', 'run': 'npm --prefix frontend run test:browser'}),
                                    ('build-windows.yml', 'windows-exe', {'name': 'x', 'run': './scripts/build-windows.ps1 -Stage Backend'}),
                                    ('build-windows.yml', 'windows-exe', {'name': 'x', 'run': './scripts/build-windows.ps1 -Stage Browser'})]:
            changed = copy.deepcopy(self.workflows)
            changed[filename]['jobs'][job]['steps'].append(step)
            with self.subTest(filename=filename, run=step['run']), self.assertRaises(ValueError):
                contracts.validate(changed)
        changed = copy.deepcopy(self.workflows)
        changed['build-deployments.yml']['jobs']['publish']['if'] += " && needs.full-validation.result == 'success'"
        with self.assertRaises(ValueError):
            contracts.validate(changed)

    def test_fast_validation_optional_steps_depend_only_on_the_change_plan(self):
        for mutation in ('always', 'other_output', 'mandatory_conditional', 'unreported'):
            changed = copy.deepcopy(self.workflows)
            steps = changed['validate.yml']['jobs']['fast']['steps']
            by_id = {step.get('id'): step for step in steps}
            if mutation == 'always': by_id['types']['if'] = 'always()'
            if mutation == 'other_output': by_id['build']['if'] = "${{ github.event_name == 'push' }}"
            if mutation == 'mandatory_conditional': by_id['ruff']['if'] = "${{ steps.plan.outputs.frontend == 'true' }}"
            if mutation == 'unreported': steps[-1]['env']['CI_OPTIONAL'] = steps[-1]['env']['CI_OPTIONAL'].replace(' eslint', '')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                contracts.validate(changed)

    def test_the_sealed_release_receipt_requires_no_complete_suite(self):
        source = (Path(__file__).resolve().parents[2] / 'scripts/deployment-package.py').read_text(encoding='utf-8')
        checks = source.split('CHECKS={', 1)[1].split('}', 1)[0]
        self.assertNotIn("'backend'", checks); self.assertNotIn("'browser'", checks)
        for required in ('types', 'build', 'catalog', 'python_audit', 'javascript_audit', 'pip_check', 'workflow_lint', 'powershell'):
            self.assertIn(f"'{required}'", checks)

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
        for filename, job in [('full-validation.yml', 'frontend'), ('validate.yml', 'fast')]:
            steps = self.workflows[filename]['jobs'][job]['steps']
            cache = next(step['with'] for step in steps if step.get('uses', '').startswith('actions/cache@'))
            self.assertNotIn('restore-keys', cache)
            for token in ('runner.os', 'runner.arch', "hashFiles('frontend/package-lock.json')"):
                self.assertIn(token, cache['key'])
            self.assertEqual(cache['path'], '${{ runner.temp }}/sap-lens-playwright')

    def test_integrity_or_test_stage_cannot_be_skipped(self):
        for stage in ('JavaScriptAudit', 'Verify', 'Smoke', 'Artifact'):
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


    def test_early_allocation_build_gate_and_published_identity_cannot_drift(self):
        for mutation in ('allocator_write','allocator_condition','build_gate','identity_output','publisher_identity'):
            changed=copy.deepcopy(self.workflows)
            jobs=changed['build-windows.yml']['jobs']
            if mutation=='allocator_write':jobs['reserve-version']['permissions']['contents']='read'
            if mutation=='allocator_condition':jobs['reserve-version']['if']='always()'
            if mutation=='build_gate':jobs['windows-exe']['if']='always()'
            if mutation=='identity_output':jobs['reserve-version']['outputs']['metadata']='another-run'
            if mutation=='publisher_identity':jobs['publish-release']['steps'][-1]['env']['BUILD_VERSION_JSON']='recomputed'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):contracts.validate(changed)
