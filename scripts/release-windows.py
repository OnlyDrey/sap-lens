"""Manual release orchestration. No network calls on import; no executable runs.

The read-only Windows job verifies the package. Only the dependent publication
job receives write access. All GitHub mutations target newly reserved identities.
"""

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from urllib.parse import quote
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "OnlyDrey/sap-lens"
SEMVER = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
FILES = ("SAP-Lens.exe", "SAP-Lens.exe.sha256")
REQUIRED_STEPS = (
    "Install dependencies and build production frontend",
    "Install Python build and test dependencies",
    "Audit Windows Python dependencies",
    "Run backend and repository regressions",
    "Audit JavaScript and run browser regressions",
    "Package Windows executable",
    "Verify Windows PE, resources, privacy and checksum",
    "Run Windows application smoke tests",
    "Upload verified executable",
    "Download this run's verified artifact",
    "Verify distributed artifact",
)


class ReleaseError(ValueError):
    pass


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(SEMVER, value) or len(value) > 32:
        raise ReleaseError(
            "Version must be MAJOR.MINOR.PATCH without leading zeros or a v prefix."
        )
    return tuple(map(int, value.split(".")))


def application_version():
    tree = ast.parse((ROOT / "backend/version.py").read_text(encoding="utf-8"))
    return next(
        ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in n.targets)
    )


def validate_inputs(mode, version, ref, source_version, attempt=1):
    requested = version_tuple(version)
    if mode not in {"build", "beta", "stable"}:
        raise ReleaseError("Unknown release mode.")
    if any(n > 65535 for n in requested):
        raise ReleaseError("Version exceeds Windows PE version component limits.")
    if version != source_version:
        raise ReleaseError(
            "Requested version must equal backend/version.py; no version-bump commits are made by CI."
        )
    if not ref.startswith("refs/heads/") or ref == "refs/heads/":
        raise ReleaseError("Select a branch, not a tag, for a manual build.")
    if mode == "stable" and ref != "refs/heads/main":
        raise ReleaseError("Stable publication is allowed only from main.")
    if mode != "build" and attempt != 1:
        raise ReleaseError(
            "Release workflow reruns are refused. Inspect prior tags/drafts and start a new manual run."
        )


def select_tag(mode, version, tags, releases):
    base = version_tuple(version)
    occupied = set(tags) | {r["tag_name"] for r in releases}
    if mode == "beta":
        pattern = re.compile(r"v" + re.escape(version) + r"-beta-([1-9][0-9]*)")
        numbers = [int(m[1]) for name in occupied if (m := pattern.fullmatch(name))]
        return f"v{version}-beta-{max(numbers, default=0) + 1}"
    if mode != "stable":
        raise ReleaseError("Build mode cannot allocate a release tag.")
    tag = "v" + version
    if tag in occupied:
        raise ReleaseError(
            "Stable tag or release already exists; it will not be changed."
        )
    previous = [
        version_tuple(name[1:])
        for name in occupied
        if re.fullmatch("v" + SEMVER, name) and len(name) <= 33
    ]
    if previous and base <= max(previous):
        raise ReleaseError(
            "Stable version must be greater than every existing stable version."
        )
    return tag


def verify_build(jobs, artifact, run, sha):
    if (
        run.get("event") != "workflow_dispatch"
        or run.get("head_sha") != sha
        or run.get("run_attempt") != 1
        or artifact.get("expired") is not False
        or artifact.get("name") != "SAP-Lens-Windows-x64"
        or artifact.get("workflow_run", {}).get("id") != run.get("id")
        or artifact.get("workflow_run", {}).get("head_sha") != sha
    ):
        raise ReleaseError(
            "Artifact/run provenance is not the verified first-attempt manual build."
        )
    builds = [j for j in jobs if j.get("name") == "Windows Build & Verification"]
    if len(builds) != 1 or builds[0].get("conclusion") != "success":
        raise ReleaseError(
            "Windows build job must have completed successfully before publication."
        )
    steps = builds[0].get("steps", [])
    for name in REQUIRED_STEPS:
        matches = [s for s in steps if s.get("name") == name]
        if len(matches) != 1 or matches[0].get("conclusion") != "success":
            raise ReleaseError(
                "A mandatory Windows build/verification step did not pass."
            )


def load_script(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), ROOT / "scripts" / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def release_archive(download, output, tag, digest):
    if not re.fullmatch("v" + SEMVER + r"(?:-beta-[1-9][0-9]*)?", tag):
        raise ReleaseError("Invalid release tag for asset naming.")
    if output.exists():
        raise ReleaseError("Release asset destination must be new.")
    archive_guard = load_script("verify-artifact-zip")
    package_guard = load_script("verify-windows-package")
    with tempfile.TemporaryDirectory(prefix="sap-lens-release-") as temp:
        distribution = Path(temp) / "distribution"
        archive_guard.verify(download, distribution, digest)
        data, exe_sha = package_guard.validate_distribution(distribution)
        package_guard.validate_gui(data)
        del data
        output.mkdir(parents=True)
        archive = output / f"SAP-Lens-Windows-x64-{tag}.zip"
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_STORED) as target:
            for name in FILES:
                entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = (stat.S_IFREG | 0o644) << 16
                entry.compress_type = zipfile.ZIP_STORED
                target.writestr(entry, (distribution / name).read_bytes())
        with archive.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        manifest = archive.with_suffix(".zip.sha256")
        manifest.write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
        # Check the exact new ZIP with the same canonical guard as the Actions roundtrip.
        check_input = Path(temp) / "archive"
        check_input.mkdir()
        (check_input / archive.name).write_bytes(archive.read_bytes())
        verified = Path(temp) / "verified"
        archive_guard.verify(check_input, verified, checksum)
        package_guard.validate_distribution(verified, exe_sha)
    return archive, manifest, exe_sha, checksum


class GitHub:
    """Official gh transport; structured JSON stdin, no shell or credential output."""

    def __init__(self, repository):
        if repository != REPOSITORY:
            raise ReleaseError(
                "Unexpected repository for SAP Lens release publication."
            )
        self.repository = repository
        self.base = f"repos/{repository}"

    def api(self, path, method="GET", payload=None, upload=None):
        command = ["gh", "api", "--method", method, path]
        data = None
        if payload is not None:
            command += ["--input", "-"]
            data = json.dumps(payload).encode()
        if upload is not None:
            command += [
                "--input",
                str(upload),
                "-H",
                "Content-Type: application/octet-stream",
            ]
        try:
            result = subprocess.run(
                command, input=data, capture_output=True, timeout=90
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ReleaseError(
                "GitHub operation interrupted; inspect the reserved tag/draft before retrying."
            ) from error
        if result.returncode:
            raise ReleaseError(
                "GitHub operation refused or failed; existing tags/releases are never replaced. Inspect this run and any reserved tag/draft."
            )
        try:
            return json.loads(result.stdout)
        except ValueError as error:
            raise ReleaseError(
                "Unexpected GitHub response; publication stopped."
            ) from error

    def list(self, path):
        items = []
        for page in range(1, 101):
            batch = self.api(f"{path}?per_page=100&page={page}")
            if not isinstance(batch, list):
                raise ReleaseError("Invalid paginated GitHub response.")
            items.extend(batch)
            if len(batch) < 100:
                return items
        raise ReleaseError(
            "GitHub pagination safety limit exceeded; no version allocated."
        )

    def download(self, asset, destination):
        try:
            with destination.open("xb") as output:
                result = subprocess.run(
                    [
                        "gh",
                        "api",
                        f'{self.base}/releases/assets/{asset["id"]}',
                        "-H",
                        "Accept: application/octet-stream",
                    ],
                    stdout=output,
                    stderr=subprocess.PIPE,
                    timeout=90,
                )
            if result.returncode:
                raise ReleaseError(
                    "Uploaded release asset could not be downloaded for verification."
                )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ReleaseError(
                "Release asset verification interrupted; the release must remain a draft."
            ) from error


def notes(mode, tag, sha, run_id, exe_sha, zip_sha, previous=None):
    text = (
        f"SAP Lens {tag}\n\n"
        + (
            "Beta prerelease intended for testing.\n\n"
            if mode == "beta"
            else "Stable Windows release.\n\n"
        )
        + f'Source commit: `{sha}`\n\nBuild date (UTC): {datetime.now(timezone.utc).isoformat(timespec="seconds")}\n\n'
        + f"Platform: Windows x64; one-file EXE, WebView2. Unsigned.\n\n"
        + f"EXE SHA-256: `{exe_sha}`\n\nZIP SHA-256: `{zip_sha}`\n\n"
        + "The ZIP contains SAP-Lens.exe and its SHA-256 manifest. The adjacent ZIP checksum covers the download.\n\n"
        + f"Originating build: https://github.com/{REPOSITORY}/actions/runs/{run_id}\n"
    )
    if previous and re.fullmatch("v" + SEMVER + r"(?:-beta-[1-9][0-9]*)?", previous):
        text += (
            f"\nChanges: https://github.com/{REPOSITORY}/compare/{previous}...{sha}\n"
        )
    return text


def publish(client, env, download, output, source_version, progress):
    mode, version, ref = env["RELEASE_MODE"], env["RELEASE_VERSION"], env["GITHUB_REF"]
    attempt = int(env["GITHUB_RUN_ATTEMPT"])
    validate_inputs(mode, version, ref, source_version, attempt)
    if mode == "build" or env.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise ReleaseError(
            "Publication requires a first-attempt manual beta/stable run."
        )
    sha = env["GITHUB_SHA"]
    run_id = env["GITHUB_RUN_ID"]
    artifact_id = env["ARTIFACT_ID"]
    if (
        not re.fullmatch("[0-9a-f]{40}", sha)
        or not run_id.isdigit()
        or not artifact_id.isdigit()
    ):
        raise ReleaseError("Invalid source/run/artifact identity.")
    base = client.base
    run = client.api(f"{base}/actions/runs/{run_id}")
    job_response = client.api(
        f"{base}/actions/runs/{run_id}/jobs?filter=latest&per_page=100"
    )
    artifact = client.api(f"{base}/actions/artifacts/{artifact_id}")
    verify_build(job_response["jobs"], artifact, run, sha)
    if artifact.get("digest") != "sha256:" + env["ARTIFACT_DIGEST"]:
        raise ReleaseError("Build artifact digest does not match GitHub provenance.")
    branch = quote(ref.removeprefix("refs/heads/"), safe="")
    if client.api(f"{base}/git/ref/heads/{branch}")["object"]["sha"] != sha:
        raise ReleaseError(
            "Source branch advanced; publish from a new verified build instead."
        )
    tags = [t["name"] for t in client.list(f"{base}/tags")]
    releases = client.list(f"{base}/releases")
    tag = select_tag(mode, version, tags, releases)
    progress["tag"] = tag
    archive, manifest, exe_sha, zip_sha = release_archive(
        download, output, tag, env["ARTIFACT_DIGEST"]
    )
    # Atomic ref creation is the final guard against external publishers racing our workflow lock.
    client.api(f"{base}/git/refs", "POST", {"ref": "refs/tags/" + tag, "sha": sha})
    progress["reserved"] = True
    previous = next(
        (
            r["tag_name"]
            for r in releases
            if not r["draft"] and (mode == "beta" or not r["prerelease"])
        ),
        None,
    )
    body = notes(mode, tag, sha, run_id, exe_sha, zip_sha, previous)
    created = client.api(
        f"{base}/releases",
        "POST",
        dict(
            tag_name=tag,
            target_commitish=sha,
            name=f"SAP Lens {tag}",
            body=body,
            prerelease=mode == "beta",
            draft=True,
            make_latest="false",
        ),
    )
    release_id = created["id"]
    progress["draft_id"] = release_id

    def owned_draft(release):
        if (
            release.get("id") != release_id
            or release.get("tag_name") != tag
            or release.get("draft") is not True
            or release.get("prerelease") != (mode == "beta")
            or release.get("target_commitish") != sha
        ):
            raise ReleaseError(
                "Reserved release identity/state changed; refusing further modification."
            )

    owned_draft(created)
    expected = {archive.name: archive, manifest.name: manifest}
    if created.get("assets"):
        raise ReleaseError("New draft unexpectedly has assets; refusing replacement.")
    for name, path in expected.items():
        client.api(
            f"https://uploads.github.com/{base}/releases/{release_id}/assets?name={quote(name)}",
            "POST",
            upload=path,
        )
    staged = client.api(f"{base}/releases/{release_id}")
    owned_draft(staged)
    assets = staged.get("assets", [])
    if len(assets) != 2 or {a["name"] for a in assets} != set(expected):
        raise ReleaseError(
            "Draft has missing, duplicate or unexpected assets; it remains unpublished."
        )
    with tempfile.TemporaryDirectory(prefix="sap-lens-published-check-") as temp:
        for asset in assets:
            path = Path(temp) / asset["name"]
            client.download(asset, path)
            original = expected[asset["name"]]
            if (
                path.stat().st_size != original.stat().st_size
                or path.read_bytes() != original.read_bytes()
            ):
                raise ReleaseError(
                    "Uploaded release asset differs; draft remains unpublished."
                )
        # Exact byte comparison includes the ZIP manifest, which was generated and verified locally.
    owned_draft(client.api(f"{base}/releases/{release_id}"))
    reference = client.api(f"{base}/git/ref/tags/{tag}")["object"]
    if reference.get("type") != "commit" or reference.get("sha") != sha:
        raise ReleaseError("Reserved tag moved; draft remains unpublished.")
    final = client.api(
        f"{base}/releases/{release_id}",
        "PATCH",
        dict(
            draft=False,
            prerelease=mode == "beta",
            make_latest="false" if mode == "beta" else "true",
        ),
    )
    if (
        final.get("id") != release_id
        or final.get("tag_name") != tag
        or final.get("draft") is not False
        or final.get("prerelease") != (mode == "beta")
        or final.get("target_commitish") != sha
    ):
        raise ReleaseError(
            "Publication response is unexpected; inspect GitHub state, do not rerun automatically."
        )
    progress.update(
        published=True, url=final["html_url"], exe_sha=exe_sha, zip_sha=zip_sha
    )
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate-inputs", "publish"])
    parser.add_argument("--download", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    env = os.environ
    progress = {}
    try:
        validate_inputs(
            env["RELEASE_MODE"],
            env["RELEASE_VERSION"],
            env["GITHUB_REF"],
            application_version(),
            int(env["GITHUB_RUN_ATTEMPT"]),
        )
        if args.command == "validate-inputs":
            print(
                "Manual build/release inputs match the authoritative application version."
            )
            return
        if args.download is None or args.output is None:
            raise ReleaseError("Missing publication artifact directories.")
        publish(
            GitHub(env["GITHUB_REPOSITORY"]),
            env,
            args.download,
            args.output,
            application_version(),
            progress,
        )
    except Exception as error:
        message = (
            str(error)
            if isinstance(error, ReleaseError)
            else "Release operation failed; inspect reserved tag/draft and run logs before recovery."
        )
        print("Release stopped: " + message)
        raise SystemExit(1)
    finally:
        if args.command == "publish" and env.get("GITHUB_STEP_SUMMARY"):
            state = (
                "Published"
                if progress.get("published")
                else "Not confirmed published — inspect GitHub state before recovery"
            )
            text = f"## Windows release publication\n\n{state}.\n\n"
            text += f'Mode: {env.get("RELEASE_MODE", "unknown")}; tag: {progress.get("tag", "not allocated")}.\n\n'
            if progress.get("reserved") and not progress.get("published"):
                text += "A tag was reserved. Any created release is deliberately left as a draft unless publication completed; an interrupted final API call may require checking its actual state. No automatic deletion or replacement is attempted.\n"
            if progress.get("published"):
                text += f'{progress["url"]}\n\nEXE SHA-256: `{progress["exe_sha"]}`\n\nZIP SHA-256: `{progress["zip_sha"]}`\n'
            Path(env["GITHUB_STEP_SUMMARY"]).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
