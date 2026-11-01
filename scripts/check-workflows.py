"""Offline workflow trigger, dependency, security and integrity contracts.

actionlint supplies the independent GitHub schema/expression/shell validation.
"""
from fnmatch import fnmatchcase
from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {'validate.yml': 'Fast Validation', 'full-validation.yml': 'Full Validation',
            'build-windows.yml': 'Build Windows Application', 'build-deployments.yml':'Build Deployment Packages'}


class UniqueLoader(yaml.BaseLoader):
    pass


def mapping(loader, node):
    result = {}
    for key, value in node.value:
        key = loader.construct_object(key)
        if key in result:
            raise ValueError('Duplicate workflow YAML key')
        result[key] = loader.construct_object(value)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def load_workflows(directory=ROOT / '.github/workflows'):
    return {path.name: yaml.load(path.read_text(encoding='utf-8'), Loader=UniqueLoader)  # noqa: S506 (UniqueLoader extends BaseLoader: scalars stay strings, nothing is instantiated)
            for path in directory.iterdir() if path.suffix in {'.yml', '.yaml'}}


def triggered(workflow, event, branch=''):
    events = workflow['on']
    if event not in events:
        return False
    options = events[event] or {}
    branches = options.get('branches')
    return branches is None or any(fnmatchcase(branch, pattern) for pattern in branches)


def validate_graph(jobs):
    visiting, visited = set(), set()

    def visit(name):
        if name in visiting or name not in jobs:
            raise ValueError('Cyclic or missing job dependency')
        if name in visited:
            return
        visiting.add(name)
        needs = jobs[name].get('needs', [])
        for dependency in [needs] if isinstance(needs, str) else needs:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)
    for name in jobs:
        visit(name)


def validate(workflows):
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    require(set(workflows) == set(EXPECTED), 'Exactly four approved workflows are required')
    for filename, name in EXPECTED.items():
        workflow = workflows[filename]
        require(workflow['name'] == name, 'Workflow display name changed')
        permissions = {'contents': 'read', **({'actions': 'read'} if filename == 'build-windows.yml' else {})}
        require(workflow.get('permissions') == permissions, 'Unexpected token permissions')
        validate_graph(workflow['jobs'])
        for job in workflow['jobs'].values():
            require(bool(job.get('name')), 'Job needs a descriptive display name')
            publisher = filename == 'build-windows.yml' and job is workflow['jobs'].get('publish-release')
            deployment_publisher = filename == 'build-deployments.yml' and job is workflow['jobs'].get('publish')
            require('continue-on-error' not in job, 'Job overrides failure policy')
            allocator = filename == 'build-windows.yml' and job is workflow['jobs'].get('reserve-version')
            require(job.get('permissions') == {'contents': 'write', 'actions': 'read'} if publisher else job.get('permissions') == {'contents':'write'} if allocator or deployment_publisher else 'permissions' not in job, 'Unexpected job permissions')
            require(1 <= int(job.get('timeout-minutes', 0)) <= 25, 'Missing or excessive timeout')
            for step in job['steps']:
                require(bool(step.get('name')), 'Step needs a descriptive name')
                require('continue-on-error' not in step, 'Check failure may not be waived')
                if 'uses' in step:
                    require(bool(re.fullmatch(r'actions/[a-z-]+@[0-9a-f]{40}', step['uses'])), 'Actions must be official and SHA-pinned')
                if step.get('uses', '').startswith('actions/checkout@'):
                    require(step.get('with', {}).get('persist-credentials') == 'false', 'Checkout must not persist credentials')
                require('${{ secrets.' not in str(step), 'Validation must not require repository secrets')
    fast, full, windows = (workflows[n] for n in ('validate.yml','full-validation.yml','build-windows.yml'))
    deployment=workflows['build-deployments.yml']
    require(set(deployment['on'])=={'workflow_dispatch'}, 'Deployment packaging must be manual-only')
    require(deployment['concurrency']['cancel-in-progress']=='false' and 'github.ref' in deployment['concurrency']['group'], 'Deployment runs must not cancel active builds')
    selection=deployment['on']['workflow_dispatch']['inputs']
    require({'platform','operating_system','package'}.isdisjoint(selection), 'Build selection is one build_target dropdown')
    require(selection['build_target']['type']=='choice' and selection['build_target']['default']=='all' and
            selection['build_target']['options']==['all','windows-all','windows-desktop','windows-service','linux-all','linux-docker','linux-native'], 'Build target choices changed')
    inputs=deployment['on']['workflow_dispatch']['inputs']
    require(inputs['release_channel']['options']==['Alpha','Beta','Release Candidate (RC)','Stable / Production'], 'Deployment channel options changed')
    require(inputs['publish_release']['type']=='boolean' and inputs['publish_release']['default']=='false', 'Publication must be explicit and off by default')
    require(set(deployment['jobs'])=={'plan','validation','desktop','service','docker','native','publish'}, 'Deployment job architecture changed')
    plan=deployment['jobs']['plan']
    plan_commands='\n'.join(step.get('run','') for step in plan['steps'])
    require('needs' not in plan and plan['runs-on']=='ubuntu-22.04' and int(plan['timeout-minutes'])<=5, 'Selection must be resolved first by a lightweight job')
    require('deployment-release.py plan' in plan_commands and 'pip install' not in plan_commands and 'npm' not in plan_commands, 'The planning job may only run the stdlib planner')
    require(set(plan['outputs'])=={'packages','desktop','service','docker','native'}, 'The plan must expose the resolved packages once')
    require(deployment['jobs']['validation']['needs']=='plan', 'Expensive validation may only start after a valid selection')
    require(plan['env']['DEPLOYMENT_TARGET']=='${{ inputs.build_target }}', 'The plan resolves exactly the dispatched build target')
    for key in ('desktop','service','docker','native'):
        job=deployment['jobs'][key]
        require(job['needs']==['plan','validation'], 'Platform jobs must depend only on the selection and shared validation')
        require(job['if']==f"${{{{ needs.plan.outputs.{key} == 'true' }}}}", 'A platform job runs only when the plan selected it')
        commands='\n'.join(s.get('run','') for s in job['steps'])
        require('deployment-package.py consume' in commands and 'check-deployment-download.py --directory' in commands, 'Attestation and distribution roundtrip are mandatory')
        require(job['outputs']=={'artifact_id':'${{ steps.distribution.outputs.artifact-id }}','package_name':'${{ steps.integrity.outputs.package_name }}','package_sha':'${{ steps.integrity.outputs.package_sha }}'}, 'Publication must use roundtrip-verified outputs')
        integrity=next((s for s in job['steps'] if s.get('id')=='integrity'),{})
        require('if' not in integrity and 'check-deployment-download.py --directory' in integrity.get('run',''), 'Integrity verification cannot be skipped')
    require(deployment['jobs']['desktop']['env'].get('SAP_LENS_EXPECTED_BUILD_JSON')=='${{ needs.validation.outputs.identity }}', 'Desktop verification requires the shared resolved build identity')
    native_steps=deployment['jobs']['native']['steps']
    audit_steps=[i for i,step in enumerate(native_steps) if step.get('run')=='python -m pip install -r scripts/requirements-audit.txt']
    smoke_steps=[i for i,step in enumerate(native_steps) if 'test-native-deployment.py' in step.get('run','')]
    require(len(audit_steps)==len(smoke_steps)==1 and audit_steps[0]<smoke_steps[0] and 'if' not in native_steps[audit_steps[0]], 'Native package auditing must be provisioned before the mandatory smoke test')
    deployment_publish=deployment['jobs']['publish']
    require(set(deployment_publish['needs'])=={'plan','validation','desktop','service','docker','native'}, 'Publication must await the plan and all platform results')
    require(deployment_publish['if']=="${{ always() && !cancelled() && inputs.publish_release && needs.plan.result == 'success' && needs.validation.result == 'success' }}", 'Publication must be manual, explicit, planned and validated')
    require(deployment_publish['env'].get('DEPLOYMENT_PACKAGES')=='${{ needs.plan.outputs.packages }}' and deployment_publish['env'].get('DEPLOYMENT_TARGET')=='${{ inputs.build_target }}', 'Publication may collect only the planned packages')
    require(deployment_publish['concurrency']=={'group':'sap-lens-deployment-publication','cancel-in-progress':'false'}, 'Publication must be serialized without cancellation')
    require(isinstance(deployment_publish.get('environment'),dict),'Publication must run in a protected environment')
    require(deployment_publish['environment']['name']=="${{ inputs.release_channel == 'Stable / Production' && 'sap-lens-stable' || 'sap-lens-beta' }}", 'Stable release protection must be retained')
    commands=[s.get('run','') for s in deployment_publish['steps']]
    require('python scripts/deployment-release.py preflight' in commands and 'python scripts/deployment-release.py publish --directory dist/publication' in commands, 'Publication eligibility and asset verification are mandatory')
    require(all('if' not in s for s in deployment_publish['steps']), 'Publication safeguards may not be conditionally skipped')
    download=next(s for s in deployment_publish['steps'] if s.get('uses','').startswith('actions/download-artifact@'))
    require(download['with']=={'artifact-ids':'${{ steps.eligible.outputs.artifact_ids }}','path':'dist/publication','merge-multiple':'true','digest-mismatch':'error'}, 'Collect only selected immutable same-run artifacts with strict digests')
    require(deployment_publish['env'].get('DEPLOYMENT_IDENTITY')=='${{ needs.validation.outputs.identity }}' and deployment_publish['env'].get('DEPLOYMENT_NEEDS')=='${{ toJSON(needs) }}' and deployment_publish['env'].get('PUBLISH_RELEASE')=='${{ inputs.publish_release }}', 'Publication context must come from validated job results')
    require(not any(s.get('uses','').startswith('actions/') and 'login' in s.get('uses','') or 'release-windows.py publish' in s.get('run','') or ('deployment-release.py' in s.get('run','') and key!='publish' and not (key=='plan' and s.get('run','').strip()=='python scripts/deployment-release.py plan')) for key,j in deployment['jobs'].items() for s in j['steps']), 'Build jobs may not publish releases or images')
    require(fast['on'] == {'push': {'branches': ['work', 'main']}, 'pull_request': {'branches': ['main']}}, 'Fast runs on pushes to work and main and on pull requests to main')
    require(set(full['on']) == {'workflow_dispatch'}, 'Full Regression is manual only: no push, pull request, schedule or workflow_call trigger')
    require(int(fast['jobs']['fast']['timeout-minutes']) <= 15, 'Fast Validation must stay a short job')
    # Full Regression is evidence, never a prerequisite: nothing that builds or publishes may run the complete suites or consult a regression result.
    for name in ('build-deployments.yml', 'build-windows.yml'):
        text = '\n'.join(str(step) for job in workflows[name]['jobs'].values() for step in job['steps'])
        require('run-tests.py regression' not in text and 'unittest discover' not in text and 'test:browser' not in text and '-Stage Backend' not in text and '-Stage Browser' not in text,
                f'{name} may not run the complete backend or browser suites')
        require(all('workflow_run' not in job.get('if', '') and 'full-validation' not in str(job).lower() for job in workflows[name]['jobs'].values()), f'{name} may not depend on a Full Regression result')
        require('workflow_run' not in workflows[name]['on'] and 'workflow_call' not in workflows[name]['on'], f'{name} is dispatched by hand only')
    for script in ('deployment-release.py', 'release-windows.py', 'deployment-package.py'):
        source = (ROOT / 'scripts' / script).read_text(encoding='utf-8').lower()
        require('full-validation' not in source and 'full validation' not in source and "'backend', 'browser'" not in source, f'{script} may not require a Full Regression result or the complete suites')
    require(not ({'backend', 'browser'} & set(re.findall(r"CHECKS=\{([^}]*)\}", (ROOT / 'scripts/deployment-package.py').read_text(encoding='utf-8'))[0].replace("'", '').split(','))), 'The sealed validation receipt may not require the complete suites')
    require(set(windows['on']) == {'workflow_dispatch'}, 'Windows must be manual-only')
    require(fast['concurrency']['cancel-in-progress'] == 'true' and
            'github.event_name' in fast['concurrency']['group'] and
            'github.event.pull_request.number' in fast['concurrency']['group'], 'Fast push and PR concurrency must be isolated')
    require(full['concurrency']['cancel-in-progress'] == 'false' and 'github.ref' in full['concurrency']['group'], 'A manual Full Regression is never cancelled by another dispatch')
    require(windows['concurrency'] == {'group': 'sap-lens-windows-distribution', 'cancel-in-progress': 'false'}, 'Manual builds must be serialized without cancelling active builds')
    require(set(windows['jobs']) == {'reserve-version', 'windows-exe', 'publish-release'}, 'Keep the complete Windows build together; isolate publication')
    allocator = windows['jobs']['reserve-version']
    require(allocator['if'] == "${{ inputs.release_mode != 'build' }}", 'Build mode may not reserve tags')
    require(allocator['outputs'] == {'metadata':'${{ steps.allocate.outputs.metadata }}'}, 'Reservation must return its fixed identity')
    require(any(s.get('run') == 'python scripts/release-windows.py allocate' and 'if' not in s for s in allocator['steps']), 'Version reservation must precede packaging')
    build = windows['jobs']['windows-exe']
    require(build['needs'] == 'reserve-version' and build['if'] == "${{ !cancelled() && (needs.reserve-version.result == 'success' || (inputs.release_mode == 'build' && needs.reserve-version.result == 'skipped')) }}", 'Windows cannot bypass failed release reservation')
    require(any(s.get('run') == 'python scripts/release-windows.py prepare-build' and s.get('id') == 'build_identity' and s.get('env',{}).get('RELEASE_ALLOCATION_JSON') == '${{ needs.reserve-version.outputs.metadata }}' and 'if' not in s for s in build['steps']), 'Windows must embed the allocated identity')
    publisher = windows['jobs']['publish-release']
    require(publisher['needs'] == 'windows-exe' and publisher['if'] == "${{ needs.windows-exe.result == 'success' && inputs.release_mode != 'build' }}", 'Publication must depend on a successful non-build manual run')
    require(publisher['environment']['name'] == "${{ inputs.release_mode == 'stable' && 'sap-lens-stable' || 'sap-lens-beta' }}", 'Stable and beta publication environments must be isolated')
    require(allocator['environment'] == publisher['environment'], 'Allocation and publication need the same protected environment')
    require(publisher['steps'][-1]['env'].get('BUILD_VERSION_JSON') == '${{ needs.windows-exe.outputs.metadata }}', 'Publication may not allocate a different version')
    inputs = windows['on']['workflow_dispatch']['inputs']
    require(inputs['release_mode'] == {'description': 'Build only, beta prerelease, or stable release', 'type': 'choice', 'options': ['build','beta','stable'], 'default':'build', 'required':'true'}, 'Release mode defaults/options changed')
    require(inputs['version']['type'] == 'string' and inputs['version']['required'] == 'true', 'An explicit base version is required')
    for name in ('benchmark_packaging','cold_cache'):
        require(inputs[name]['type'] == 'boolean' and inputs[name]['default'] == 'false', 'Benchmark defaults changed')
    publication_download = next(s for s in publisher['steps'] if s.get('uses','').startswith('actions/download-artifact@'))
    require(publication_download['with'].get('artifact-ids') == '${{ needs.windows-exe.outputs.artifact_id }}' and publication_download['with'].get('digest-mismatch') == 'error' and publication_download['with'].get('skip-decompress') == 'true', 'Publication must revalidate the exact raw build artifact')
    steps = windows['jobs']['windows-exe']['steps']
    commands = [s.get('run', '') for s in steps]
    for stage in ('Environment', 'Frontend', 'Python', 'Audit', 'JavaScriptAudit', 'Package', 'Verify', 'Smoke', 'Artifact'):
        matches = [i for i, command in enumerate(commands) if re.search(r'-Stage '+stage+r'\b', command)]
        require(len(matches) == 1, 'Each canonical Windows stage must run exactly once')
        require('if' not in steps[matches[0]], 'Windows validation stages cannot be conditionally skipped')
    require(any(s.get('run') == 'python scripts/release-windows.py validate-inputs' and 'if' not in s for s in steps), 'Manual version preflight is mandatory')
    require(windows['jobs']['windows-exe']['outputs'] == {'metadata':'${{ steps.build_identity.outputs.metadata }}', 'artifact_id': '${{ steps.executable.outputs.artifact-id }}', 'artifact_digest': '${{ steps.executable.outputs.artifact-digest }}'}, 'Release must consume only this verified artifact')
    upload = next(s for s in steps if s.get('id') == 'executable')
    require(upload['with']['path'].split() == ['backend/dist/SAP-Lens.exe', 'backend/dist/SAP-Lens.exe.sha256'], 'Unexpected distribution upload')
    require(upload['with']['name'] == 'SAP-Lens-Windows-x64' and upload['with']['retention-days'] == '14', 'Distribution identity or retention changed')
    download = next(s for s in steps if s.get('uses', '').startswith('actions/download-artifact@'))
    require(download['with']['artifact-ids'] == '${{ steps.executable.outputs.artifact-id }}', 'Download must use this upload ID')
    require(download['with'].get('digest-mismatch') == 'error', 'ZIP digest mismatch must fail')
    require(download['with'].get('skip-decompress') == 'true', 'Raw ZIP must be checked before extraction')
    artifact_command = next(command for command in commands if '-Stage Artifact ' in command)
    require('-ArtifactDownloadDirectory' in artifact_command and '-ArtifactDigest' in artifact_command, 'Raw ZIP verification inputs are mandatory')
    for workflow in (fast, full):
        steps = {step['id'] for job in workflow['jobs'].values() for step in job['steps'] if 'id' in step}
        require({'ruff', 'eslint'} <= steps, 'Both workflows must lint Python with Ruff and the frontend with ESLint')
        for job in workflow['jobs'].values():
            require(job['steps'][-1].get('if') == 'always()', 'Validation report must run after failures')
            identifiers = {step['id']: step for step in job['steps'] if 'id' in step}
            report = job['steps'][-1]['env']
            mandatory, optional = report['CI_REQUIRED'].split(), report.get('CI_OPTIONAL', '').split()
            require(not set(mandatory) & set(optional) and set(mandatory) | set(optional) == set(identifiers), 'Every validation/setup step must be represented in the report')
            require(all('if' not in identifiers[key] for key in mandatory), 'Mandatory validation cannot be skipped')
            # Optional steps are the change-selected frontend and browser steps: each is gated only by the plan of the same job.
            require(all(re.fullmatch(r"\$\{\{ steps\.plan\.outputs\.(frontend|browser) == 'true' \}\}", identifiers[key].get('if', '')) for key in optional), 'Optional steps may only depend on the change plan')


if __name__ == '__main__':
    try:
        validate(load_workflows())
    except (ValueError, KeyError, TypeError, yaml.YAMLError):
        sys.exit('Workflow contract validation failed; run backend/tests/test_workflows.py for details.')
    print('Workflow triggers, permissions, concurrency, job graph and artifact contracts passed.')
