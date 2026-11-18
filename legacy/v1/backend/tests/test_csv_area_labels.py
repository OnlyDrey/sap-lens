"""CSV-only module labels preserve graph, palette overrides and source evidence."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache, config
from config_models import AppConfig, ModuleOverride
from module_registry import registry_list, module_definition, discovered_color, REGISTRY


class CsvAreaTests(unittest.TestCase):
    def test_csv_alias_unknown_and_conflict_labels_never_infer_names_or_change_transactions(
        self,
    ):
        with tempfile.TemporaryDirectory() as root, patch.dict(
            os.environ, {"SAP_LENS_CONFIG_DIR": root, "DATA_CSV_PATH": ""}
        ):
            config.get_settings.cache_clear()
            path = Path(root) / "catalogue.csv"
            path.write_text(
                "FUNCTION_KEY,AGR_NAME,CHILD_AGR,CHILD_AGR_TEXT,TCODE\nFinance,ZC:MM:WRONG,ZS:SD:HINT,MM - Not area evidence,FB03\nLOCAL_AREA,ZC:FI:HINT,ZS:FI:HINT,,ME23N\nFI,ZC:MIXED,ZS:SHARED,,FB03\nMM,ZC:MIXED,ZS:SHARED,,ME23N\n"
            )
            state = cache.build_cache(
                str(path),
                AppConfig(
                    module_overrides={
                        "FI": ModuleOverride(
                            color="#123456", icon="Package", enabled=False
                        )
                    }
                ),
            )
            self.assertEqual(state.roles["ZC:MM:WRONG"].function_key, "FI")
            self.assertEqual(
                state.roles["ZC:MM:WRONG"].single_roles[0].function_key, "UNCLASSIFIED"
            )
            self.assertEqual(state.roles["ZC:FI:HINT"].function_key, "UNCLASSIFIED")
            self.assertEqual(state.roles["ZC:MIXED"].function_key, "UNCLASSIFIED")
            self.assertTrue(state.roles["ZC:MIXED"].module_ambiguous)
            self.assertEqual(state.roles["ZC:FI:HINT"].source_modules, ["LOCAL_AREA"])
            self.assertEqual(state.import_report["transaction_assignments"], 4)
            self.assertEqual(state.import_report["relationship_count"], 3)
            self.assertEqual(state.roles["ZC:MIXED"].tcode_count, 2)
            info = next(m for m in state.modules if m.function_key == "FI")
            self.assertEqual(info.color, "#123456")
            self.assertEqual(info.icon, "Package")
            self.assertFalse(info.enabled)
            config.get_settings.cache_clear()

    def test_area_defaults_remain_stable_and_reset_metadata_preserves_custom_values(
        self,
    ):
        items = {
            m["id"]: m for m in registry_list({"FI": ModuleOverride(color="#112233")})
        }
        self.assertEqual(len(items), 49)
        self.assertEqual(items["FI"]["color"], "#112233")
        self.assertEqual(items["FI"]["default_color"], REGISTRY["FI"]["color"])
        self.assertGreaterEqual(len({m["default_color"] for m in items.values()}), 40)
        self.assertEqual(discovered_color("local_fin"), discovered_color(" LOCAL-FIN "))
        self.assertEqual(
            discovered_color("X" * 256 + "Y" * 100_000), discovered_color("X" * 256)
        )
        self.assertEqual(
            module_definition("FI", {"FI": ModuleOverride(color="#3d4d8a")})["color"],
            "#3d4d8a",
        )
