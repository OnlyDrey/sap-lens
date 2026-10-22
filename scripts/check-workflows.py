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
            'build-windows.yml': 'Build Windows Application'}


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
    return {path.name: yaml.load(path.read_text(encoding='utf-8'), Loader=UniqueLoader)
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

    require(set(workflows) == set(EXPECTED), 'Exactly three primary workflows are required')
    for filename, name in EXPECTED.items():
        workflow = workflows[filename]
        require(workflow['name'] == name, 'Workflow display name changed')
        permissions = {'contents': 'read', **({'actions': 'read'} if filename == 'build-windows.yml' else {})}
        require(workflow.get('permissions') == permissions, 'Unexpected token permissions')
        validate_graph(workflow['jobs'])
        for job in workflow['jobs'].values():
            require(bool(job.get('name')), 'Job needs a descriptive display name')
            publisher = filename == 'build-windows.yml' and job is workflow['jobs'].get('publish-release')
            require('continue-on-error' not in job, 'Job overrides failure policy')
            allocator = filename == 'build-windows.yml' and job is workflow['jobs'].get('reserve-version')
            require(job.get('permissions') == {'contents': 'write', 'actions': 'read'} if publisher else job.get('permissions') == {'contents':'write'} if allocator else 'permissions' not in job, 'Unexpected job permissions')
            require(1 <= int(job.get('timeout-minutes', 0)) <= 25, 'Missing or excessive timeout')
            for step in job['steps']:
                require(bool(step.get('name')), 'Step needs a descriptive name')
                require('continue-on-error' not in step, 'Check failure may not be waived')
                if 'uses' in step:
                    require(bool(re.fullmatch(r'actions/[a-z-]+@[0-9a-f]{40}', step['uses'])), 'Actions must be official and SHA-pinned')
                if step.get('uses', '').startswith('actions/checkout@'):
                    require(step.get('with', {}).get('persist-credentials') == 'false', 'Checkout must not persist credentials')
                require('${{ secrets.' not in str(step), 'Validation must not require repository secrets')
    fast, full, windows = (workflows[n] for n in EXPECTED)
    require(fast['on'] == {'push': '', 'pull_request': ''}, 'Fast must run on every push and PR without filters')
    require(full['on'] == {'pull_request': {'branches': ['main']}}, 'Full must run only on PRs targeting main')
    require(set(windows['on']) == {'workflow_dispatch'}, 'Windows must be manual-only')
    require(fast['concurrency']['cancel-in-progress'] == 'true' and
            'github.event_name' in fast['concurrency']['group'] and
            'github.event.pull_request.number' in fast['concurrency']['group'], 'Fast push and PR concurrency must be isolated')
    require(full['concurrency']['cancel-in-progress'] == 'true' and
            'github.event.pull_request.number' in full['concurrency']['group'], 'Full concurrency must be per PR')
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
    for stage in ('Environment', 'Frontend', 'Python', 'Audit', 'Backend', 'Browser', 'Package', 'Verify', 'Smoke', 'Artifact'):
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
        for job in workflow['jobs'].values():
            require(job['steps'][-1].get('if') == 'always()', 'Validation report must run after failures')
            identifiers = {step['id']: step for step in job['steps'] if 'id' in step}
            mandatory = job['steps'][-1]['env']['CI_REQUIRED'].split()
            require(set(mandatory) == set(identifiers), 'Every validation/setup step must be represented in the report')
            require(all('if' not in step for step in identifiers.values()), 'Mandatory validation cannot be skipped')


if __name__ == '__main__':
    try:
        validate(load_workflows())
    except (ValueError, KeyError, TypeError, yaml.YAMLError):
        sys.exit('Workflow contract validation failed; run backend/tests/test_workflows.py for details.')
    print('Workflow triggers, permissions, concurrency, job graph and artifact contracts passed.')
