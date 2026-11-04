"""Shared build CLI, consent, routing and failures; no installer/system modifications."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from build_system import cli, prerequisites as deps, targets
from build_system.runner import BuildError, Runner


def args(*values):
    value=cli.parser().parse_args(values);value.tool_args=[]
    return cli.configure(value,False)


class CliTests(unittest.TestCase):
    def test_noninteractive_default_is_quick_targeted_and_no_system_install(self):
        value=args()
        self.assertEqual((value.mode,value.scope,value.install_system),('quick','targeted',False))

    def test_interactive_menu_prompts_only_for_missing_arguments(self):
        read=Mock(side_effect=['build','windows','installer'])
        value=cli.parser().parse_args([]);value.tool_args=[]
        cli.configure(value,True,read)
        self.assertEqual((value.mode,value.platform,value.target),('build','windows','installer'))
        self.assertEqual(read.call_count,3)
        read.reset_mock()
        value=args('package','--platform','linux','--target','server')
        cli.configure(value,True,read);read.assert_not_called()

    def test_empty_menu_uses_quick_default_and_case_insensitive_inputs(self):
        value=cli.parser().parse_args([]);value.tool_args=[]
        cli.configure(value,True,lambda _: '')
        self.assertEqual(value.mode,'quick')
        self.assertEqual(args('PaCkAgE','--platform','WINDOWS','--target','INSTALLER').target,'installer')

    def test_invalid_target_combinations_and_full_packaging_are_rejected(self):
        for values in [('package','--platform','linux','--target','installer'),('build','--platform','docker','--target','desktop'),('build','--scope','full'),('quick','--setup-only','--skip-setup')]:
            with self.subTest(values=values),self.assertRaises(BuildError):args(*values)

    def test_dry_run_does_not_setup_execute_or_create_logs(self):
        with patch.object(cli,'Runner') as runner,patch.object(deps,'check_tools') as check,patch.object(deps,'prepare_environment') as setup,contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(['quick','--dry-run','--non-interactive']),0)
        runner.return_value.run.assert_not_called();check.assert_not_called();setup.assert_not_called()
        result=json.loads(output.getvalue());self.assertEqual(result['scope'],'targeted');self.assertFalse(result['system_install_opt_in'])

    def test_help_has_no_dependency_or_setup_side_effects(self):
        with patch.object(deps,'check_tools') as check,contextlib.redirect_stdout(io.StringIO()),self.assertRaises(SystemExit) as exit:
            cli.main(['--help'])
        self.assertEqual(exit.exception.code,0);check.assert_not_called()

    def test_ci_never_prompts_and_forbids_bootstrap_in_internal_adapter(self):
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true'}),patch('builtins.input',side_effect=AssertionError('No prompts')),patch.object(cli,'Runner'),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['package','--ci-tool','native-package','--install-system','--','native']),2)

    def test_noninteractive_subprocess_exit_is_forwarded(self):
        with patch.object(cli,'Runner') as runner,patch.object(deps,'check_tools'),contextlib.redirect_stderr(io.StringIO()):
            runner.return_value.run.side_effect=BuildError('Synthetic command failure',23)
            self.assertEqual(cli.main(['quick','--non-interactive']),23)


class RoutingTests(unittest.TestCase):
    def test_quick_never_contains_install_packaging_or_full_regression(self):
        value=args('quick');value.version=targets.product_version()
        commands=targets.plan(value)
        flat=str(commands)
        for forbidden in ('pip','npm ci','PyInstaller','regression','test:browser'):self.assertNotIn(forbidden,flat)
        self.assertIn('local-build.py',flat)

    def test_windows_desktop_and_installer_use_existing_specialized_packagers(self):
        with patch.object(targets.platform,'system',return_value='Windows'):
            desktop=args('build','--platform','windows','--target','desktop');desktop.version='1.0.0-beta.2'
            self.assertIn('build-local.ps1',str(targets.plan(desktop)))
            installer=args('package','--platform','windows','--target','installer');installer.version=desktop.version
            self.assertIn('build-deployments.py',str(targets.plan(installer)))
            self.assertIn('--scope',str(targets.plan(installer)))

    def test_linux_docker_service_and_all_keep_existing_target_names(self):
        for platform,target,expected in [('linux','server','linux-native'),('docker','server','docker'),('windows','service','service'),('windows','all','desktop'),('all','all','all')]:
            value=args('package','--platform',platform,'--target',target);value.version='1.0.0-beta.2';value.windows_host='synthetic-builder'
            with patch.object(targets.platform,'system',return_value='Linux'):
                self.assertIn(expected,targets.plan(value)[0][1])

    def test_unsupported_windows_portable_build_fails_on_linux(self):
        value=args('build','--platform','windows','--target','desktop');value.version='1.0.0-beta.2'
        with patch.object(targets.platform,'system',return_value='Linux'),self.assertRaisesRegex(BuildError,'requires Windows'):targets.plan(value)

    def test_skip_setup_reuses_verified_inputs_not_an_unchecked_skip(self):
        value=args('package','--platform','linux','--target','server','--skip-setup');value.version='1.0.0-beta.2'
        self.assertIn('--reuse-validation',targets.plan(value)[0][1])
        self.assertNotIn('--no-verify',targets.plan(value)[0][1])

    def test_ci_tools_are_whitelisted_mode_checked_and_do_not_bootstrap(self):
        value=args('package','--ci-tool','native-package');value.version='1.0.0-beta.2';value.tool_args=['native']
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'false'}),self.assertRaises(BuildError):targets.plan(value)
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true'}):
            command=targets.plan(value)[0][1]
            self.assertTrue(command[-2].endswith('deployment-package.py'));self.assertEqual(command[-1],'native')
            value.mode='quick'
            with self.assertRaises(BuildError):targets.plan(value)

    def test_stable_preparation_rejected_from_work_and_no_publication_command(self):
        value=args('release','--output','dist/synthetic','--version','1.0.0');value.version='1.0.0'
        with patch.object(targets.subprocess,'check_output',return_value='work\n'),self.assertRaises(BuildError):targets.plan(value)
        value.version='1.0.0-beta.2'
        with patch.object(targets.subprocess,'check_output',return_value='work\n'):
            commands=targets.plan(value)
        self.assertIn('--verify-output',str(commands));self.assertNotIn('publish',str(commands));self.assertNotIn('git tag',str(commands))


class BootstrapperStaticTests(unittest.TestCase):
    """No PowerShell is available on Linux CI: these are static guards for the Windows PowerShell 5.1 baseline, not execution evidence."""
    def test_root_bootstrapper_keeps_the_51_baseline_and_forwards_help(self):
        import re
        text=(ROOT/'build.ps1').read_text(encoding='utf-8')
        self.assertTrue(text.startswith('#requires -Version 5.1'))
        for token in (r'\?\?',r'\?\.',r'-AsHashtable',r'-Parallel',r'\$IsWindows',r'\$IsLinux',r'utf8NoBOM',r'\s&&\s'):
            self.assertIsNone(re.search(token,text),token)
        self.assertIn("'--help'",text);self.assertIn('Windows_NT',text)
        self.assertNotIn('Set-ExecutionPolicy',text);self.assertNotIn('Bypass',text)


class PrerequisiteTests(unittest.TestCase):
    def test_powershell_is_required_for_windows_hosts_only_not_for_linux_packaging(self):
        args=SimpleNamespace(mode='package',platform='linux',skip_setup=False,install_system=False)
        with patch.object(deps,'locate',side_effect=lambda name:None if name in('pwsh','powershell') else name),patch.object(deps,'inspect_tool',return_value=True),\
             patch.object(deps.sys,'version_info',(3,12,0,'final',0)):
            with patch.object(deps.os,'name','posix'):deps.check_tools(args,Mock(),False)
            with patch.object(deps.os,'name','nt'),self.assertRaises(BuildError) as raised:deps.check_tools(args,Mock(),False)
        self.assertEqual(raised.exception.code if hasattr(raised.exception,'code') else 3,3);self.assertIn('5.1',str(raised.exception))

    def test_missing_node_and_compatible_existing_tool_detection(self):
        with patch.object(deps,'locate',return_value=None):self.assertIsNone(deps.inspect_tool('node'))
        for major in (24,25):
            with patch.object(deps,'locate',return_value='synthetic-node'),patch.object(deps.subprocess,'check_output',return_value=f'{major}.2.0'):
                self.assertEqual(deps.inspect_tool('node'),'synthetic-node')
        with patch.object(deps,'locate',return_value='synthetic-node'),patch.object(deps.subprocess,'check_output',return_value='26.0.0'),self.assertRaises(BuildError):deps.inspect_tool('node')

    def test_declined_install_and_noninteractive_default_never_execute_installer(self):
        for interactive in (True,False):
            runner=Mock()
            with patch.object(deps.os,'name','nt'),patch.object(deps,'locate',return_value='synthetic-winget'),self.assertRaises(BuildError):
                deps.install_system('git',runner,False,interactive,lambda _: 'no')
            runner.run.assert_not_called()

    def test_explicit_per_user_node_install_selects_supported_pinned_major(self):
        runner=Mock()
        with patch.object(deps.os,'name','nt'),patch.object(deps,'locate',return_value='synthetic-winget'),patch.object(deps.subprocess,'check_output',return_value='26.0.0\n24.10.0\n24.12.0\n'),patch.object(deps,'inspect_tool',return_value='installed-node'):
            deps.install_system('node',runner,True,False)
        command=runner.run.call_args.args[1]
        self.assertIn('24.12.0',command);self.assertIn('user',command);self.assertNotIn('26.0.0',command)

    def test_winget_without_supported_node_version_fails_without_arbitrary_upgrade(self):
        runner=Mock()
        with patch.object(deps.os,'name','nt'),patch.object(deps,'locate',return_value='synthetic-winget'),patch.object(deps.subprocess,'check_output',return_value='26.0.0\n'),self.assertRaises(BuildError):deps.install_system('node',runner,True)
        runner.run.assert_not_called()

    def test_setup_creates_local_environment_and_uses_lockfiles(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(deps,'locate',return_value='npm'),patch.object(deps.subprocess,'check_output',return_value='[3,12]'):
            root=Path(temporary);runner=Mock();deps.prepare_environment(root,runner)
        commands=[call.args[1] for call in runner.run.call_args_list]
        self.assertIn('venv',commands[0]);self.assertIn('requirements-dev.txt',' '.join(map(str,commands[2])))
        self.assertIn('ci',commands[-1]);self.assertNotIn('update',str(commands))

    def test_existing_environment_is_reused_and_incompatible_one_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);python=root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python');python.parent.mkdir(parents=True);python.touch();runner=Mock()
            with patch.object(deps,'locate',return_value='npm'),patch.object(deps.subprocess,'check_output',return_value='[3,12]'):deps.prepare_environment(root,runner)
            self.assertFalse(any('venv' in call.args[1] for call in runner.run.call_args_list))
            with patch.object(deps.subprocess,'check_output',return_value='[3,13]'),self.assertRaises(BuildError):deps.prepare_environment(root,Mock())


class SafetyTests(unittest.TestCase):
    def test_runner_preserves_child_status_and_structured_logs(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner=Runner(Path(temporary))
            with patch('build_system.runner.subprocess.run',return_value=SimpleNamespace(returncode=17)),self.assertRaises(BuildError) as error:runner.run('Synthetic failure',['synthetic'])
            self.assertEqual(error.exception.code,17)
            event=json.loads((runner.directory/'events.jsonl').read_text());self.assertEqual(event['exit_code'],17)

    def test_clean_requires_confirmation_and_refuses_arbitrary_output(self):
        value=args('clean');value.version='1.0.0-beta.2'
        with self.assertRaisesRegex(BuildError,'confirm-clean'):targets.clean(value,Mock())
        value.output=ROOT/'backend/resources';value.confirm_clean=True
        with self.assertRaises(BuildError):targets.clean(value,Mock())

    def test_bootstrap_is_not_dependent_on_python_and_never_bypasses_policy(self):
        source=(ROOT/'build.ps1').read_text()
        for item in ('Find-BuildPython','Python.Python.3.12','--scope user','--non-interactive','scripts/build.py','-NonInteractive','nonInteractiveRun'):
            self.assertIn(item.lstrip('-') if item=='-NonInteractive' else item,source)
        self.assertNotIn('ExecutionPolicy Bypass',source);self.assertNotIn('Invoke-Expression',source);self.assertNotIn('Invoke-WebRequest',source)
        self.assertIn('Read-Host',source);self.assertIn('$LASTEXITCODE',source)

class OwnershipAndScopeTests(unittest.TestCase):
    def test_clean_refuses_an_owned_build_and_preserves_user_data(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(targets,'ROOT',Path(temporary)):
            root=Path(temporary);build=root/'backend/build';build.mkdir(parents=True)
            (build/'deployment-builder.lock').write_text('synthetic owner')
            data=root/'private-user-data';data.mkdir();(data/'keep').write_text('synthetic')
            value=args('clean','--confirm-clean')
            with self.assertRaisesRegex(BuildError,'deployment build lock'):targets.clean(value,Mock())
            self.assertTrue((build/'deployment-builder.lock').exists());self.assertTrue((data/'keep').exists())
            self.assertFalse((root/'dist/.sap-lens-clean.lock').exists())

    def test_confirmed_clean_only_removes_the_allowlisted_generated_paths(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(targets,'ROOT',Path(temporary)):
            root=Path(temporary)
            for name in targets.CLEAN_PATHS:(root/name).mkdir(parents=True,exist_ok=True)
            user=root/'data';user.mkdir();(user/'keep').write_text('synthetic')
            with contextlib.redirect_stdout(io.StringIO()):targets.clean(args('clean','--confirm-clean'),Mock())
            self.assertTrue((user/'keep').exists())
            self.assertFalse(any((root/name).exists() for name in targets.CLEAN_PATHS))

    def test_linked_output_is_rejected_before_resolution(self):
        with patch('build_system.cli.Path.is_symlink',return_value=True),self.assertRaisesRegex(BuildError,'linked path'):
            args('package','--output','dist/synthetic')

    def test_setup_and_install_flags_cannot_bypass_skip_setup(self):
        with self.assertRaises(BuildError):args('quick','--skip-setup','--install-system')

    def test_timing_and_publication_guards_survive_ci_entrypoint_migration(self):
        for name in ('validate.yml','full-validation.yml','build-deployments.yml','build-windows.yml'):
            source=(ROOT/'.github/workflows'/name).read_text()
            self.assertIn('python scripts/build.py',source)
            self.assertIn('--non-interactive',source)
        source=(ROOT/'scripts/build-deployments.py').read_text()
        self.assertIn("['targeted','deployment']",source)
        self.assertIn("['--grep','@smoke']",source)
        self.assertIn("'--scope', self.args.scope",source)
        self.assertIn('dist/.sap-lens-clean.lock',source)
        self.assertIn('dist/.sap-lens-clean.lock',(ROOT/'scripts/build-local.ps1').read_text())


class CiAdmissionTests(unittest.TestCase):
    def test_every_ci_adapter_plans_noninteractively_without_local_release_or_setup_requirements(self):
        modes={'validation':'test','windows-stage':'build','installer-check':'build','windows-package':'package','native-package':'package','docker-package':'package','deployment-release':'release','legacy-release':'release'}
        for tool,mode in modes.items():
            with self.subTest(tool=tool),patch.dict(os.environ,{'GITHUB_ACTIONS':'true'}),patch.object(deps,'check_tools') as prerequisites,contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main([mode,'--ci-tool',tool,'--non-interactive','--dry-run']),0)
                result=json.loads(output.getvalue());self.assertEqual(len(result['commands']),1)
                prerequisites.assert_not_called()

    def test_benchmark_flag_preserves_the_existing_boolean_switch(self):
        value=args('build','--ci-tool','windows-stage','--benchmark-packaging','true');value.tool_args=['-Stage','Package']
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true'}):
            command=targets.plan(value)[0][1]
            self.assertIn('-BenchmarkPackaging',command)
            value.benchmark_packaging='false'
            self.assertNotIn('-BenchmarkPackaging',targets.plan(value)[0][1])


class ReleaseEnvironmentTests(unittest.TestCase):
    def test_release_can_reuse_existing_packaging_dependencies_without_frontend_setup(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(cli,'ROOT',Path(temporary)):
            candidate=Path(temporary)/'backend/build/python-env'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            candidate.parent.mkdir(parents=True);candidate.touch()
            value=args('release','--output','dist/synthetic','--skip-setup')
            with patch.object(cli.subprocess,'check_output',return_value=b''),patch.object(deps,'prepare_environment') as setup:
                self.assertEqual(cli.test_python(value,Mock()),candidate)
                setup.assert_not_called()

    def test_release_dependency_repair_does_not_install_node_modules(self):
        value=args('release','--output','dist/synthetic','--setup')
        with patch.object(deps,'prepare_environment',return_value=Path('synthetic-python')) as setup:
            cli.test_python(value,Mock())
        self.assertFalse(setup.call_args.kwargs['frontend'])
