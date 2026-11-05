"""Build failure diagnostics, Windows file-lock handling, the isolated frontend workspace and accurate manifest classification (no real locks needed)."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'backend'))
from build_system import failures, frontend_workspace as workspace  # noqa: E402

spec = importlib.util.spec_from_file_location('build_deployments_diag', ROOT / 'scripts/build-deployments.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

NPM_EPERM = r"""npm error code EPERM
npm error syscall unlink
npm error path C:\Users\Test User\sap lens\frontend\node_modules\lightningcss-win32-x64-msvc\lightningcss.win32-x64-msvc.node
npm error errno -4048
npm error [Error: EPERM: operation not permitted, unlink 'C:\Users\Test User\sap lens\frontend\node_modules\lightningcss-win32-x64-msvc\lightningcss.win32-x64-msvc.node']"""


class Classification(unittest.TestCase):
    def test_npm_eperm_on_unlink_is_a_transient_lock_with_the_affected_path(self):
        lock = failures.classify_lock(NPM_EPERM)
        self.assertEqual((lock['kind'], lock['code'], lock['operation']), ('locked', 'EPERM', 'unlink'))
        self.assertTrue(lock['path'].endswith('lightningcss.win32-x64-msvc.node'), lock['path'])
        self.assertIn('Test User', lock['path'])  # Windows paths with spaces survive

    def test_busy_files_are_transient_and_access_denied_is_permanent(self):
        for text in ('EBUSY: resource busy or locked, rename', "PermissionError: [WinError 32] The process cannot access the file because it is being used by another process"):
            self.assertEqual(failures.classify_lock(text)['kind'], 'locked', text)
        for text in ('EACCES: permission denied, open /x', "PermissionError: [WinError 5] Access is denied: 'C:\\x'"):
            self.assertEqual(failures.classify_lock(text)['kind'], 'permission', text)
        self.assertIsNone(failures.classify_lock('npm error code E404\nnpm error 404 Not Found'))

    def test_secrets_never_reach_the_summary_or_the_record(self):
        with patch.dict(os.environ, {'NPM_TOKEN': 'super-secret-value-123'}):
            failure = failures.StageFailure('Install locked frontend dependencies', ['npm', '--prefix', 'a b', 'ci'], '/work tree', 1,
                                            'npm error //registry.example/:_authToken=abc123456\nfetch https://user:hunter2pw@host/x failed\nsuper-secret-value-123', '/log/build.log')
        text = failure.summary() + json.dumps(failure.as_record())
        for secret in ('super-secret-value-123', 'abc123456', 'hunter2pw'):
            self.assertNotIn(secret, text)

    def test_summary_names_stage_command_directory_exit_code_cause_and_log(self):
        failure = failures.StageFailure('Install locked frontend dependencies', ['npm', '--prefix', 'C:\\My Repo\\ws\\frontend', 'ci', '--no-audit'], 'C:\\My Repo', 1, NPM_EPERM, 'dist/1.0.0/build.log', 'dependency_install')
        text = str(failure)
        for expected in ('Build stage failed: Install locked frontend dependencies', "'C:\\My Repo\\ws\\frontend'", 'Working directory: C:\\My Repo', 'Exit code: 1', 'EPERM', 'locked by another process', 'Detailed log: dist/1.0.0/build.log'):
            self.assertIn(expected, text)
        record = failure.as_record()
        self.assertEqual((record['failed_stage'], record['failure_class'], record['exit_code'], record['file_lock']['kind']), ('Install locked frontend dependencies', 'dependency_install', 1, 'locked'))
        self.assertLessEqual(len(record['output_tail']), 20)

    def test_permission_failures_are_explained_without_asking_for_administrator_rights(self):
        failure = failures.StageFailure('x', ['npm'], '.', 1, 'EACCES: permission denied')
        self.assertIn('not required', failure.hint)
        self.assertEqual(failure.lock['kind'], 'permission')


class IsolatedWorkspace(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'Repo With Spaces'
        for name, text in {'frontend/package.json': '{"name":"x"}', 'frontend/package-lock.json': '{"lockfileVersion":3}', 'frontend/src/main.tsx': 'x',
                           'frontend/node_modules/dev-only/index.js': 'dev', 'frontend/dist/old.js': 'old', 'frontend/test-results/r.txt': 'r',
                           'scripts/tool.mjs': 'tool', 'scripts/__pycache__/c.pyc': 'c', 'backend/main.py': 'm', 'backend/resources/product-version.json': '{}',
                           'backend/build/build-version.json': '{"v":1}', 'backend/build/python-env/x': 'env', 'backend/tests/test_x.py': 't'}.items():
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        self.work = self.root / 'backend/build/frontend-workspace'

    def test_mirror_copies_sources_and_identity_but_never_node_modules_or_stale_output(self):
        workspace.mirror(self.root, self.work)
        self.assertTrue((self.work / 'frontend/src/main.tsx').is_file())
        self.assertEqual((self.work / 'backend/build/build-version.json').read_text(), '{"v":1}')
        for name in ('frontend/node_modules', 'frontend/dist', 'frontend/test-results', 'backend/build/python-env', 'backend/tests', 'scripts/__pycache__'):
            self.assertFalse((self.work / name).exists(), name)
        self.assertTrue((self.root / 'frontend/node_modules/dev-only/index.js').is_file())  # the developer's installation is untouched

    def test_remirror_keeps_the_workspace_installation_but_drops_removed_sources_and_stale_dist(self):
        workspace.mirror(self.root, self.work)
        (self.work / 'frontend/node_modules/pkg').mkdir(parents=True); (self.work / 'frontend/node_modules/pkg/i.js').write_text('x')
        (self.work / 'frontend/dist').mkdir(); (self.work / 'frontend/dist/index.html').write_text('stale')
        (self.root / 'frontend/src/main.tsx').unlink()
        workspace.mirror(self.root, self.work)
        self.assertTrue((self.work / 'frontend/node_modules/pkg/i.js').is_file())
        self.assertFalse((self.work / 'frontend/src/main.tsx').exists())
        self.assertFalse((self.work / 'frontend/dist').exists())

    @unittest.skipIf(os.name == 'nt', 'creating symbolic links needs a privilege on Windows')
    def test_linked_sources_are_refused(self):
        (self.root / 'frontend/src/leak').symlink_to(self.root / 'backend')
        with self.assertRaisesRegex(workspace.WorkspaceError, 'linked'):
            workspace.mirror(self.root, self.work)

    def test_dependency_stamp_follows_the_lockfile_and_node_major(self):
        first = workspace.dependency_stamp(self.root, '25.8.0')
        self.assertEqual(first, workspace.dependency_stamp(self.root, '25.1.0'))
        self.assertNotEqual(first, workspace.dependency_stamp(self.root, '24.2.0'))
        (self.root / 'frontend/package-lock.json').write_text('{"lockfileVersion":3,"changed":1}')
        self.assertNotEqual(first, workspace.dependency_stamp(self.root, '25.8.0'))

    def test_current_installation_is_reused_and_a_changed_stamp_reinstalls_once(self):
        workspace.mirror(self.root, self.work)
        calls = []
        def run(label):
            calls.append(label); (self.work / 'frontend/node_modules').mkdir(exist_ok=True); (self.work / 'frontend/node_modules/.package-lock.json').write_text('{}')
        self.assertEqual(workspace.install(self.work, 's1', run), 1)
        self.assertEqual(workspace.install(self.work, 's1', run), 0)   # no repeated installation for the second target or the next run
        self.assertEqual(workspace.install(self.work, 's2', run), 1)
        self.assertEqual(len(calls), 2)

    def failure(self, text, code=1):
        return failures.StageFailure('Install locked frontend dependencies', ['npm', 'ci'], self.work, code, text)

    def test_transient_lock_is_retried_with_bounded_backoff_then_succeeds(self):
        workspace.mirror(self.root, self.work)
        attempts, delays = [], []
        def run(label):
            attempts.append(1)
            if len(attempts) < 3: raise self.failure(NPM_EPERM)
            (self.work / 'frontend/node_modules').mkdir(exist_ok=True); (self.work / 'frontend/node_modules/.package-lock.json').write_text('{}')
        self.assertEqual(workspace.install(self.work, 's', run, sleep=delays.append), 3)
        self.assertEqual(delays, [3, 8])

    def test_retries_are_bounded_and_permanent_or_unrelated_errors_are_not_retried(self):
        workspace.mirror(self.root, self.work)
        for text, expected_attempts in ((NPM_EPERM, 3), ('EACCES: permission denied', 1), ('npm error 404 Not Found', 1)):
            attempts = []
            def run(label, text=text, attempts=attempts):
                attempts.append(1); raise self.failure(text)
            with self.assertRaises(failures.StageFailure):
                workspace.install(self.work, 'new-' + str(expected_attempts) + text[:3], run, sleep=lambda _: None)
            self.assertEqual(len(attempts), expected_attempts, text)

    def test_publish_replaces_dist_atomically_and_leaves_no_staging_directories(self):
        workspace.mirror(self.root, self.work)
        (self.work / 'frontend/dist/assets').mkdir(parents=True)
        (self.work / 'frontend/dist/index.html').write_text('new'); (self.work / 'frontend/dist/assets/a.js').write_text('a')
        self.assertEqual(workspace.publish_dist(self.work, self.root), 2)
        self.assertEqual((self.root / 'frontend/dist/index.html').read_text(), 'new')
        self.assertFalse((self.root / 'frontend/dist/old.js').exists())
        self.assertEqual([p.name for p in (self.root / 'frontend').iterdir() if p.name.startswith('dist.')], [])

    def test_publish_refuses_an_incomplete_build_and_restores_the_old_assets_on_failure(self):
        workspace.mirror(self.root, self.work)
        with self.assertRaisesRegex(workspace.WorkspaceError, 'no index.html'):
            workspace.publish_dist(self.work, self.root)
        self.assertTrue((self.root / 'frontend/dist/old.js').is_file())
        (self.work / 'frontend/dist').mkdir(); (self.work / 'frontend/dist/index.html').write_text('new')
        real = Path.rename
        def locked(self_path, target):
            if self_path.name == 'dist': raise PermissionError(32, 'in use')
            return real(self_path, target)
        with patch.object(Path, 'rename', locked), self.assertRaisesRegex(workspace.WorkspaceError, 'Could not publish'):
            workspace.publish_dist(self.work, self.root)
        self.assertTrue((self.root / 'frontend/dist/old.js').is_file())

    def test_the_workspace_is_a_generated_ignored_cleanable_path(self):
        self.assertEqual(subprocess.run(['git', 'check-ignore', '-q', 'backend/build/frontend-workspace/frontend/node_modules/x'], cwd=ROOT).returncode, 0)
        from build_system import layout
        self.assertIn('backend/build', layout.GENERATED)


class NodeBaseline(unittest.TestCase):
    def test_supported_current_release_gets_one_lts_recommendation_and_unsupported_versions_fail_early(self):
        from build_system import prerequisites
        from build_system.runner import BuildError
        for version, noted in (('25.8.0', True), ('24.11.0', False)):
            prerequisites.NOTED.clear()
            with patch.object(prerequisites, 'locate', return_value='node'), patch.object(prerequisites.subprocess, 'check_output', return_value=version), patch('builtins.print') as output:
                self.assertEqual(prerequisites.inspect_tool('node'), 'node')
                prerequisites.inspect_tool('node')  # repeated inspection stays quiet
            messages = [call.args[0] for call in output.call_args_list if call.args]
            self.assertEqual(len([m for m in messages if 'Node.js 24 LTS' in m]), 1 if noted else 0, version)
        for version in ('22.12.0', '26.0.0'):
            with patch.object(prerequisites, 'locate', return_value='node'), patch.object(prerequisites.subprocess, 'check_output', return_value=version), self.assertRaisesRegex(BuildError, 'Incompatible node'):
                prerequisites.inspect_tool('node')


class BuilderClassification(unittest.TestCase):
    def make(self, log):
        run = object.__new__(builder.Builder)
        run.system = 'Windows'; run.log = log; run.env = {'PATH': 'p'}; run.python = Path('python'); run.stage = 'x'
        run.output = log.parent; run.manifest = dict(targets={}); run.shared_failure = None; run.validated = False; run.validation_started = False
        return run

    def test_a_failed_command_reports_command_directory_exit_code_and_the_real_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = self.make(Path(temporary) / 'build.log')
            def fake(command, cwd, env, stdout, stderr, check):
                stdout.write(NPM_EPERM + '\n'); stdout.flush()
                raise subprocess.CalledProcessError(1, command)
            with patch.object(builder.subprocess, 'run', side_effect=fake), self.assertRaises(failures.StageFailure) as caught:
                run.run('Install locked frontend dependencies', ['npm', '--prefix', 'C:\\a b\\frontend', 'ci'], cwd=temporary)
            failure = caught.exception
            self.assertEqual((failure.exit_code, failure.failure_class, failure.lock['kind']), (1, 'dependency_install', 'locked'))
            self.assertIn('lightningcss', failure.summary())
            self.assertIn('EPERM', (Path(temporary) / 'build.log').read_text())  # the complete output stays in the detailed log

    def test_shared_validation_failure_blocks_every_target_without_calling_it_a_packaging_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = self.make(Path(temporary) / 'build.log'); run.args = SimpleNamespace(platform=['desktop', 'service'])
            install = failures.StageFailure('Install locked frontend dependencies', ['npm', 'ci'], temporary, 1, NPM_EPERM, run.log, 'dependency_install')
            def local(target):
                run.validate_calls = getattr(run, 'validate_calls', 0) + 1
                if run.validation_started: raise failures.BlockedByShared(run.shared_failure)
                run.validation_started = True; run.shared_failure = install; raise install
            with patch.object(builder.Builder, 'local', side_effect=local), patch.object(builder.Builder, 'save'), patch.object(builder, 'host_for', return_value='Windows'), patch('sys.stderr'):
                self.assertEqual(run.execute(), 1)
            rows = run.manifest['targets']
            self.assertEqual({row['status'] for row in rows.values()}, {'blocked'})
            self.assertTrue(all(row['blocked_by'] == 'shared_validation' and 'failed_stage' not in row and not row['built'] for row in rows.values()))
            shared = run.manifest['shared_validation']
            self.assertEqual((shared['status'], shared['failure_class'], shared['failed_stage']), ('failed', 'dependency_install', 'Install locked frontend dependencies'))
            self.assertEqual(run.validate_calls, 2)  # the second target never revalidated or reinstalled

    def test_one_targets_own_packaging_failure_does_not_block_or_hide_the_other(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = self.make(Path(temporary) / 'build.log'); run.args = SimpleNamespace(platform=['desktop', 'service'])
            package = failures.StageFailure('Canonical Windows package and native smoke tests', ['pwsh'], temporary, 2, 'smoke failed', run.log, 'desktop_packaging')
            passed = dict(status='passed', built=True, package_verified=True, runtime_smoke_tested=True, artifact='a.zip', sha256='0' * 64)
            outcomes = [package, passed]
            def local(target):
                value = outcomes.pop(0)
                if isinstance(value, Exception): raise value
                return value
            with patch.object(builder.Builder, 'local', side_effect=local), patch.object(builder.Builder, 'save'), patch.object(builder, 'host_for', return_value='Windows'), patch('sys.stderr'):
                self.assertEqual(run.execute(), 1)
            rows = run.manifest['targets']
            self.assertEqual((rows['desktop']['status'], rows['desktop']['failure_class'], rows['desktop']['exit_code']), ('failed', 'desktop_packaging', 2))
            self.assertEqual(rows['service']['status'], 'passed')
            self.assertNotIn('shared_validation', run.manifest)

    def test_failure_classes_distinguish_dependency_build_and_packaging_stages(self):
        run = object.__new__(builder.Builder)
        self.assertEqual(run.failure_class('Install locked frontend dependencies'), 'dependency_install')
        self.assertEqual(run.failure_class('build'), 'frontend_build')
        self.assertEqual(run.failure_class('types'), 'frontend_validation')
        self.assertEqual(run.failure_class('Browser regression tests'), 'browser_smoke')
        run.current_target = 'service'
        self.assertEqual(run.failure_class('Canonical Windows package and native smoke tests'), 'service_packaging')
        self.assertEqual(run.failure_class('Offline installation and runtime/persistence smoke tests'), 'runtime_smoke')

    def test_an_overlong_windows_workspace_path_is_rejected_with_advice(self):
        run = object.__new__(builder.Builder); run.workspace = Path('C:/' + 'very-long-directory-name/' * 6 + 'backend/build/frontend-workspace')
        with patch.object(builder.os, 'name', 'nt'), self.assertRaisesRegex(workspace.WorkspaceError, 'shorter path'):
            run.prepare_workspace()


if __name__ == '__main__':
    unittest.main()
