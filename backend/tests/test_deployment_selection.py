"""Build selection of the manual deployment workflow: operating system and package are resolved once by a planning job, incompatible pairs fail
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
EXPECTED = {  # (operating system, package) -> packages built, or None when the pair is rejected before any job starts
    ('all', 'all'): [WD, WS, LD, LN], ('windows', 'all'): [WD, WS], ('linux', 'all'): [LD, LN],
    ('all', WD): [WD], ('all', WS): [WS], ('all', LD): [LD], ('all', LN): [LN],
    ('windows', WD): [WD], ('windows', WS): [WS], ('linux', LD): [LD], ('linux', LN): [LN],
    ('windows', LD): None, ('windows', LN): None, ('linux', WD): None, ('linux', WS): None,
}


def run_plan(operating_system, package, **extra):
    with tempfile.TemporaryDirectory() as directory:
        output, summary = Path(directory, 'output'), Path(directory, 'summary.md')
        env = dict(DEPLOYMENT_OS=operating_system, DEPLOYMENT_PACKAGE=package, GITHUB_OUTPUT=str(output), GITHUB_STEP_SUMMARY=str(summary), **extra)
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/deployment-release.py'), 'plan'], env={**os.environ, **env}, capture_output=True, text=True)
        values = dict(line.split('=', 1) for line in output.read_text().splitlines()) if output.exists() else {}
        return done, values, summary.read_text() if summary.exists() else ''


class SelectionMatrixTests(unittest.TestCase):
    def test_every_combination_resolves_or_is_rejected_as_documented(self):
        pairs = [(o, p) for o in release.OPERATING_SYSTEMS for p in ['all', *release.PACKAGES]]
        self.assertEqual(sorted(pairs), sorted(EXPECTED), 'the matrix covers every combination of the two inputs')
        for pair, expected in EXPECTED.items():
            with self.subTest(pair=pair):
                if expected is None:
                    with self.assertRaises(release.DeliveryError) as refused:
                        release.resolve(*pair)
                    message = str(refused.exception)
                    self.assertIn(pair[1], message); self.assertIn(pair[0], message); self.assertIn("Choose operating system 'all'", message)
                else:
                    self.assertEqual(release.resolve(*pair), expected)

    def test_unknown_values_are_rejected(self):
        for pair in (('macos', 'all'), ('', 'all'), ('All', 'all'), ('all', 'Windows Desktop'), ('all', ''), ('all', 'windows')):
            with self.subTest(pair=pair), self.assertRaises(release.DeliveryError):
                release.resolve(*pair)


class PlanningJobTests(unittest.TestCase):
    def test_the_plan_exposes_each_job_flag_once_and_a_summary(self):
        for pair, expected in EXPECTED.items():
            done, values, summary = run_plan(*pair, BASE_VERSION='0.1.0', DEPLOYMENT_CHANNEL='Beta', PUBLISH_RELEASE='false')
            with self.subTest(pair=pair):
                if expected is None:
                    self.assertEqual(done.returncode, 1)
                    self.assertIn('::error::Build selection rejected', done.stderr)
                    self.assertEqual(values, {}, 'a rejected plan selects nothing')
                    self.assertIn('Build selection rejected', summary); self.assertIn('No package was built or published', summary)
                    continue
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(values['packages'].split(','), expected); self.assertEqual(values['count'], str(len(expected)))
                for name, (key, label, *_rest) in release.PACKAGES.items():
                    self.assertEqual(values[key], 'true' if name in expected else 'false')
                    row = next(line for line in summary.splitlines() if line.startswith(f'| {label} '))
                    self.assertIn('Selected' if name in expected else 'Not selected', row)
                self.assertIn(f'Operating system: `{pair[0]}` | Package: `{pair[1]}`', summary)
                self.assertIn(f'{len(expected)} of 4 packages selected', summary); self.assertIn('Build only', summary)

    def test_the_summary_states_when_publication_is_enabled(self):
        done, values, summary = run_plan('linux', 'all', PUBLISH_RELEASE='true')
        self.assertEqual(done.returncode, 0); self.assertIn('only the selected packages that pass verification are published', summary)

    def test_the_publisher_accepts_only_the_planned_list_of_the_same_inputs(self):
        for pair, expected in EXPECTED.items():
            if expected is None:
                continue
            env = dict(DEPLOYMENT_OS=pair[0], DEPLOYMENT_PACKAGE=pair[1], DEPLOYMENT_PACKAGES=','.join(expected))
            self.assertEqual(release.planned(env), expected)
        for packages_value in ('', 'windows-desktop', 'linux-docker,linux-native,windows-desktop', 'windows-service,windows-desktop'):
            with self.subTest(planned=packages_value), self.assertRaises(release.DeliveryError):
                release.planned(dict(DEPLOYMENT_OS='all', DEPLOYMENT_PACKAGE='all', DEPLOYMENT_PACKAGES=packages_value))
        with self.assertRaises(release.DeliveryError):
            release.planned(dict(DEPLOYMENT_OS='windows', DEPLOYMENT_PACKAGE='linux-docker', DEPLOYMENT_PACKAGES='linux-docker'))

    def test_the_shared_validation_rejects_an_incompatible_selection_too(self):
        env = dict(GITHUB_ACTIONS='true', GITHUB_RUN_ID='1', GITHUB_RUN_NUMBER='1', GITHUB_RUN_ATTEMPT='1', DEPLOYMENT_OS='linux', DEPLOYMENT_PACKAGE=WD,
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
        self.assertEqual(set(workflow['on']['workflow_dispatch']['inputs']) & {'platform'}, set())
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
        for pair, expected in EXPECTED.items():
            if expected is None:
                continue
            _, outputs, _ = run_plan(*pair)
            started = [key for key in runners if re.fullmatch(r"\$\{\{ needs\.plan\.outputs\.(\w+) == 'true' \}\}", jobs[key]['if']) and outputs[re.search(r'outputs\.(\w+)', jobs[key]['if']).group(1)] == 'true']
            self.assertEqual(sorted(started), sorted(release.PACKAGES[name][0] for name in expected), pair)
            for key in started:
                self.assertEqual(jobs[key]['runs-on'], runners[key])
            if pair[0] == 'linux':
                self.assertFalse([key for key in started if jobs[key]['runs-on'].startswith('windows')], 'no Windows runner for a Linux selection')
            if pair[0] == 'windows':
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
        for pair, expected in EXPECTED.items():
            if expected is None:
                continue
            info, data = self.needs_for(expected)
            rows = release.eligible(info, release.resolve(*pair), data)
            self.assertEqual(len(rows), len(expected), pair)
            self.assertTrue(all(row['package_name'].startswith('SAP-Lens-') for row in rows))
            for name in expected:  # one selected package failing blocks the whole release, skipped siblings do not
                broken = copy.deepcopy(data); broken[release.PACKAGES[name][0]]['result'] = 'failure'
                with self.subTest(pair=pair, failing=name), self.assertRaises(release.DeliveryError):
                    release.eligible(info, release.resolve(*pair), broken)

    def test_an_artifact_from_a_package_nobody_selected_cannot_ride_along(self):
        info, data = self.needs_for([WD, WS])
        data['docker'] = {'result': 'success', 'outputs': {'artifact_id': '9', 'package_name': f'SAP-Lens-Linux-Docker-amd64-{info["version"]}.tar.gz', 'package_sha': 'e' * 64}}
        with self.assertRaises(release.DeliveryError):
            release.eligible(info, release.resolve('windows', 'all'), data)


if __name__ == '__main__':
    unittest.main()
