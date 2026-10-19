"""
In-memory cache for SAP role and module data.
Loaded from a CSV file at startup. Thread-safe atomic cache replacement.
"""
import logging
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

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


_cache = _CacheState()
_load_lock = threading.Lock()


def load_cache() -> None:
    """Read the SAP role CSV and populate the in-memory cache atomically."""
    global _cache

    with _load_lock:
        settings = get_settings()
        csv_path_str = settings.data_csv_path

        if sys.platform != "win32" and csv_path_str.startswith("//"):
            raise RuntimeError(
                "UNC paths (//server/...) are only supported on Windows. "
                "Mount the share to a local path on Linux/macOS."
            )

        csv_path = Path(csv_path_str)
        logger.info("Loading role data from: %s", csv_path)

        if not csv_path.exists():
            raise FileNotFoundError(
                f"CSV file not found: {csv_path}\n"
                "Check the DATA_CSV_PATH value in your .env file."
            )

        df = pd.read_csv(
            csv_path,
            sep=",",
            dtype=str,
            keep_default_na=False,
            encoding="utf-8-sig",
        )

        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(
                f"CSV is missing required columns: {sorted(missing)}\n"
                f"Found columns: {list(df.columns)}"
            )

        logger.info("CSV loaded: %d rows.", len(df))

        raw: dict[str, dict] = {}

        for row in df.to_dict("records"):
            agr_name       = str(row["AGR_NAME"]).strip()       or None
            function_key   = str(row["FUNCTION_KEY"]).strip()   or None
            text           = str(row["TEXT"]).strip()           or None
            child_agr      = str(row["CHILD_AGR"]).strip()      or None
            child_agr_text = str(row["CHILD_AGR_TEXT"]).strip() or None
            tcode          = str(row["TCODE"]).strip()          or None
            ttext          = str(row["TTEXT"]).strip()          or None

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
                    logger.warning("Role %s has tcode %s with no child_agr - skipped.", agr_name, tcode)
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

        _cache = _CacheState(
            roles=new_roles, modules=new_modules, last_loaded=datetime.now(timezone.utc)
        )
        logger.info("Cache loaded: %d roles, %d modules.", len(_cache.roles), len(_cache.modules))


def get_all_roles() -> list[RoleSummary]:
    state = _cache
    return [
        RoleSummary(agr_name=r.agr_name, text=r.text, function_key=r.function_key,
                    module_name=r.module_name, tcode_count=r.tcode_count)
        for r in state.roles.values()
    ]


def get_role_detail(agr_name: str) -> RoleDetail | None:
    return _cache.roles.get(agr_name)


def get_modules() -> list[ModuleInfo]:
    return _cache.modules


def get_last_loaded() -> datetime | None:
    return _cache.last_loaded