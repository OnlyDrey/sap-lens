"""Offline build identity. Generated metadata is authoritative; no runtime CI env.

The workflow writes backend/build/build-version.json, which PyInstaller embeds
at its resource root. Missing source-checkout metadata means local development;
a frozen executable must contain valid metadata and never silently falls back.
"""

import json
from pathlib import Path
import re
import sys

BASE_PATTERN = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
FIELDS = {
    "schema",
    "version",
    "base_version",
    "mode",
    "file_version",
    "source_sha",
    "run_id",
    "run_number",
    "attempt",
    "tag",
}


def base_numbers(value):
    if (
        not isinstance(value, str)
        or len(value) > 32
        or not re.fullmatch(BASE_PATTERN, value)
    ):
        raise ValueError(
            "Build base version must be MAJOR.MINOR.PATCH without leading zeros."
        )
    numbers = tuple(map(int, value.split(".")))
    if any(n > 65535 for n in numbers):
        raise ValueError("Build version exceeds Windows PE component limits.")
    return numbers


def make_build_info(
    mode, base, source_sha, run_id, run_number, attempt=1, beta_number=None
):
    numbers = base_numbers(base)
    if (
        not isinstance(mode, str)
        or mode not in {"build", "beta", "stable"}
        or type(attempt) is not int
        or attempt < 1
    ):
        raise ValueError("Invalid build mode or attempt.")
    if not isinstance(source_sha, str) or not re.fullmatch("[0-9a-f]{40}", source_sha):
        raise ValueError("Build source commit must be a full Git SHA.")
    for value in (run_id, run_number):
        if not isinstance(value, str) or not re.fullmatch("[1-9][0-9]{0,19}", value):
            raise ValueError("Build/run identity must be a positive decimal number.")
    if mode == "beta":
        if type(beta_number) is not int or not 1 <= beta_number <= 65535:
            raise ValueError(
                "Beta sequence cannot be represented in Windows FileVersion; use a new base version."
            )
        resolved, fourth = f"{base}-beta-{beta_number}", beta_number
    elif mode == "stable":
        resolved, fourth = base, 0
    else:
        resolved = f"{base}-dev.{run_number}" + (f".{attempt}" if attempt > 1 else "")
        # PE has only 16 bits per component. Full ProductVersion remains unique;
        # dev's numeric range avoids stable and ordinary low beta sequence numbers.
        fourth = 32768 + ((int(run_number) * 16 + attempt - 1) % 32768)
    return dict(
        schema=1,
        version=resolved,
        base_version=base,
        mode=mode,
        file_version=[*numbers, fourth],
        source_sha=source_sha,
        run_id=run_id,
        run_number=run_number,
        attempt=attempt,
        tag="" if mode == "build" else "v" + resolved,
    )


def make_local_package_info(requested_version, source_sha):
    """Deterministic unofficial identity; no reserved tag or fabricated CI run."""
    if not isinstance(requested_version, str) or len(requested_version) > 48:
        raise ValueError("Local version must be MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH-beta-N.")
    match = re.fullmatch(r"(" + BASE_PATTERN + r")(?:-beta-([1-9][0-9]{0,4}))?", requested_version)
    if not match:
        raise ValueError("Local version must be MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH-beta-N.")
    base = match[1]
    numbers = base_numbers(base)
    beta = int(match[5]) if match[5] else 0
    if beta > 65535 or not isinstance(source_sha, str) or not re.fullmatch('[0-9a-f]{40}', source_sha):
        raise ValueError("Invalid local build sequence or source commit.")
    return dict(schema=1, version=f"{requested_version}+local.{source_sha[:12]}",
                base_version=base, mode="local-build", file_version=[*numbers, beta],
                source_sha=source_sha, run_id="", run_number="", attempt=0, tag="")


def deployment_version(base, channel, sequence=""):
    """Explicit SemVer for deployment dispatches; legacy desktop numbering is unchanged."""
    base_numbers(base)
    if channel not in {"alpha", "beta", "rc", "stable"}:
        raise ValueError("Choose alpha, beta, rc or stable.")
    if not isinstance(sequence, str) or (sequence and not re.fullmatch(r"[1-9][0-9]{0,4}", sequence)):
        raise ValueError("Prerelease number must be a positive integer without leading zeros.")
    if sequence and int(sequence) > 65535:
        raise ValueError("Prerelease number exceeds Windows FileVersion limits.")
    if channel != "stable" and not sequence:
        raise ValueError("A prerelease number is required for alpha, beta and rc.")
    return base if channel == "stable" else f"{base}-{channel}.{sequence}"


def make_deployment_info(base, channel, sequence, source_sha, run_id, run_number, attempt=1):
    # Reuse the existing strict source/run/PE validation. Schema 2 distinguishes
    # explicit SemVer candidates from schema 1's reserved legacy beta-N releases.
    value = make_build_info("build", base, source_sha, run_id, run_number, attempt)
    resolved = deployment_version(base, channel, sequence)
    value.update(schema=2, version=resolved, mode=channel,
                 file_version=[*base_numbers(base), 0 if channel == "stable" else int(sequence)],
                 tag="v" + resolved)
    return value


def make_local_deployment_info(requested, source_sha):
    """Exact requested SemVer for local packages, explicitly without a CI run/tag."""
    if not isinstance(requested, str) or len(requested) > 48:
        raise ValueError("Use MAJOR.MINOR.PATCH[-alpha.N|-beta.N|-rc.N].")
    match = re.fullmatch(r"(" + BASE_PATTERN + r")(?:-(alpha|beta|rc)\.([1-9][0-9]{0,4}))?", requested)
    if not match or not isinstance(source_sha, str) or not re.fullmatch('[0-9a-f]{40}', source_sha):
        raise ValueError("Invalid local deployment version or source SHA.")
    base, channel, sequence = match[1], match[5] or 'stable', match[6] or ''
    resolved = deployment_version(base, channel, sequence)
    return dict(schema=3, version=resolved, base_version=base, mode=channel,
                file_version=[*base_numbers(base), int(sequence) if sequence else 0],
                source_sha=source_sha, run_id='', run_number='', attempt=0, tag='')


def parse_build_info(value):
    if (
        not isinstance(value, dict)
        or set(value) != FIELDS
        or type(value["schema"]) is not int
        or value["schema"] not in {1, 2, 3}
    ):
        raise ValueError("Invalid build metadata schema.")
    if value["schema"] == 3:
        expected = make_local_deployment_info(value['version'], value['source_sha'])
        if (value != expected or type(value['attempt']) is not int
                or any(type(n) is not int for n in value['file_version'])):
            raise ValueError("Inconsistent local deployment metadata.")
        return expected
    if value["schema"] == 2:
        sequence = ""
        if value["mode"] != "stable":
            match = re.fullmatch(re.escape(str(value["base_version"])) +
                                 r"-(alpha|beta|rc)\.([1-9][0-9]{0,4})", str(value["version"]))
            if not match or match[1] != value["mode"]:
                raise ValueError("Invalid deployment prerelease identity.")
            sequence = match[2]
        expected = make_deployment_info(value["base_version"], value["mode"], sequence,
                                       value["source_sha"], value["run_id"], value["run_number"], value["attempt"])
        if value != expected or any(type(n) is not int for n in value["file_version"]):
            raise ValueError("Inconsistent deployment metadata.")
        return expected
    if value["mode"] == "local-build":
        requested = str(value["version"]).split("+", 1)[0]
        expected = make_local_package_info(requested, value["source_sha"])
        if value != expected or type(value["attempt"]) is not int or any(type(n) is not int for n in value["file_version"]):
            raise ValueError("Inconsistent local build metadata.")
        return expected
    beta_number = None
    if value["mode"] == "beta":
        match = re.fullmatch(
            re.escape(str(value["base_version"])) + r"-beta-([1-9][0-9]{0,4})",
            str(value["version"]),
        )
        if not match:
            raise ValueError("Invalid beta build identity.")
        beta_number = int(match[1])
    expected = make_build_info(
        value["mode"],
        value["base_version"],
        value["source_sha"],
        value["run_id"],
        value["run_number"],
        value["attempt"],
        beta_number,
    )
    if value != expected or any(type(n) is not int for n in value["file_version"]):
        raise ValueError("Build metadata has inconsistent version fields.")
    return expected


def local_build_info():
    return dict(
        schema=1,
        version="0.0.0-dev.local",
        base_version="0.0.0",
        mode="local",
        file_version=[0, 0, 0, 0],
        source_sha="",
        run_id="",
        run_number="",
        attempt=0,
        tag="",
    )


def read_build_info(path=None, *, frozen=None):
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if path is None:
        path = (
            Path(sys._MEIPASS) / "build-version.json"
            if frozen
            else Path(__file__).resolve().parent / "build/build-version.json"
        )
    path = Path(path)
    if not path.exists() and not frozen:
        return local_build_info()
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ValueError("Required build metadata is missing or unsafe.")
    return parse_build_info(json.loads(path.read_text(encoding="utf-8")))


BUILD_INFO = read_build_info()
VERSION = BUILD_INFO["version"]
FILE_VERSION = tuple(BUILD_INFO["file_version"])
