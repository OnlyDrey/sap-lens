"""
In-memory cache for SAP role and module data.
Loaded from a CSV file at startup. Thread-safe atomic cache replacement.
"""
import csv
import logging
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from config import get_settings
from models import ModuleInfo, RoleDetail, RoleSummary, SingleRole, TCode

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {
    "FUNCTION_KEY", "AGR_NAME", "TEXT",
    "CHILD_AGR", "CHILD_AGR_TEXT", "TCODE", "TTEXT",
}

MODULE_MAP: dict[str, str] = {
    "BC": "Basis", "CO": "Controlling", "FI": "Finance",
    "HR": "Human Resources", "MM": "Materials Management",
    "PM": "Plant Maintenance", "PP": "Production Planning",
    "PS": "Project System", "QM": "Quality Management",
    "SD": "Sales & Distribution",
}


@dataclass
class _CacheState:
    roles: dict[str, RoleDetail] = field(default_factory=dict)
    modules: list[ModuleInfo] = field(default_factory=list)
    last_loaded: datetime | None = None
    summaries: list[RoleSummary] = field(default_factory=list)
    tcode_index: dict[str, set[str]] = field(default_factory=dict)


_cache = _CacheState()
_load_lock = threading.Lock()


def _read_rows(path: Path):
    # Stream the seven needed columns; avoid a dataframe and a second copy of
    # every row. csv handles BOMs, quoted commas and multiline descriptions.
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, strict=True)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing required columns: {sorted(missing)}")
        columns = ['AGR_NAME', 'FUNCTION_KEY', 'TEXT', 'CHILD_AGR', 'CHILD_AGR_TEXT', 'TCODE', 'TTEXT']
        for row in reader:
            yield tuple((row.get(column) or '').strip() or None for column in columns)


def load_cache(path: str | None = None, before_commit: Callable[[], None] | None = None) -> None:
    """Read the SAP role CSV and populate the in-memory cache atomically."""
    global _cache

    with _load_lock:
        settings = get_settings()
        csv_path_str = path if path is not None else settings.data_csv_path
        if not csv_path_str:
            raise ValueError("Choose a SAP role CSV in Settings.")
        if "://" in csv_path_str:
            raise ValueError("Use a local CSV path or a mounted network share, not a URL.")

        if sys.platform != "win32" and csv_path_str.startswith("//"):
            raise RuntimeError(
                "UNC paths (//server/...) are only supported on Windows. "
                "Mount the share to a local path on Linux/macOS."
            )

        csv_path = Path(csv_path_str).expanduser()
        if csv_path.suffix.lower() != ".csv":
            raise ValueError("Select a .csv file.")
        logger.info("Loading SAP role catalog")

        if not csv_path.exists():
            raise FileNotFoundError(
                f"CSV file not found: {csv_path}\n"
                "Check the DATA_CSV_PATH value in your .env file."
            )

        raw: dict[str, dict] = {}
        for values in _read_rows(csv_path):
            agr_name, function_key, text, child_agr, child_agr_text, tcode, ttext = values

            if not agr_name:
                continue

            if agr_name not in raw:
                raw[agr_name] = {"text": text, "function_key": function_key, "single_roles": {}}
            else:
                if text and not raw[agr_name]["text"]:
                    raw[agr_name]["text"] = text
                if function_key and not raw[agr_name]["function_key"]:
                    raw[agr_name]["function_key"] = function_key

            if not child_agr:
                if tcode:
                    logger.warning("Ignored a transaction assignment without a child role")
                continue

            if child_agr not in raw[agr_name]["single_roles"]:
                raw[agr_name]["single_roles"][child_agr] = {
                    "child_agr_text": child_agr_text, "tcode_objects": {}
                }

            if not tcode:
                continue

            sr = raw[agr_name]["single_roles"][child_agr]
            if tcode not in sr["tcode_objects"]:
                sr["tcode_objects"][tcode] = TCode(tcode=tcode, ttext=ttext or None)

        new_roles: dict[str, RoleDetail] = {}
        for agr_name, data in raw.items():
            fkey: str | None = data["function_key"]
            module_name: str | None = MODULE_MAP.get(fkey, fkey) if fkey else None

            single_roles_list: list[SingleRole] = [
                SingleRole(
                    child_agr=k,
                    child_agr_text=v["child_agr_text"],
                    tcodes=list(v["tcode_objects"].values()),
                )
                for k, v in data["single_roles"].items()
            ]

            all_tcodes: set[str] = set()
            for sr in single_roles_list:
                all_tcodes.update(t.tcode for t in sr.tcodes)

            new_roles[agr_name] = RoleDetail(
                agr_name=agr_name, text=data["text"], function_key=fkey,
                module_name=module_name, tcode_count=len(all_tcodes),
                single_roles=single_roles_list,
            )

        seen: set[str] = set()
        new_modules: list[ModuleInfo] = []
        for role in new_roles.values():
            fk = role.function_key
            if fk and fk not in seen:
                seen.add(fk)
                new_modules.append(ModuleInfo(function_key=fk, module_name=MODULE_MAP.get(fk, fk)))
        new_modules.sort(key=lambda m: m.function_key)

        summaries = [
            RoleSummary(agr_name=r.agr_name, text=r.text, function_key=r.function_key,
                        module_name=r.module_name, tcode_count=r.tcode_count,
                        single_role_count=len(r.single_roles))
            for r in new_roles.values()
        ]
        index: dict[str, set[str]] = {}
        for role in new_roles.values():
            for single in role.single_roles:
                for tc in single.tcodes:
                    index.setdefault(tc.tcode.upper(), set()).add(role.agr_name)
        # Persist settings only after validation; readers retain the previous complete state
        # if reading, validation or persistence fails.
        if before_commit:
            before_commit()
        _cache = _CacheState(
            roles=new_roles, modules=new_modules, last_loaded=datetime.now(timezone.utc),
            summaries=summaries, tcode_index=index,
        )
        logger.info("Cache loaded: %d roles, %d modules.", len(_cache.roles), len(_cache.modules))


def get_all_roles() -> list[RoleSummary]:
    return _cache.summaries


def get_snapshot() -> _CacheState:
    """Hold one consistent generation for the lifetime of a request."""
    return _cache


def get_role_detail(agr_name: str) -> RoleDetail | None:
    return _cache.roles.get(agr_name)


def get_modules() -> list[ModuleInfo]:
    return _cache.modules


def get_last_loaded() -> datetime | None:
    return _cache.last_loaded