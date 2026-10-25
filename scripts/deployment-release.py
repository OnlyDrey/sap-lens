"""Explicit, same-run deployment publication. Importing this module performs no I/O.

Packages are collected only from successful selected jobs. Upload to a draft
first; create an owned annotated tag only after every asset is verified. Failure
cleanup may remove only this invocation's draft/tag, never a pre-existing ref.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from version import deployment_version, parse_build_info

CHANNELS = {'Alpha': 'alpha', 'Beta': 'beta', 'Release Candidate (RC)': 'rc',
            'Stable / Production': 'stable'}
class DeliveryError(RuntimeError):
    """Bounded operational message safe for workflow logs."""


TARGETS = {'Windows Desktop': ('desktop', 'Windows-Desktop-x64', '.zip'),
           'Windows Server Service': ('service', 'Windows-Service-x64', '.zip'),
           'Linux Docker': ('docker', 'Linux-Docker-amd64', '.tar.gz'),
           'Linux Native/systemd': ('native', 'Linux-Native-x64', '.tar.gz')}


def selected(platform):
    if platform == 'All':
        return list(TARGETS.values())
    if platform not in TARGETS:
        raise DeliveryError('Invalid deployment platform.')
    return [TARGETS[platform]]


def channel(value):
    if value not in CHANNELS:
        raise DeliveryError('Invalid deployment release channel.')
    return CHANNELS[value]


def output(**values):
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            for key, value in values.items():
                stream.write(f'{key}={value}\n')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class GitHub:
    def __init__(self, repository, token):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or not token:
            raise DeliveryError('GitHub repository and scoped workflow token are required.')
        self.repository, self.token = repository, token

    def request(self, method, path, payload=None, asset=None):
        base = 'https://uploads.github.com' if asset else 'https://api.github.com'
        url = base + '/repos/' + self.repository + path
        headers = {'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                   'X-GitHub-Api-Version': '2022-11-28'}
        data = json.dumps(payload).encode() if payload is not None else None
        headers['Content-Type'] = 'application/json'
        try:
            if asset:
                headers.update({'Content-Type': 'application/octet-stream',
                                'Content-Length': str(asset.stat().st_size)})
                # Stream large Docker archives; do not duplicate them in memory.
                with asset.open('rb') as stream:
                    with urlopen(Request(url, data=stream, headers=headers, method=method), timeout=300) as response:
                        return json.load(response)
            with urlopen(Request(url, data=data, headers=headers, method=method), timeout=45) as response:
                body = response.read()
                return json.loads(body) if body else None
        except HTTPError as error:
            if method == 'GET' and error.code == 404:
                return None
            # Response bodies/URLs may contain signed credentials; never print them.
            raise DeliveryError(f'GitHub {method} failed (HTTP {error.code}).') from None

    def available(self, tag):
        if self.request('GET', '/git/ref/tags/' + quote(tag, safe='')) is not None:
            raise DeliveryError('Version tag already exists; choose a new version. Nothing was overwritten.')
        if self.request('GET', '/releases/tags/' + quote(tag, safe='')) is not None:
            raise DeliveryError('Version release already exists; choose a new version. Nothing was overwritten.')


def context():
    info = parse_build_info(json.loads(os.environ['DEPLOYMENT_IDENTITY']))
    if (info['schema'] != 2 or os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or info['source_sha'] != os.environ.get('GITHUB_SHA')
            or info['run_id'] != os.environ.get('GITHUB_RUN_ID')
            or info['run_number'] != os.environ.get('GITHUB_RUN_NUMBER')
            or info['attempt'] != int(os.environ.get('GITHUB_RUN_ATTEMPT', '0'))):
        raise DeliveryError('Publication requires this workflow commit, run and attempt.')
    return info


def eligible(info, platform, needs):
    """All chosen jobs must have completed roundtrip verification, not merely upload."""
    if needs.get('validation', {}).get('result') != 'success':
        raise DeliveryError('Shared validation did not succeed.')
    rows = []
    for key, stem, extension in selected(platform):
        job = needs.get(key, {})
        values = job.get('outputs', {})
        expected = f'SAP-Lens-{stem}-{info["version"]}{extension}'
        if job.get('result') != 'success':
            raise DeliveryError(f'Selected platform {key} did not succeed; publication is forbidden.')
        if (values.get('package_name') != expected
                or not re.fullmatch(r'[0-9a-f]{64}', values.get('package_sha', ''))
                or not re.fullmatch(r'[1-9][0-9]*', values.get('artifact_id', ''))):
            raise DeliveryError('Missing or inconsistent verified platform outputs.')
        rows.append(values)
    if len({row['artifact_id'] for row in rows}) != len(rows):
        raise DeliveryError('Platform artifacts must be distinct.')
    return rows


def collect(directory, info, rows):
    expected = {name for row in rows for name in (row['package_name'], row['package_name'] + '.sha256')}
    entries = list(directory.iterdir())
    if {path.name for path in entries} != expected or any(path.is_symlink() or not path.is_file() for path in entries):
        raise DeliveryError('Release collection contains missing or unexpected assets.')
    assets = []
    for row in rows:
        path = directory / row['package_name']
        checksum = path.with_name(path.name + '.sha256')
        if checksum.stat().st_size > 1024:
            raise DeliveryError('Invalid distributed checksum file.')
        if (sha(path) != row['package_sha']
                or checksum.read_text(encoding='ascii').strip() != row['package_sha'] + '  ' + path.name):
            raise DeliveryError('Collected package differs from the verified platform artifact.')
        assets.extend((path, checksum))
    manifest = directory / f'SAP-Lens-Deployment-Manifest-{info["version"]}.json'
    manifest.write_text(json.dumps(dict(schema=1, identity=info,
        assets={path.name: dict(sha256=sha(path), size=path.stat().st_size) for path in assets}), indent=2) + '\n')
    return [*assets, manifest]


def verify_asset(value, path):
    if (not isinstance(value, dict) or value.get('name') != path.name
            or value.get('state') != 'uploaded' or value.get('size') != path.stat().st_size
            or value.get('digest') != 'sha256:' + sha(path)):
        raise DeliveryError('GitHub release asset size, state or SHA-256 differs.')


def publish(api, info, assets):
    tag = info['tag']
    api.available(tag)
    marker = f'SAP Lens deployment run {info["run_id"]}, attempt {info["attempt"]}, source {info["source_sha"]}'
    release_id = None
    tag_object = None
    prerelease = info['mode'] != 'stable'

    def published(value):
        return (value and value.get('draft') is False and value.get('tag_name') == tag
                and value.get('prerelease') is prerelease and marker in value.get('body', ''))

    def verify_result(value):
        if not published(value):
            raise DeliveryError('Release publication metadata mismatch.')
        remote = {item['name']: item for item in value.get('assets', [])}
        if set(remote) != {path.name for path in assets}:
            raise DeliveryError('Published release asset set differs.')
        for path in assets:
            verify_asset(remote[path.name], path)
        ref = api.request('GET', '/git/ref/tags/' + quote(tag, safe=''))
        if not ref or ref.get('object', {}).get('sha') != tag_object:
            raise DeliveryError('Published tag does not identify the owned validated source tag.')
        return value

    try:
        print('Publication phase: create unpublished draft')
        draft = api.request('POST', '/releases', dict(tag_name=tag,
            target_commitish=info['source_sha'], name='SAP Lens ' + info['version'],
            body=marker + '\n\nValidated deployment packages. See the attached manifest for source identity and SHA-256 digests.',
            draft=True, prerelease=prerelease))
        release_id = draft['id']
        if draft.get('draft') is not True:
            raise DeliveryError('Expected an unpublished draft release.')
        print('Publication phase: upload and verify every selected package')
        for path in assets:
            uploaded = api.request('POST', f'/releases/{release_id}/assets?name=' + quote(path.name, safe=''), asset=path)
            verify_asset(uploaded, path)
        # Draft creation/upload must not have reserved a tag. Never adopt an existing ref.
        if api.request('GET', '/git/ref/tags/' + quote(tag, safe='')) is not None:
            raise DeliveryError('Tag appeared during packaging/publication; it will not be modified.')
        print('Publication phase: create owned annotated version tag')
        annotation = api.request('POST', '/git/tags', dict(tag=tag, message=marker,
                                  object=info['source_sha'], type='commit'))
        tag_object = annotation['sha']
        if not re.fullmatch(r'[0-9a-f]{40}', tag_object):
            raise DeliveryError('Invalid annotated tag identity.')
        api.request('POST', '/git/refs', dict(ref='refs/tags/' + tag, sha=tag_object))
        print('Publication phase: publish complete validated release')
        api.request('PATCH', f'/releases/{release_id}', dict(draft=False,
            prerelease=prerelease, make_latest='false' if prerelease else 'true'))
        return verify_result(api.request('GET', f'/releases/{release_id}'))
    except Exception as original:
        if release_id is None:
            raise DeliveryError('Publication stopped before an owned release was confirmed; inspect any draft before retrying.') from original
        try:
            current = api.request('GET', f'/releases/{release_id}')
            # A response can be lost after a successful publish. Reconcile once,
            # never blindly retry publication or delete a published release.
            if published(current):
                return verify_result(current)
            if (not current or current.get('draft') is not True
                    or current.get('tag_name') != tag or marker not in current.get('body', '')):
                raise DeliveryError('Release ownership/state is uncertain.')
            if tag_object:
                ref = api.request('GET', '/git/ref/tags/' + quote(tag, safe=''))
                if ref and ref.get('object', {}).get('sha') == tag_object:
                    api.request('DELETE', '/git/refs/tags/' + quote(tag, safe=''))
            api.request('DELETE', f'/releases/{release_id}')
        except Exception as cleanup:
            raise DeliveryError('Publication requires manual reconciliation; no uncertain or published state was removed.') from cleanup
        raise DeliveryError('Publication failed; the owned draft and any owned tag were rolled back. No automatic retry.') from original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['preflight', 'publish'])
    parser.add_argument('--directory', type=Path)
    args = parser.parse_args()
    if os.environ.get('PUBLISH_RELEASE') != 'true':
        raise DeliveryError('Publication must be explicitly enabled by manual dispatch.')
    info = context()
    rows = eligible(info, os.environ['DEPLOYMENT_PLATFORM'], json.loads(os.environ['DEPLOYMENT_NEEDS']))
    api = GitHub(os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_TOKEN'])
    api.available(info['tag'])
    if args.operation == 'preflight':
        output(artifact_ids=','.join(row['artifact_id'] for row in rows))
        return
    if args.directory is None:
        raise DeliveryError('A verified release asset directory is required.')
    result = publish(api, info, collect(args.directory, info, rows))
    summary = f'### Deployment release\n\nPublished {info["tag"]} from `{info["source_sha"]}`.\n\n{result["html_url"]}\n'
    print(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write(summary)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # No exception string, API body, credentials or signed download URL.
        detail = str(error) if isinstance(error, DeliveryError) else 'Inspect the preceding phase and release/tag state.'
        message = f'Deployment publication stopped ({type(error).__name__}): {detail} No automatic retry.'
        print(message, file=sys.stderr)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
                stream.write('### Deployment publication stopped\n\n' + message + '\n')
        raise SystemExit(1)
