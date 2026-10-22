"""Release decisions and failure boundaries use synthetic archives and a fake GitHub.

No tags, releases, Windows builds or network requests are created by these tests.
"""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from test_windows_package import synthetic_pe

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "release_windows", ROOT / "scripts/release-windows.py"
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
SHA = "a" * 40
VERSION = "1.2.0"


class FakeGitHub:
    base = "repos/OnlyDrey/sap-lens"

    def __init__(self, digest):
        self.digest = digest
        self.tags = []
        self.releases = []
        self.writes = []
        self.draft = None
        self.assets = {}
        self.jobs = [
            dict(
                name="Windows Build & Verification",
                conclusion="success",
                steps=[
                    dict(name=n, conclusion="success") for n in release.REQUIRED_STEPS
                ],
            )
        ]
        self.artifact = dict(
            id=3,
            expired=False,
            name="SAP-Lens-Windows-x64",
            digest="sha256:" + digest,
            workflow_run=dict(id=1, head_sha=SHA),
        )
        self.run = dict(id=1, head_sha=SHA, event="workflow_dispatch", run_attempt=1)
        self.tag_sha = SHA
        self.branch_sha = SHA
        self.upload_failure = False
        self.tamper = False
        self.missing_asset = False
        self.collision = False
        self.reserve = None

    def list(self, path):
        return copy.deepcopy(self.tags if path.endswith("/tags") else self.releases)

    def api(self, path, method="GET", payload=None, upload=None):
        if method != "GET":
            self.writes.append((method, path, copy.deepcopy(payload)))
        if path.endswith("/actions/runs/1"):
            return copy.deepcopy(self.run)
        if "/actions/runs/1/jobs?" in path:
            return dict(jobs=copy.deepcopy(self.jobs))
        if path.endswith("/actions/artifacts/3"):
            return copy.deepcopy(self.artifact)
        if "/git/ref/tags/" in path:
            return dict(object=dict(type="commit", sha=self.tag_sha))
        if "/git/ref/heads/" in path:
            return dict(object=dict(sha=self.branch_sha))
        if path.endswith("/git/refs"):
            if self.reserve:
                self.reserve(payload["ref"])
            if self.collision:
                raise release.ReleaseError("Atomic reservation collision")
            self.tags.append(dict(name=payload["ref"].removeprefix("refs/tags/")))
            return dict(ref=payload["ref"])
        if path.endswith("/releases") and method == "POST":
            self.draft = dict(
                payload,
                id=7,
                assets=[],
                html_url="https://github.com/OnlyDrey/sap-lens/releases/test",
            )
            return copy.deepcopy(self.draft)
        if upload is not None:
            if self.upload_failure:
                raise release.ReleaseError("Synthetic upload failure")
            name = upload.name
            self.assets[name] = upload.read_bytes()
            if not self.missing_asset:
                self.draft["assets"].append(dict(name=name, id=len(self.assets)))
            return dict(name=name)
        if path.endswith("/releases/7"):
            if method == "PATCH":
                self.draft.update(payload)
            return copy.deepcopy(self.draft)
        raise AssertionError("Unexpected fake operation: " + path)

    def download(self, asset, destination):
        data = self.assets[asset["name"]]
        destination.write_bytes(data + (b"changed" if self.tamper else b""))


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.download = self.root / "download"
        self.download.mkdir()
        self.exe = bytes(synthetic_pe())
        self.exe_sha = hashlib.sha256(self.exe).hexdigest()
        self.manifest = f"{self.exe_sha}  SAP-Lens.exe\n".encode()
        self.digest = self.write_archive()
        self.env = dict(
            RELEASE_MODE="beta",
            RELEASE_VERSION=VERSION,
            GITHUB_REF="refs/heads/work",
            GITHUB_RUN_ATTEMPT="1",
            GITHUB_EVENT_NAME="workflow_dispatch",
            GITHUB_SHA=SHA,
            GITHUB_RUN_ID="1",
            ARTIFACT_ID="3",
            ARTIFACT_DIGEST=self.digest,
        )
        self.client = FakeGitHub(self.digest)
        self.progress = {}

    def write_archive(self, manifest=True, extra=False):
        path = self.download / "source.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("SAP-Lens.exe", self.exe)
            if manifest:
                archive.writestr("SAP-Lens.exe.sha256", self.manifest)
            if extra:
                archive.writestr("unexpected.csv", b"SYNTHETIC")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def publish(self):
        return release.publish(
            self.client,
            self.env,
            self.download,
            self.root / "output",
            VERSION,
            self.progress,
        )

    def test_beta_number_matrix(self):
        for tags, expected in [
            ([], 1),
            (["v1.2.0-beta-1"], 2),
            (["v1.2.0-beta-3", "v1.2.0-beta-12", "v1.2.0-beta-2"], 13),
            (["v1.2.0-beta-2", "v1.2.0-beta-9"], 10),
            (["v1.3.0-beta-10", "v1.2.1-beta-20"], 1),
            (
                [
                    "v1.2.0-beta-0",
                    "v1.2.0-beta-01",
                    "v1.2.0-beta-2x",
                    "xv1.2.0-beta-9",
                    "v1.2.0-beta--1",
                ],
                1,
            ),
        ]:
            with self.subTest(tags=tags):
                self.assertEqual(
                    release.select_tag("beta", VERSION, tags, []),
                    f"v1.2.0-beta-{expected}",
                )

    def test_large_beta_counters_are_compared_numerically(self):
        self.assertEqual(
            release.select_tag("beta", VERSION, ["v1.2.0-beta-1000000000"], []),
            "v1.2.0-beta-1000000001",
        )

    def test_beta_considers_drafts_and_reserved_tags(self):
        self.assertEqual(
            release.select_tag(
                "beta",
                VERSION,
                ["v1.2.0-beta-5"],
                [dict(tag_name="v1.2.0-beta-8", draft=True)],
            ),
            "v1.2.0-beta-9",
        )

    def test_strict_versions_and_windows_component_limits(self):
        for value in [
            "",
            "v1.2.3",
            "01.2.3",
            "1.02.3",
            "1.2.03",
            "-1.2.3",
            "1.2",
            "1.2.3.4",
            "1.2.3-beta-1",
            "1.2.3+meta",
            " 1.2.3",
            "1.2.3\n",
            "１.2.3",
            "9" * 40 + ".0.0",
        ]:
            with self.subTest(value=value), self.assertRaises(release.ReleaseError):
                release.version_tuple(value)
        self.assertEqual(release.version_tuple("0.0.0"), (0, 0, 0))
        with self.assertRaises(release.ReleaseError):
            release.validate_inputs(
                "build", "65536.0.0", "refs/heads/work", "65536.0.0"
            )

    def test_source_version_branch_and_mode_policy(self):
        for mode, ref in [("build", "work"), ("beta", "work"), ("stable", "main")]:
            release.validate_inputs(mode, VERSION, "refs/heads/" + ref, VERSION)
        for mode, version, ref in [
            ("stable", VERSION, "refs/heads/work"),
            ("stable", VERSION, "refs/heads/feature/main"),
            ("beta", VERSION, "refs/tags/v1.2.0"),
            ("beta", "0.1.0", "refs/heads/work"),
            ("other", VERSION, "refs/heads/main"),
        ]:
            with self.subTest(mode=mode, ref=ref), self.assertRaises(
                release.ReleaseError
            ):
                release.validate_inputs(mode, version, ref, VERSION)

    def test_stable_duplicate_and_progression(self):
        for tags, releases in [
            (["v1.2.0"], []),
            ([], [dict(tag_name="v1.2.0")]),
            (["v1.3.0"], []),
            (["v2.0.0"], []),
        ]:
            with self.assertRaises(release.ReleaseError):
                release.select_tag("stable", VERSION, tags, releases)
        self.assertEqual(
            release.select_tag("stable", VERSION, ["v1.1.9", "v1.2.0-beta-8"], []),
            "v1.2.0",
        )
        self.assertEqual(
            release.select_tag("stable", "1.10.0", ["v1.9.0"], []), "v1.10.0"
        )

    def test_reruns_refused_before_any_publication(self):
        for mode in ["beta", "stable"]:
            self.env.update(
                RELEASE_MODE=mode, GITHUB_REF="refs/heads/main", GITHUB_RUN_ATTEMPT="2"
            )
            with self.assertRaises(release.ReleaseError):
                self.publish()
            self.assertEqual(self.client.writes, [])
        release.validate_inputs("build", VERSION, "refs/heads/work", VERSION, 2)

    def test_build_mode_and_nonmanual_events_never_publish(self):
        for key, value in [
            ("RELEASE_MODE", "build"),
            ("GITHUB_EVENT_NAME", "push"),
            ("GITHUB_EVENT_NAME", "pull_request"),
        ]:
            env = copy.deepcopy(self.env)
            env[key] = value
            with self.assertRaises(release.ReleaseError):
                release.publish(
                    self.client, env, self.download, self.root / "output", VERSION, {}
                )
            self.assertEqual(self.client.writes, [])

    def test_beta_success_exact_assets_flags_commit_and_roundtrip(self):
        result = self.publish()
        self.assertTrue(self.progress["published"])
        self.assertFalse(result["draft"])
        self.assertTrue(result["prerelease"])
        self.assertEqual(result["target_commitish"], SHA)
        self.assertEqual(result["name"], "SAP Lens v1.2.0-beta-1")
        self.assertEqual(
            set(self.client.assets),
            {
                "SAP-Lens-Windows-x64-v1.2.0-beta-1.zip",
                "SAP-Lens-Windows-x64-v1.2.0-beta-1.zip.sha256",
            },
        )
        self.assertIn("intended for testing", result["body"])
        self.assertIn(SHA, result["body"])
        self.assertEqual(
            self.client.writes[0][2], dict(ref="refs/tags/v1.2.0-beta-1", sha=SHA)
        )
        self.assertTrue(self.client.writes[1][2]["draft"])
        self.assertEqual(
            [w[0] for w in self.client.writes],
            ["POST", "POST", "POST", "POST", "PATCH"],
        )

    def test_stable_success_flags(self):
        self.env.update(RELEASE_MODE="stable", GITHUB_REF="refs/heads/main")
        result = self.publish()
        self.assertEqual(result["tag_name"], "v1.2.0")
        self.assertFalse(result["draft"])
        self.assertFalse(result["prerelease"])
        self.assertEqual(result["make_latest"], "true")

    def test_each_mandatory_check_failure_blocks_all_mutations(self):
        for name in release.REQUIRED_STEPS:
            for step in self.client.jobs[0]["steps"]:
                step["conclusion"] = "failure" if step["name"] == name else "success"
            with self.subTest(name=name), self.assertRaises(release.ReleaseError):
                self.publish()
            self.assertEqual(self.client.writes, [])

    def test_failed_or_missing_build_job_blocks_publication(self):
        for jobs in [
            [],
            [dict(name="Windows Build & Verification", conclusion="failure")],
        ]:
            self.client.jobs = jobs
            with self.assertRaises(release.ReleaseError):
                self.publish()
            self.assertEqual(self.client.writes, [])

    def test_artifact_provenance_and_missing_digest_fail_closed(self):
        original = copy.deepcopy(self.client.artifact)
        for field, value in [
            ("expired", True),
            ("name", "other"),
            ("digest", ""),
            ("workflow_run", dict(id=2, head_sha=SHA)),
        ]:
            self.client.artifact = copy.deepcopy(original)
            self.client.artifact[field] = value
            with self.subTest(field=field), self.assertRaises(release.ReleaseError):
                self.publish()
            self.assertEqual(self.client.writes, [])

    def test_branch_movement_and_run_attempt_mismatch_block_publication(self):
        self.client.branch_sha = "b" * 40
        with self.assertRaises(release.ReleaseError):
            self.publish()
        self.client.branch_sha = SHA
        self.client.run["run_attempt"] = 2
        with self.assertRaises(release.ReleaseError):
            self.publish()
        self.assertEqual(self.client.writes, [])

    def test_missing_checksum_artifact_or_extra_private_file_before_reservation(self):
        for manifest, extra in [(False, False), (True, True)]:
            self.digest = self.write_archive(manifest, extra)
            self.env["ARTIFACT_DIGEST"] = self.digest
            self.client = FakeGitHub(self.digest)
            with self.assertRaises(ValueError):
                self.publish()
            self.assertEqual(self.client.writes, [])
        (self.download / "source.zip").unlink()
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.client.writes, [])

    def test_bad_inner_checksum_before_reservation(self):
        self.manifest = b"0" * 64 + b"  SAP-Lens.exe\n"
        self.digest = self.write_archive()
        self.env["ARTIFACT_DIGEST"] = self.digest
        self.client = FakeGitHub(self.digest)
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.client.writes, [])

    def test_failed_asset_upload_keeps_draft_and_reserved_tag(self):
        self.client.upload_failure = True
        with self.assertRaises(release.ReleaseError):
            self.publish()
        self.assertTrue(self.progress["reserved"])
        self.assertTrue(self.client.draft["draft"])
        self.assertFalse(
            any(method in {"PATCH", "DELETE"} for method, _, _ in self.client.writes)
        )

    def test_missing_or_changed_uploaded_assets_never_publish(self):
        for field in ["tamper", "missing_asset"]:
            with self.subTest(field=field):
                client = FakeGitHub(self.digest)
                setattr(client, field, True)
                with self.assertRaises(release.ReleaseError):
                    release.publish(
                        client, self.env, self.download, self.root / field, VERSION, {}
                    )
                self.assertTrue(client.draft["draft"])
                self.assertFalse(
                    any(w[0] in {"PATCH", "DELETE"} for w in client.writes)
                )

    def test_moved_tag_does_not_publish_draft(self):
        self.client.tag_sha = "b" * 40
        with self.assertRaises(release.ReleaseError):
            self.publish()
        self.assertTrue(self.client.draft["draft"])
        self.assertFalse(any(w[0] == "PATCH" for w in self.client.writes))

    def test_atomic_collision_never_overwrites_or_creates_release(self):
        self.client.collision = True
        with self.assertRaises(release.ReleaseError):
            self.publish()
        self.assertIsNone(self.client.draft)
        self.assertEqual(len(self.client.writes), 1)

    def test_two_concurrent_publishers_only_one_reserves_and_publishes(self):
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        reserved = set()
        outcomes = []

        def reserve(ref):
            barrier.wait(timeout=10)
            with lock:
                if ref in reserved:
                    raise release.ReleaseError("Concurrent collision")
                reserved.add(ref)

        def worker(index):
            client = FakeGitHub(self.digest)
            client.reserve = reserve
            try:
                release.publish(
                    client, self.env, self.download, self.root / str(index), VERSION, {}
                )
                outcomes.append("published")
            except release.ReleaseError:
                outcomes.append("collision")

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertEqual(sorted(outcomes), ["collision", "published"])
        self.assertEqual(len(reserved), 1)

    def test_deterministic_archive_preserves_exe_bytes_and_both_checksums(self):
        archives = []
        for n in range(2):
            archive, manifest, exe_sha, zip_sha = release.release_archive(
                self.download, self.root / str(n), "v1.2.0-beta-1", self.digest
            )
            archives.append(archive.read_bytes())
            self.assertEqual(exe_sha, self.exe_sha)
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), zip_sha)
            self.assertEqual(manifest.read_text(), f"{zip_sha}  {archive.name}\n")
            with zipfile.ZipFile(archive) as contents:
                self.assertEqual(contents.namelist(), list(release.FILES))
                self.assertEqual(contents.read("SAP-Lens.exe"), self.exe)
                self.assertEqual(contents.read("SAP-Lens.exe.sha256"), self.manifest)
                self.assertTrue(
                    all(
                        i.date_time == (1980, 1, 1, 0, 0, 0)
                        for i in contents.infolist()
                    )
                )
        self.assertEqual(archives[0], archives[1])

    def test_github_transport_uses_structured_stdin_without_echoing_remote_errors(self):
        client = release.GitHub(release.REPOSITORY)
        with patch.object(release.subprocess, "run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = b"SENSITIVE"
            with self.assertRaises(release.ReleaseError) as error:
                client.api("repos/example", "POST", {"name": "literal"})
            self.assertNotIn("SENSITIVE", str(error.exception))
            self.assertEqual(
                json.loads(run.call_args.kwargs["input"]), {"name": "literal"}
            )
            self.assertNotIn("shell", run.call_args.kwargs)
        with self.assertRaises(release.ReleaseError):
            release.GitHub("other/repository")

    def test_compare_link_only_for_valid_release_tags(self):
        for previous, expect in [
            ("v1.1.0", True),
            ("v1.2.0-beta-1", True),
            ("internal personal text", False),
        ]:
            note = release.notes(
                "stable", "v1.2.0", SHA, "1", "b" * 64, "c" * 64, previous
            )
            self.assertEqual("/compare/" in note, expect)
            self.assertNotIn("internal personal text", note)
