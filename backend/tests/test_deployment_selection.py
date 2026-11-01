"""Build selection of the manual deployment workflow: the single build_target choice is resolved once by a planning job, an unknown value fails
before any expensive job, unselected packages are skipped and can never be published. Offline: no workflow is dispatched."""
import copy
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load('deployment_selection_release', 'scripts/deployment-release.py')
packages = load('deployment_selection_package', 'scripts/deployment-package.py')
contracts = load('deployment_selection_contracts', 'scripts/check-workflows.py')
WD, WS, LD, LN = 'windows-desktop', 'windows-service', 'linux-docker', 'linux-native'
EXPECTED = {  # build_target -> the packages it builds; the seven values of the dropdown, all valid
    'all': [WD, WS, LD, LN], 'windows-all': [WD, WS], 'windows-desktop': [WD], 'windows-service': [WS],
    'linux-all': [LD, LN], 'linux-docker': [LD], 'linux-native': [LN],
}


def run_plan(build_target, **extra):
    with tempfile.TemporaryDirectory() as directory:
        output, summary = Path(directory, 'output'), Path(directory, 'summary.md')
        env = dict(DEPLOYMENT_TARGET=build_target, GITHUB_OUTPUT=str(output), GITHUB_STEP_SUMMARY=str(summary), **extra)
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/deployment-release.py'), 'plan'], env={**os.environ, **env}, capture_output=True, text=True)
        values = dict(line.split('=', 1) for line in output.read_text().splitlines()) if output.exists() else {}
        return done, values, summary.read_text() if summary.exists() else ''


class SelectionTests(unittest.TestCase):
    def test_every_dropdown_value_resolves_to_its_documented_packages(self):
        self.assertEqual(list(release.BUILD_TARGETS), list(EXPECTED), 'the planner offers the seven values, in the dropdown order')
        for target, expected in EXPECTED.items():
            with self.subTest(target=target):
                self.assertEqual(release.resolve(target), expected)
        self.assertEqual(release.resolve('all'), list(release.PACKAGES), 'all builds every package, in build order')

    def test_prefixes_agree_with_the_operating_system_of_each_package(self):
        for target, expected in EXPECTED.items():
            for name in expected:
                self.assertTrue(target == 'all' or name.startswith(target.split('-')[0]), (target, name))

    def test_unknown_values_are_rejected(self):
        for value in ('', 'All', 'windows', 'linux', 'windows-linux', 'windows-all ', 'docker', 'Windows Desktop', None):
            with self.subTest(value=value), self.assertRaises(release.DeliveryError):
                release.resolve(value)

    def test_the_returned_list_cannot_alter_the_table(self):
        release.resolve('all').clear()
        self.assertEqual(release.resolve('all'), list(release.PACKAGES))


class PlanningJobTests(unittest.TestCase):
    def test_the_plan_exposes_each_job_flag_once_and_a_summary(self):
        for target, expected in EXPECTED.items():
            done, values, summary = run_plan(target, BASE_VERSION='0.1.0', DEPLOYMENT_CHANNEL='Beta', PUBLISH_RELEASE='false')
            with self.subTest(target=target):
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(values['packages'].split(','), expected); self.assertEqual(values['count'], str(len(expected)))
                for name, (key, label, *_rest) in release.PACKAGES.items():
                    self.assertEqual(values[key], 'true' if name in expected else 'false')
                    row = next(line for line in summary.splitlines() if line.startswith(f'| {label} '))
                    self.assertIn('Selected' if name in expected else 'Not selected', row)
                self.assertIn(f'Build target: `{target}`', summary)
                self.assertIn('Resolved packages: ' + ', '.join(f'`{name}`' for name in expected), summary)
                self.assertIn(f'{len(expected)} of 4 packages selected', summary); self.assertIn('Build only', summary)

    def test_an_unknown_target_stops_the_run_with_a_clear_message_and_selects_nothing(self):
        done, values, summary = run_plan('windows')
        self.assertEqual(done.returncode, 1)
        self.assertIn('::error::Build selection rejected', done.stderr); self.assertIn('Choose one of: all, windows-all', done.stderr)
        self.assertEqual(values, {}, 'a rejected plan selects nothing')
        self.assertIn('Build selection rejected', summary); self.assertIn('No package was built or published', summary)

    def test_the_summary_states_when_publication_is_enabled(self):
        done, values, summary = run_plan('linux-all', PUBLISH_RELEASE='true')
        self.assertEqual(done.returncode, 0); self.assertIn('only the selected packages that pass verification are published', summary)

    def test_the_publisher_accepts_only_the_planned_list_of_the_same_target(self):
        for target, expected in EXPECTED.items():
            self.assertEqual(release.planned(dict(DEPLOYMENT_TARGET=target, DEPLOYMENT_PACKAGES=','.join(expected))), expected)
        for planned_value in ('', 'windows-desktop', 'linux-docker,linux-native,windows-desktop', 'windows-service,windows-desktop'):
            with self.subTest(planned=planned_value), self.assertRaises(release.DeliveryError):
                release.planned(dict(DEPLOYMENT_TARGET='all', DEPLOYMENT_PACKAGES=planned_value))
        with self.assertRaises(release.DeliveryError):
            release.planned(dict(DEPLOYMENT_TARGET='windows-all', DEPLOYMENT_PACKAGES='linux-docker'))

    def test_the_shared_validation_rejects_an_unknown_target_too(self):
        env = dict(GITHUB_ACTIONS='true', GITHUB_RUN_ID='1', GITHUB_RUN_NUMBER='1', GITHUB_RUN_ATTEMPT='1', DEPLOYMENT_TARGET='windows-linux',
                   DEPLOYMENT_CHANNEL='Beta', DEPLOYMENT_SEQUENCE='1', PUBLISH_RELEASE='false')
        with patch.dict(os.environ, env, clear=True), patch.object(packages, 'write') as write, self.assertRaises(ValueError):
            packages.prepare('0.1.0')
        write.assert_not_called()


class WorkflowWiringTests(unittest.TestCase):
    """What GitHub would run for each selection, derived from the workflow file itself (nothing is dispatched)."""
    def workflow(self):
        return contracts.load_workflows()['build-deployments.yml']

    def test_selection_is_decided_by_the_plan_alone_and_validation_waits_for_it(self):
        workflow = self.workflow(); jobs = workflow['jobs']
        inputs = workflow['on']['workflow_dispatch']['inputs']
        self.assertEqual(set(inputs) & {'platform', 'operating_system', 'package'}, set())
        self.assertEqual(inputs['build_target']['options'], list(release.BUILD_TARGETS), 'exactly one build-selection dropdown with the planner\'s seven values')
        self.assertEqual(inputs['build_target']['default'], 'all')
        self.assertEqual([name for name, value in inputs.items() if value.get('type') == 'choice'], ['build_target', 'release_channel'], 'the only other dropdown is the version channel')
        self.assertEqual(jobs['plan'].get('needs'), None, 'the planning job starts first')
        self.assertEqual(jobs['validation']['needs'], 'plan', 'an invalid selection stops before the shared validation')
        for name, (key, *_rest) in release.PACKAGES.items():
            job = jobs[key]
            self.assertEqual(job['needs'], ['plan', 'validation'])
            self.assertEqual(job['if'], f"${{{{ needs.plan.outputs.{key} == 'true' }}}}", name)
            self.assertNotIn('inputs.', job['if'])

    def test_each_selection_starts_exactly_the_selected_runners(self):
        jobs = self.workflow()['jobs']
        runners = {'desktop': 'windows-latest', 'service': 'windows-latest', 'docker': 'ubuntu-22.04', 'native': 'ubuntu-22.04'}
        for target, expected in EXPECTED.items():
            _, outputs, _ = run_plan(target)
            started = [key for key in runners if re.fullmatch(r"\$\{\{ needs\.plan\.outputs\.(\w+) == 'true' \}\}", jobs[key]['if']) and outputs[re.search(r'outputs\.(\w+)', jobs[key]['if']).group(1)] == 'true']
            self.assertEqual(sorted(started), sorted(release.PACKAGES[name][0] for name in expected), target)
            for key in started:
                self.assertEqual(jobs[key]['runs-on'], runners[key])
            if target.startswith('linux'):
                self.assertFalse([key for key in started if jobs[key]['runs-on'].startswith('windows')], 'no Windows runner for a Linux selection')
            if target.startswith('windows'):
                self.assertFalse([key for key in started if jobs[key]['runs-on'].startswith('ubuntu')], 'no Linux package runner for a Windows selection')

    def test_publication_collects_only_planned_packages_and_artifact_names_are_unchanged(self):
        jobs = self.workflow()['jobs']; publish = jobs['publish']
        self.assertEqual(set(publish['needs']), {'plan', 'validation', 'desktop', 'service', 'docker', 'native'})
        self.assertIn("needs.plan.result == 'success'", publish['if'])
        self.assertEqual(publish['env']['DEPLOYMENT_PACKAGES'], '${{ needs.plan.outputs.packages }}')
        names = {key: next(step['with']['name'] for step in jobs[key]['steps'] if step.get('id') == 'distribution') for key in ('desktop', 'service', 'docker', 'native')}
        self.assertEqual(names, {'desktop': 'SAP-Lens-Windows-Desktop-x64-${{ needs.validation.outputs.version }}', 'service': 'SAP-Lens-Windows-Service-x64-${{ needs.validation.outputs.version }}',
                                 'docker': 'SAP-Lens-Linux-Docker-amd64-${{ needs.validation.outputs.version }}', 'native': 'SAP-Lens-Linux-Native-x64-${{ needs.validation.outputs.version }}'})
        for name, (_key, _label, stem, *_rest) in release.PACKAGES.items():
            self.assertIn(stem, next(value for value in names.values() if stem in value), name)


class PublicationGatingTests(unittest.TestCase):
    def needs_for(self, chosen):
        from version import make_deployment_info
        info = make_deployment_info('0.1.0', 'beta', '1', 'a' * 40, '123', '12', 1)
        data = {'plan': {'result': 'success'}, 'validation': {'result': 'success'}}
        for index, (name, (key, _label, stem, ext, *_rest)) in enumerate(release.PACKAGES.items(), 1):
            data[key] = ({'result': 'success', 'outputs': {'artifact_id': str(index), 'package_name': f'SAP-Lens-{stem}-{info["version"]}{ext}', 'package_sha': 'f' * 64}}
                         if name in chosen else {'result': 'skipped', 'outputs': {}})
        return info, data

    def test_each_selection_publishes_only_its_verified_packages(self):
        for target, expected in EXPECTED.items():
            info, data = self.needs_for(expected)
            rows = release.eligible(info, release.resolve(target), data)
            self.assertEqual(len(rows), len(expected), target)
            self.assertTrue(all(row['package_name'].startswith('SAP-Lens-') for row in rows))
            for name in expected:  # one selected package failing blocks the whole release, skipped siblings do not
                broken = copy.deepcopy(data); broken[release.PACKAGES[name][0]]['result'] = 'failure'
                with self.subTest(target=target, failing=name), self.assertRaises(release.DeliveryError):
                    release.eligible(info, release.resolve(target), broken)

    def test_an_artifact_from_a_package_nobody_selected_cannot_ride_along(self):
        info, data = self.needs_for([WD, WS])
        data['docker'] = {'result': 'success', 'outputs': {'artifact_id': '9', 'package_name': f'SAP-Lens-Linux-Docker-amd64-{info["version"]}.tar.gz', 'package_sha': 'e' * 64}}
        with self.assertRaises(release.DeliveryError):
            release.eligible(info, release.resolve('windows-all'), data)


if __name__ == '__main__':
    unittest.main()
