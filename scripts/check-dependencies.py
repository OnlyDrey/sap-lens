"""NuGet audit with a real failure exit code when advisories are found (dotnet list alone returns zero)."""
from pathlib import Path
import json
import subprocess

root = Path(__file__).resolve().parents[1]
done = subprocess.run(['dotnet', 'list', str(root / 'backend/SapLens.slnx'), 'package', '--vulnerable', '--include-transitive', '--format', 'json'],
                      capture_output=True, text=True, timeout=180)
if done.returncode:
    print(done.stderr)
    raise SystemExit(done.returncode)
try:
    report = json.loads(done.stdout)
except ValueError:
    print('NuGet audit did not return valid JSON; advisory status is unknown.')
    raise SystemExit(1) from None
findings = []
for project in report.get('projects', []):
    for framework in project.get('frameworks', []):
        for group in ('topLevelPackages', 'transitivePackages'):
            for package in framework.get(group, []):
                if package.get('vulnerabilities'):
                    findings.append((Path(project['path']).name, package['id'], package.get('resolvedVersion')))
for finding in findings:
    print('Vulnerable NuGet package:', *finding)
print(f'NuGet dependency audit: {len(findings)} vulnerable package references.')
raise SystemExit(bool(findings) or bool(report.get('problems')))
