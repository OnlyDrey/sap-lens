"""Fail-closed active CI trigger, permissions and .NET structure contracts. No API calls."""
from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT):
    workflows = sorted((root / '.github/workflows').glob('*.y*ml'))
    assert [p.name for p in workflows] == ['validate.yml'], 'Only the main-push validation workflow may be active'
    data = yaml.load(workflows[0].read_text(), Loader=yaml.BaseLoader)  # noqa: S506 BaseLoader builds only str/list/dict (keeps the key 'on' a string)
    assert data['on'] == {'push': {'branches': ['main']}}, 'CI must run only on push to main'
    assert data['permissions'] == {'contents': 'read'}, 'CI must not publish or deploy'
    assert set(data['jobs']) == {'frontend', 'backend', 'browser'}
    for name, job in data['jobs'].items():
        assert 'timeout-minutes' in job, f'{name}: bounded job required'
        assert not {'permissions', 'environment', 'secrets'} & job.keys(), f'{name}: unexpected privileged job'
        for step in job['steps']:
            if action := step.get('uses'):
                assert re.fullmatch(r'actions/[a-z-]+@[a-f0-9]{40}', action), f'Unpinned action: {action}'
            command = step.get('run', '')
            assert not re.search(r'legacy/v1|scripts/build\.py|requirements-dev\.txt|workflow_dispatch|gh release|docker push', command), f'{name}: obsolete or publishing command'
    print('Workflow YAML, main-only triggers, pinned actions, read-only permissions and .NET job contracts passed.')


if __name__ == '__main__':
    check()
