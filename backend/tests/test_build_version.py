"""Offline build metadata and PE version identity; never build/run a Windows EXE."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import version

ROOT = Path(__file__).resolve().parents[2]


class BuildVersionTests(unittest.TestCase):
    def make(self, mode="beta", base="0.1.0", attempt=1, beta=1):
        return version.make_build_info(
            mode, base, "a" * 40, "1234", "123", attempt, beta
        )

    def test_local_fallback_is_identifiable_without_ci_environment(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {}, clear=True
        ):
            info = version.read_build_info(
                Path(directory) / "absent.json", frozen=False
            )
            self.assertEqual(info["version"], "0.0.0-dev.local")
            self.assertEqual(info["mode"], "local")
            self.assertEqual(info["source_sha"], "")

    def test_build_versions_include_run_number_and_rerun_attempt(self):
        first = self.make("build")
        rerun = self.make("build", attempt=2)
        self.assertEqual(first["version"], "0.1.0-dev.123")
        self.assertEqual(rerun["version"], "0.1.0-dev.123.2")
        self.assertNotEqual(first["version"], rerun["version"])
        self.assertNotEqual(first["file_version"], rerun["file_version"])
        self.assertEqual(first["tag"], "")
        self.assertGreaterEqual(first["file_version"][3], 32768)

    def test_beta_and_stable_have_distinct_numeric_resources(self):
        beta = self.make()
        stable = self.make("stable")
        self.assertEqual(beta["version"], "0.1.0-beta-1")
        self.assertEqual(beta["file_version"], [0, 1, 0, 1])
        self.assertEqual(beta["tag"], "v0.1.0-beta-1")
        self.assertEqual(stable["version"], "0.1.0")
        self.assertEqual(stable["file_version"], [0, 1, 0, 0])

    def test_frozen_metadata_loads_offline_and_ignores_runtime_ci_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "build-version.json"
            path.write_text(json.dumps(self.make()))
            with patch.dict(
                "os.environ",
                {"GITHUB_RUN_NUMBER": "999", "RELEASE_VERSION": "9.9.9"},
                clear=True,
            ), patch.object(sys, "_MEIPASS", directory, create=True):
                self.assertEqual(version.read_build_info(frozen=True), self.make())
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(
                    version.read_build_info(path, frozen=True)["version"],
                    "0.1.0-beta-1",
                )

    def test_frozen_module_exports_the_embedded_version_without_runtime_environment(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "build-version.json").write_text(json.dumps(self.make()))
            spec = importlib.util.spec_from_file_location(
                "isolated_frozen_version", ROOT / "backend/version.py"
            )
            module = importlib.util.module_from_spec(spec)
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "_MEIPASS", directory, create=True
            ), patch.dict("os.environ", {}, clear=True):
                spec.loader.exec_module(module)
            self.assertEqual(module.VERSION, "0.1.0-beta-1")
            self.assertEqual(module.FILE_VERSION, (0, 1, 0, 1))

    def test_missing_corrupt_or_oversized_packaged_metadata_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "build-version.json"
            with self.assertRaises(ValueError):
                version.read_build_info(path, frozen=True)
            for content in [
                "bad json",
                "{}",
                "x" * 4097,
                json.dumps(version.local_build_info()),
            ]:
                path.write_text(content)
                with self.subTest(content=content[:20]), self.assertRaises(ValueError):
                    version.read_build_info(path, frozen=True)

    def test_mismatched_fields_and_extra_private_values_are_rejected(self):
        for key, value in [
            ("version", "0.1.0-beta-2"),
            ("tag", "v0.2.0"),
            ("file_version", [0, 1, 0, 2]),
            ("schema", True),
            ("attempt", True),
            ("mode", {}),
            ("source_sha", "secret"),
            ("run_number", "01"),
            ("unexpected", "private"),
        ]:
            info = self.make()
            info[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                version.parse_build_info(info)
        self.assertEqual(version.parse_build_info(self.make()), self.make())

    def test_invalid_input_and_unrepresentable_pe_beta_are_rejected(self):
        for base in ["01.1.0", "v0.1.0", "0.1.0-beta-1", "65536.0.0", "0.1.0\n"]:
            with self.subTest(base=base), self.assertRaises(ValueError):
                self.make(base=base)
        for number in [0, 65536, True, None]:
            with self.subTest(number=number), self.assertRaises(ValueError):
                self.make(beta=number)

    def test_windows_resource_strings_and_fixed_numbers_use_same_metadata(self):
        for mode in ["beta", "stable", "build"]:
            info = self.make(mode)
            spec = importlib.util.spec_from_file_location(
                "generated_windows_metadata", ROOT / "scripts/write-windows-metadata.py"
            )
            writer = importlib.util.module_from_spec(spec)
            with patch.object(version, "VERSION", info["version"]), patch.object(
                version, "FILE_VERSION", tuple(info["file_version"])
            ), patch.object(version, "BUILD_INFO", info):
                spec.loader.exec_module(writer)
            values = writer.expected_metadata()
            self.assertEqual(values["ProductVersion"], info["version"])
            self.assertEqual(
                values["FileVersion"], ".".join(map(str, info["file_version"]))
            )
            self.assertEqual(values["ProductName"], "SAP Lens")
            self.assertEqual(values["FileDescription"], "SAP Lens")
            with tempfile.TemporaryDirectory() as directory, patch.object(
                writer, "ROOT", Path(directory)
            ):
                writer.main()
                text = (Path(directory) / "backend/build/version-info.txt").read_text()
                self.assertIn("filevers=" + repr(tuple(info["file_version"])), text)
                self.assertIn(info["version"], text)

    def test_pyinstaller_includes_the_single_metadata_resource(self):
        text = (ROOT / "scripts/build-windows.ps1").read_text()
        self.assertIn("'--add-data', ($buildIdentity + ';.')", text)
        self.assertIn("ensure-local-build", text)
        self.assertIn("backend/build/build-version.json", text)
        self.assertNotIn("1.2.0", (ROOT / "backend/version.py").read_text())
