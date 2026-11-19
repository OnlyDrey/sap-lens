"""NuGet audit with a real failure exit code for findings or incomplete advisory queries."""
from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def findings(report):
    if report.get('version') != 1 or not isinstance(report.get('projects'), list) or not report['projects']:
        raise ValueError('Unsupported or empty NuGet audit report; advisory status is unknown.')
    if report.get('problems') or report.get('logs'):
        raise ValueError('NuGet reported an incomplete advisory query; inspect the local SDK/feed configuration.')
    result = []
    for project in report['projects']:
        for framework in project.get('frameworks', []):
            for group in ('topLevelPackages', 'transitivePackages'):
                for package in framework.get(group, []):
                    if package.get('vulnerabilities'):
                        result.append((Path(project['path']).name, package['id'], package.get('resolvedVersion')))
    return result


def main():
    done = subprocess.run(['dotnet', 'list', str(ROOT / 'backend/AuthLens.slnx'), 'package', '--vulnerable', '--include-transitive', '--format', 'json'],
                          capture_output=True, text=True, timeout=180)
    if done.returncode:
        print('NuGet advisory query failed; run dotnet list package locally for feed diagnostics.')
        return done.returncode
    try:
        rows = findings(json.loads(done.stdout))
    except (ValueError, KeyError, TypeError) as error:
        print(f'NuGet audit failed: {error}')
        return 1
    for row in rows:
        print('Vulnerable NuGet package:', *row)
    print(f'NuGet dependency audit: {len(rows)} vulnerable package references.')
    return int(bool(rows))


if __name__ == '__main__':
    raise SystemExit(main())
