"""Synthetic local access, release and compatibility regressions."""

import asyncio
import csv
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
import cache
import config
from config_models import AppConfig, ImportProfile, UserImportProfile, ModuleOverride
from main import create_app
from portable_config import export_configuration, read_portable, PortableConfig
from role_matching import RoleMatcher, normalize_role, role_scope
from user_access import (
    build_users,
    UserCsvImport,
    parse_release_role,
    sap_date,
    interval_status,
)

FIXTURE = Path(__file__).parent / "fixtures/user-access.csv"
CATALOGUE = "FUNCTION_KEY,AGR_NAME,CHILD_AGR,TCODE\nMM,ZC:MM:BUY:EN*,ZS:BUY,ME23N\nMM,ZC:MM:BUY:*,ZS:BUY,ME23N\nFI,ZC:FI:VIEW:*,ZS:VIEW,ME23N\nFI,ZC:FI:VIEW:*,ZS:VIEW,FB03\n"
H = {"X-SAP-Lens": "test-access"}


class MatcherTests(unittest.TestCase):
    def test_exact_then_most_specific_organizational_prefix(self):
        matcher = RoleMatcher(["ZC:MM:BUY:*", "ZC:MM:BUY:EN*", "ZC:MM:BUY:ENP"])
        self.assertEqual(matcher.match(" zc:mm:buy:enp ").status, "exact")
        for suffix in ["ENO", "ENK", "ENS", "ENOTHER"]:
            self.assertEqual(
                matcher.match("ZC:MM:BUY:" + suffix).candidates, ("ZC:MM:BUY:EN*",)
            )
        self.assertEqual(matcher.match("ZC:MM:BUY:DE1").candidates, ("ZC:MM:BUY:*",))
        self.assertEqual(matcher.match("X:ZC:MM:BUY:ENP").status, "unmapped")

    def test_equal_normalized_patterns_and_exact_names_are_ambiguous(self):
        matcher = RoleMatcher(["ZC:FI:EN*", "zc:fi:en*", "ZO:EXACT", "zo:exact"])
        self.assertEqual(matcher.match("ZC:FI:ENP").status, "ambiguous")
        self.assertEqual(len(matcher.match("ZO:EXACT").candidates), 2)
        self.assertEqual(matcher.match("ZO:EXACT").status, "ambiguous")

    def test_malformed_patterns_and_wildcard_assignments_are_not_expanded(self):
        matcher = RoleMatcher(
            ["*", "ZC:*:BAD", "ZC:X**", "ZC:[AB]*", "ZC:Q?*", "ZC:VALID:*"]
        )
        self.assertEqual(len(matcher.invalid_patterns), 5)
        self.assertEqual(matcher.match("ZC:VALID:*").status, "unmapped")
        self.assertEqual(matcher.match("ZC:VALID:A").status, "wildcard")
        self.assertEqual(matcher.match("ZC:UNKNOWN:A").status, "unmapped")
        self.assertEqual(normalize_role(" zc: a :enp "), "ZC:A:ENP")
        self.assertEqual(role_scope("zo:mm:x"), "release")


class DateReleaseTests(unittest.TestCase):
    def test_sap_dates_open_end_and_unknown_bounds(self):
        self.assertEqual(sap_date("99991231").isoformat(), "9999-12-31")
        self.assertIsNone(sap_date("00000000"))
        from datetime import date

        today = date(2026, 10, 21)
        self.assertEqual(interval_status(None, None, today), "unknown")
        self.assertEqual(interval_status(None, date(2001, 1, 1), today), "expired")
        self.assertEqual(interval_status(date(2999, 1, 1), None, today), "future")
        self.assertEqual(interval_status(date(2000, 1, 1), None, today), "unknown")
        self.assertEqual(interval_status(today, today, today), "active")
        for value in ["01/02/2026", "2026-13-01", "99999999"]:
            with self.assertRaises(ValueError):
                sap_date(value)

    def test_strict_release_structure_keeps_opaque_tokens(self):
        for kind, group, strategy in [
            ("PR", "SH", "N6"),
            ("PR", "SI", "N6"),
            ("PO", "E1", "ND"),
            ("PO", "E2", "ND"),
        ]:
            parsed = parse_release_role(f"ZO:MM:M:{kind}_REL_ST_{group}_{strategy}:ALL")
            self.assertTrue(parsed["parsed"])
            self.assertEqual(parsed["release_group"], group)
            self.assertEqual(parsed["document_type"], kind)
            self.assertEqual(parsed["opaque_scope"], "M")
            self.assertEqual(parsed["opaque_suffix"], "ALL")
        for value in [
            "ZO:MM:M:PR_REL_ST_SH:ALL",
            "ZO:MM:M:PR_REL_ST_SH_N6:ALL:EXTRA",
            "ZO:FI:M:PR_REL_ST_SH_N6:ALL",
            "ZO:UNKNOWN",
            "ZO:MM:M:PR_REL_ST_SH_N6:*",
        ]:
            self.assertFalse(parse_release_role(value)["parsed"])


class UserAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ, {"SAP_LENS_CONFIG_DIR": self.temp.name, "DATA_CSV_PATH": ""}
        )
        self.env.start()
        config.get_settings.cache_clear()
        cache.clear_cache()
        self.catalogue = Path(self.temp.name) / "catalogue.csv"
        self.catalogue.write_text(CATALOGUE)
        self.settings = AppConfig(
            data_csv_path=str(self.catalogue), user_csv_path=str(FIXTURE.resolve())
        )
        self.client = TestClient(
            create_app(session_token="test-access"), base_url="http://127.0.0.1:18743"
        )
        self.client.__enter__()
        config.save_configuration(self.settings, 0)
        self.client.post("/api/refresh", headers=H).raise_for_status()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        config.get_settings.cache_clear()
        cache.clear_cache()
        self.env.stop()
        self.temp.cleanup()

    def get(self, path):
        response = self.client.get("/api/access/" + path, headers=H)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_multiple_groups_and_roles_combine_with_or_within_and_and_between_filters(self):
        names = lambda query: sorted(item["username"] for item in self.get("users?limit=100&" + query)["items"])
        a_or_c = names("groups=GROUP_A&groups=GROUP_C")
        self.assertEqual(a_or_c, sorted(set(names("groups=GROUP_A")) | set(names("groups=GROUP_C"))))
        self.assertIn("DEMO_BETA", a_or_c)
        self.assertNotIn("DEMO_DELTA", a_or_c)
        self.assertEqual(names("group=GROUP_A&groups=GROUP_C"), a_or_c)  # the legacy single value joins the list
        both_roles = names("roles=ZC:MM:BUY:ENP&roles=ZC:FI:VIEW:ENS")
        self.assertEqual(both_roles, sorted(set(names("roles=ZC:MM:BUY:ENP")) | set(names("roles=ZC:FI:VIEW:ENS"))))
        self.assertTrue({"DEMO_ALFA", "DEMO_DELTA"} <= set(both_roles))
        # The group filter applies to the assignment evidence too: DEMO_ALFA holds ENP in GROUP_A only, DEMO_DELTA holds ENS in GROUP_B.
        self.assertEqual(names("roles=ZC:MM:BUY:ENP&roles=ZC:FI:VIEW:ENS&groups=GROUP_B"), ["DEMO_DELTA"])

    def test_all_supported_roles_and_transaction_search_preserve_evidence(self):
        all_roles = self.get("users/DEMO_ALFA?scope=all&show_expired=true&limit=100")
        self.assertTrue(all(a["scope"] in {"business", "release"} for a in all_roles["items"]))
        business = self.get("users/DEMO_ALFA?scope=business&show_expired=true&limit=100")
        release = self.get("users/DEMO_ALFA?scope=release&show_expired=true&limit=100")
        self.assertEqual({a["id"] for a in all_roles["items"]}, {a["id"] for a in business["items"] + release["items"]})
        self.assertTrue(all_roles["data_revision"])
        found = self.get("users/DEMO_ALFA?scope=all&tcode=%20me23n%20")
        self.assertEqual({a["role_name"] for a in found["items"]}, {"ZC:MM:BUY:ENP", "ZC:FI:VIEW:ENO"})
        self.assertTrue(all(a["transaction_roles"] for a in found["items"]))
        self.assertTrue(found["mapping_available"])
        self.assertTrue(all(a["status"] != "expired" for a in found["items"]))
        self.assertEqual(self.get("users/DEMO_ALFA?scope=release&tcode=ME23N")["total"], 0)
        self.assertEqual(self.get("users/DEMO_ALFA?scope=all&tcode=ME23")["total"], 0)
        self.assertEqual(self.get("users/DEMO_BETA?scope=business&tcode=FB03")["total"], 0)

    def test_supported_role_pagination_and_missing_mapping_are_explicit(self):
        path = Path(self.temp.name) / "large-user.csv"
        path.write_text("USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\n" +
                        "".join(f"DEMO_PAGE,ZC:UNMAPPED:{i},G{i % 2},20000101,99991231\n" for i in range(125)) +
                        "DEMO_PAGE,ZD:TECHNICAL,G,20000101,99991231\nDEMO_PAGE,ZZ:OTHER,G,20000101,99991231\n")
        candidate = config.get_settings().model_dump()
        candidate["user_csv_path"] = str(path)
        self.client.post("/api/configuration", headers=H, json=candidate).raise_for_status()
        first = self.get("users/DEMO_PAGE?scope=all&limit=100")
        second = self.get("users/DEMO_PAGE?scope=all&limit=100&offset=100")
        self.assertEqual((first["total"], len(first["items"]), len(second["items"])), (125, 100, 25))
        self.assertEqual(first["data_revision"], second["data_revision"])
        self.assertEqual(len({a["id"] for a in first["items"] + second["items"]}), 125)
        found = self.get("users/DEMO_PAGE?scope=all&tcode=MIGO")
        self.assertEqual(found["total"], 0)
        self.assertEqual(found["unmapped_assignments"], 125)
        self.assertTrue(all(a["role_description"] == "" for a in first["items"]))

    def test_transaction_search_reports_catalogue_unavailable(self):
        candidate = config.get_settings().model_dump()
        candidate["data_csv_path"] = ""
        self.client.post("/api/configuration", headers=H, json=candidate).raise_for_status()
        found = self.get("users/DEMO_ALFA?scope=all&tcode=ME23N")
        self.assertFalse(found["mapping_available"])
        self.assertGreater(found["unmapped_assignments"], 0)
        self.assertEqual(found["items"], [])

    def test_multi_transaction_filters_use_exact_or_before_assignment_pagination(self):
        combined = self.get("users/DEMO_ALFA?scope=all&tcodes=%20me23n%20&tcodes=fb03&tcodes=ME23N&transaction_mode=or")
        first = self.get("users/DEMO_ALFA?scope=all&tcode=ME23N")
        second = self.get("users/DEMO_ALFA?scope=all&tcode=FB03")
        self.assertEqual({a["id"] for a in combined["items"]}, {a["id"] for a in first["items"] + second["items"]})
        self.assertEqual(combined["total"], len(combined["items"]))
        self.assertEqual(self.get("users/DEMO_ALFA?scope=release&tcodes=ME23N")["total"], 0)
        self.assertEqual(self.get("users/DEMO_ALFA?scope=all&tcodes=ME23")["total"], 0)
        for suffix in ['tcodes=' + 'X' * 129, '&'.join('tcodes=T' + str(i) for i in range(22))]:
            self.assertEqual(self.client.get('/api/access/users/DEMO_ALFA?' + suffix, headers=H).status_code, 422)

    def test_catalogue_multi_transaction_filters_are_exact_or_and_other_filters(self):
        response = self.client.get('/api/roles?tcodes=me23n&tcodes=fb03&function_key=FI&search=VIEW', headers=H)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r['agr_name'] for r in response.json()], ['ZC:FI:VIEW:*'])
        self.assertEqual(set(response.json()[0]['matching_tcodes']), {'ME23N', 'FB03'})
        self.assertEqual(self.client.get('/api/roles?tcodes=ME23', headers=H).json(), [])
        self.assertEqual(self.client.get('/api/roles?tcodes=' + 'X' * 129, headers=H).status_code, 422)
        # Legacy prefix lookup is still available to existing callers.
        self.assertTrue(self.client.get('/api/roles?tcode=ME23', headers=H).json())

    def load_navigation_export(self):
        path = Path(self.temp.name) / "navigation.csv"
        path.write_text(
            "USERNAME,ROLE_NAME,USER_GROUP,FIRST_NAME,ROLE_VALID_FROM,ROLE_VALID_TO\n"
            + "".join(f"DEMO_{i:03},ZO:MM:M:PR_REL_ST_G{i:03}_N6:ALL,GROUP_KEEP,Tied,20000101,99991231\n" for i in range(125))
            + "DEMO_HIDDEN,ZO:MM:M:PR_REL_ST_HIDDEN_N6:ALL,GROUP_OTHER,Tied,20000101,99991231\n"
        )
        candidate = config.get_settings().model_dump()
        candidate["user_csv_path"] = str(path)
        self.client.post("/api/configuration", headers=H, json=candidate).raise_for_status()

    def assert_navigation_matches_list(self, path, params, key):
        from urllib.parse import urlencode
        first = self.get(path + "?" + urlencode(dict(params, limit=100)))
        second = self.get(path + "?" + urlencode(dict(params, limit=100, offset=100)))
        rows = first["items"] + second["items"]
        for index in sorted({0, 24, 25, 49, 50, 99, 100, len(rows) - 1}):
            if index < 0 or index >= len(rows): continue
            anchored = self.get(path + "?" + urlencode(dict(params, anchor=rows[index][key].lower(), offset=0, limit=1)))
            self.assertEqual(len(anchored["items"]), 1)
            self.assertNotIn("matrix", anchored)  # No unrelated aggregate transfer for detail navigation.
            self.assertEqual(anchored["navigation"], dict(
                index=index, total=len(rows),
                previous=rows[index - 1][key] if index else None,
                next=rows[index + 1][key] if index + 1 < len(rows) else None,
            ))

    def test_user_navigation_crosses_all_pages_with_filters_and_both_directions(self):
        self.load_navigation_export()
        for descending in (False, True):
            self.assert_navigation_matches_list("users", dict(group="GROUP_KEEP", search="demo", sort="first_name", descending=str(descending).lower()), "username")

    def test_release_navigation_crosses_all_pages_and_uses_existing_tie_breaks(self):
        self.load_navigation_export()
        for descending in (False, True):
            self.assert_navigation_matches_list("releases", dict(group="GROUP_KEEP", document_type="PR", strategy="N6", role="ZO:MM", username="DEMO_", status="active", sort="assigned_users", descending=str(descending).lower()), "role_name")

    def test_navigation_all_sort_fields_follow_the_same_filtered_list(self):
        for path, key, sorts in [
            ("users", "username", ["username", "group", "first_name", "last_name", "email", "account_status", "relevant_roles"]),
            ("releases", "role_name", ["role_name", "document_type", "release_group", "release_strategy", "assigned_users"]),
        ]:
            for sort in sorts:
                for descending in ("true", "false"):
                    with self.subTest(path=path, sort=sort, descending=descending):
                        self.assert_navigation_matches_list(path, dict(sort=sort, descending=descending), key)

    def test_navigation_respects_evidence_status_and_classification_filters(self):
        for params in [dict(role="ZC:MM:BUY:EN*"), dict(tcode="FB03"), dict(group="GROUP_B"), dict(status="future"), dict(status="unknown")]:
            self.assert_navigation_matches_list("users", params, "username")
        for params in [dict(status="all"), dict(status="future"), dict(status="expired"), dict(document_type="Unparsed", status="all"), dict(group="GROUP_A", document_type="PR", release_group="SH", strategy="N6")]:
            self.assert_navigation_matches_list("releases", params, "role_name")

    def test_navigation_missing_filtered_or_removed_anchor_never_substitutes_a_record(self):
        for path, anchor in [("users", "DEMO_ALFA"), ("releases", "ZO:MM:M:PR_REL_ST_SH_N6:ALL")]:
            from urllib.parse import urlencode
            query = urlencode(dict(anchor=anchor, group="NO_SUCH_GROUP", limit=1))
            self.assertEqual(self.get(path + "?" + query)["navigation"], dict(index=None, total=0, previous=None, next=None))
        cache.clear_cache()
        self.assertEqual(self.get("users?anchor=DEMO_ALFA&limit=1")["navigation"]["index"], None)
        self.assertEqual(self.client.get("/api/access/users/DEMO_ALFA", headers=H).status_code, 404)
        self.assertEqual(self.get("releases?anchor=ZO:REMOVED&limit=1")["navigation"]["total"], 0)

    def test_navigation_requires_session_and_validates_bounded_inputs(self):
        for path in ("users", "releases"):
            self.assertEqual(self.client.get("/api/access/" + path + "?anchor=DEMO").status_code, 403)
            self.assertEqual(self.client.get("/api/access/" + path, params={"anchor":"x"*513}, headers=H).status_code, 422)
            self.assertNotIn("navigation", self.get(path))

    def test_release_options_use_all_records_bounded_search_and_exact_values(self):
        self.load_navigation_export()
        result = self.get("release-options?field=release_group&limit=10")
        self.assertEqual(result['total'], 126)
        self.assertEqual(len(result['items']), 10)
        self.assertTrue(result['has_more'])
        self.assertEqual(self.get("release-options?field=release_group&search=g124")['items'], ['G124'])
        self.assertFalse(self.get("release-options?field=release_group&selected=REMOVED")['selected_available'])
        self.assertTrue(self.get("release-options?field=username&selected=demo_12")['selected_available'])

    def test_release_options_hierarchy_does_not_filter_ancestors_or_siblings(self):
        result = self.get('release-options?field=group&group=NO_SUCH&document_type=PO&release_group=NO_SUCH&strategy=NO_SUCH')
        self.assertEqual(result['items'], ['GROUP_A', 'GROUP_B'])
        self.assertEqual(self.get('release-options?field=release_group&document_type=PO')['items'], ['E1'])
        self.assertEqual(self.get('release-options?field=strategy&document_type=PR&release_group=SH')['items'], ['N6'])
        self.assertEqual(self.get('release-options?field=role&document_type=PO')['items'], ['ZO:MM:M:PO_REL_ST_E1_ND:ALL'])
        self.assertEqual(self.get('release-options?field=username&group=GROUP_B')['items'], ['DEMO_ALFA'])
        self.assertEqual(self.get('release-options?field=document_type&status=all')['items'], ['PO', 'PR', 'Unparsed'])
        self.assertEqual(self.get('release-options?field=release_group&status=future')['items'], ['SI'])
        self.assertEqual(self.get('release-options?field=release_group&document_type=Unparsed&status=all')['items'], [])

    def test_release_options_are_guarded_bounded_and_reload_from_current_generation(self):
        self.assertEqual(self.client.get('/api/access/release-options?field=role').status_code, 403)
        for params in [dict(field='invalid'), dict(field='role', limit=101), dict(field='role', search='x'*513)]:
            self.assertEqual(self.client.get('/api/access/release-options', params=params, headers=H).status_code, 422)
        cache.clear_cache()
        self.assertEqual(self.get('release-options?field=role')['items'], [])
        self.client.post('/api/refresh', headers=H).raise_for_status()
        self.assertTrue(self.get('release-options?field=role')['items'])

    def test_diagnostics_distinguishes_configured_and_loaded_sources_without_exporting_paths(self):
        local = self.client.get('/api/diagnostics', headers=H).json()
        sources = {source['id']: source for source in local['sources']}
        self.assertEqual(sources['roles']['records'], 3)
        self.assertEqual(sources['users']['records'], 7)
        self.assertEqual(sources['users']['loaded_path'], str(FIXTURE.resolve()))
        self.assertTrue(all(sources[key]['last_successful_load'] for key in ('roles','users')))
        self.assertFalse(sources['employees']['loaded'])
        self.assertEqual(sources['users']['availability'], 'available_at_last_load')
        exported = self.client.get('/api/diagnostics/export', headers=H).json()
        raw = json.dumps(exported)
        for private in [str(self.catalogue), str(FIXTURE.resolve()), 'DEMO_ALFA', 'example.invalid', 'configured_path', 'loaded_path', 'attempted_path']:
            self.assertNotIn(private, raw)

    def test_failed_source_refresh_retains_previous_generation_and_redacts_error(self):
        old = cache.get_snapshot()
        candidate = config.get_settings().model_copy(update={'user_csv_path': str(Path(self.temp.name)/'missing-private-users.csv')})
        config.save_configuration(candidate, candidate.revision)
        response=self.client.post('/api/refresh', headers=H)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['refresh']['status'], 'partial')
        self.assertIs(cache.get_snapshot(), old)
        sources = {source['id']:source for source in self.client.get('/api/diagnostics', headers=H).json()['sources']}
        self.assertEqual(sources['users']['availability'], 'missing')
        self.assertEqual(sources['users']['error'], 'missing')
        self.assertEqual(sources['users']['loaded_path'], str(FIXTURE.resolve()))
        self.assertNotEqual(sources['users']['configured_path'], sources['users']['loaded_path'])
        self.assertIsNone(sources['roles']['error'])
        raw = json.dumps(self.client.get('/api/diagnostics/export', headers=H).json())
        self.assertNotIn('missing-private-users.csv', raw)
        self.assertNotIn(self.temp.name, raw)

    def test_diagnostics_permission_errors_are_static_and_successful_refresh_clears_them(self):
        with patch('cache.build_users', side_effect=PermissionError('private username and filename must not escape')):
            response=self.client.post('/api/refresh', headers=H)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['refresh']['status'], 'partial')
        sources = self.client.get('/api/diagnostics/export', headers=H).json()['sources']
        self.assertEqual(sources[1]['error'], 'access_denied')
        self.assertNotIn('private username', json.dumps(sources))
        self.client.post('/api/refresh', headers=H).raise_for_status()
        self.assertIsNone(self.client.get('/api/diagnostics', headers=H).json()['sources'][1]['error'])

    def test_user_only_diagnostics_does_not_claim_a_catalogue_was_loaded(self):
        candidate = config.get_settings().model_copy(update={'data_csv_path': ''})
        config.save_configuration(candidate, candidate.revision)
        self.client.post('/api/refresh', headers=H).raise_for_status()
        sources = self.client.get('/api/diagnostics', headers=H).json()['sources']
        self.assertFalse(sources[0]['configured'])
        self.assertFalse(sources[0]['loaded'])
        self.assertIsNone(sources[0]['last_successful_load'])
        self.assertTrue(sources[1]['loaded'])
        self.assertEqual(sources[1]['records'], 7)

    def test_directory_identity_duplicate_intervals_groups_and_optional_fields(self):
        state = cache.get_snapshot().users
        self.assertEqual(len(state.users), 7)
        self.assertEqual(state.report["duplicate_rows"], 1)
        self.assertEqual(state.report["assignments"], 13)
        alfa = state.users["DEMO_ALFA"]
        self.assertEqual(alfa["groups"], ["GROUP_A", "GROUP_B"])
        self.assertEqual(len(alfa["assignments"]), 5)
        self.assertEqual(len(state.users["DEMO_EMPTY"]["assignments"]), 0)
        self.assertEqual(state.report["samples"], [])

    def test_users_search_sort_pagination_directory_only_and_account_lock(self):
        users = self.get("users?limit=2&sort=username&descending=true")
        self.assertEqual(users["total"], 7)
        self.assertEqual(len(users["items"]), 2)
        self.assertEqual(
            self.get("users?search=beta%40example.invalid")["items"][0]["username"],
            "DEMO_BETA",
        )
        self.assertEqual(self.get("users?group=GROUP_B")["total"], 3)
        beta = self.get("users/DEMO_BETA")
        self.assertEqual(beta["lock_status"], "Locked")
        self.assertEqual(beta["account_status"], "active")
        empty = self.get("users/DEMO_EMPTY")
        self.assertEqual(empty["total"], 0)

    def test_validity_filters_are_separate_and_all_records_remain_available(self):
        gamma = self.get("users/DEMO_GAMMA")
        self.assertEqual(gamma["total"], 1)
        self.assertEqual(gamma["items"][0]["status"], "future")
        self.assertEqual(gamma["items"][0]["account_status"], "expired")
        self.assertEqual(self.get("users/DEMO_GAMMA?show_expired=true")["total"], 2)
        self.assertEqual(self.get("users/DEMO_GAMMA?status=expired")["total"], 1)
        delta = self.get("users/DEMO_DELTA?scope=business")["items"][0]
        self.assertEqual(delta["status"], "unknown")
        self.assertEqual(delta["match_status"], "wildcard")

    def test_role_and_transaction_reverse_lookup_deduplicates_users_preserves_evidence(
        self,
    ):
        result = self.get("users?tcode=ME23N")
        self.assertEqual(
            {u["username"] for u in result["items"]}, {"DEMO_ALFA", "DEMO_DELTA"}
        )
        self.assertEqual(self.get("users?role=ZC%3AMM%3ABUY%3AEN%2A")["total"], 1)
        assignments = self.get("users/DEMO_ALFA?scope=business")["items"]
        self.assertEqual(len(assignments), 2)
        self.assertTrue(all("ME23N" in a["tcodes"] for a in assignments))
        unmapped = self.get("users/DEMO_UNMAPPED")["items"][0]
        self.assertEqual(unmapped["match_status"], "unmapped")
        self.assertEqual(unmapped["tcodes"], [])

    def test_release_matrix_distinct_counts_group_comparison_and_drilldown(self):
        releases = self.get("releases")
        pr = next(c for c in releases["matrix"] if c["document_type"] == "PR")
        self.assertEqual(pr["user_count"], 2)
        po = next(c for c in releases["matrix"] if c["document_type"] == "PO")
        self.assertEqual(po["user_count"], 1)
        compared = self.get("releases?document_type=PR&group_by_user_group=true")[
            "matrix"
        ]
        self.assertEqual(
            {c["user_group"]: c["user_count"] for c in compared},
            {"GROUP_A": 2, "GROUP_B": 1},
        )
        drill = self.get(
            "release-assignments?document_type=PR&release_group=SH&strategy=N6"
        )
        self.assertEqual(drill["distinct_users"], 2)
        self.assertEqual(drill["total"], 4)
        self.assertEqual(
            self.get("release-assignments?document_type=PR&group=GROUP_B")[
                "distinct_users"
            ],
            1,
        )
        self.assertEqual(
            self.get("releases?document_type=Unparsed&status=all")["total"], 1
        )
        self.assertEqual(self.get("releases?status=future")["total"], 1)
        self.assertEqual(
            self.get(
                "release-assignments?document_type=PR&release_group=SH&strategy=N6&username=ALFA"
            )["distinct_users"],
            1,
        )

    def test_preview_and_failed_refresh_do_not_replace_settings_or_generation(self):
        before = cache.get_snapshot()
        saved = config.get_settings().model_dump()
        bad = Path(self.temp.name) / "bad.csv"
        bad.write_text("USERNAME,ROLE_NAME,ROLE_VALID_FROM\nDEMO_BAD,ZC:X,not-a-date\n")
        response = self.client.post(
            "/api/user-import/preview", headers=H, json={"data_csv_path": str(bad)}
        )
        self.assertEqual(response.status_code, 400)
        candidate = config.get_settings().model_dump()
        candidate["user_csv_path"] = str(bad)
        self.assertEqual(
            self.client.post(
                "/api/configuration", headers=H, json=candidate
            ).status_code,
            400,
        )
        self.assertIs(cache.get_snapshot(), before)
        self.assertEqual(config.get_settings().model_dump(), saved)
        preview = self.client.post(
            "/api/user-import/preview",
            headers=H,
            json={"data_csv_path": str(FIXTURE.resolve())},
        )
        self.assertEqual(preview.status_code, 200)
        samples = preview.json()["samples"]
        self.assertGreater(len(samples), 0)
        self.assertLessEqual(len(samples), 20)
        self.assertEqual(set(samples[0]), {"USERNAME", "ROLE_NAME", "USER_GROUP", "FIRST_NAME", "LAST_NAME", "EMAIL", "ROLE_VALID_FROM", "ROLE_VALID_TO"})
        self.assertEqual(before.users.report["samples"], [])
        self.assertIs(cache.get_snapshot(), before)

    def test_no_catalogue_does_not_invent_access_and_relationships_remain(self):
        roles = cache.get_snapshot().roles
        self.assertEqual(roles["ZC:MM:BUY:EN*"].single_roles[0].child_agr, "ZS:BUY")
        self.assertEqual(
            roles["ZC:MM:BUY:EN*"].single_roles[0].function_key, "UNCLASSIFIED"
        )
        state = build_users(
            str(FIXTURE), UserImportProfile(id="default", name="Standard"), {}
        )
        self.assertTrue(
            all(
                not a["tcodes"] and a["match_status"] == "unmapped"
                for a in state.assignments
            )
        )

    def test_same_name_email_never_merges_users_and_ambiguous_catalogue_never_infers_transactions(
        self,
    ):
        path = Path(self.temp.name) / "identities.csv"
        path.write_text(
            "USERNAME,ROLE_NAME,FIRST_NAME,EMAIL\nDEMO A,ZC:MM:BUY:ENP,Same,same@example.invalid\nDEMOA,ZC:MM:BUY:ENP,Same,same@example.invalid\n"
        )
        catalogue = dict(cache.get_snapshot().roles)
        catalogue["zc:mm:buy:en*"] = catalogue["ZC:MM:BUY:EN*"]
        state = build_users(
            str(path), UserImportProfile(id="default", name="Standard"), catalogue
        )
        self.assertEqual(len(state.users), 2)
        self.assertTrue(
            all(
                a["match_status"] == "ambiguous" and not a["tcodes"]
                for a in state.assignments
            )
        )

    def test_unknown_source_group_cell_drills_only_ungrouped_records(self):
        path = Path(self.temp.name) / "groups.csv"
        path.write_text(
            "USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\nDEMO_ONE,ZO:MM:M:PR_REL_ST_SH_N6:ALL,,20000101,99991231\nDEMO_TWO,ZO:MM:M:PR_REL_ST_SH_N6:ALL,GROUP_A,20000101,99991231\n"
        )
        candidate = config.get_settings().model_dump()
        candidate["user_csv_path"] = str(path)
        self.assertEqual(
            self.client.post(
                "/api/configuration", headers=H, json=candidate
            ).status_code,
            200,
        )
        matrix = self.get("releases?group_by_user_group=true")["matrix"]
        self.assertEqual(len(matrix), 2)
        drill = self.get(
            "release-assignments?document_type=PR&release_group=SH&strategy=N6&ungrouped=true"
        )
        self.assertEqual(drill["distinct_users"], 1)
        self.assertEqual(drill["items"][0]["username"], "DEMO_ONE")

    def test_paged_users_and_startup_with_only_the_user_source(self):
        candidate = config.get_settings().model_copy(deep=True)
        candidate.data_csv_path = ""
        config.save_configuration(candidate, config.get_settings().revision)
        cache.clear_cache()
        import time

        with TestClient(
            create_app(session_token="test-access"), base_url="http://127.0.0.1:18743"
        ) as client:
            deadline = time.monotonic() + 5
            while (
                client.get("/health").json()["status"] == "loading"
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            self.assertEqual(client.get("/health").json()["status"], "ok")
            response = client.get(
                "/api/access/users?offset=5&limit=2", headers=H
            ).json()
            self.assertEqual(len(response["items"]), 2)
            self.assertEqual(response["total"], 7)
            self.assertFalse(response["catalogue_loaded"])
            self.assertTrue(
                all(
                    a["match_status"] == "unmapped"
                    for a in cache.get_snapshot().users.assignments
                )
            )

    def test_matrix_and_account_evidence_are_bounded_without_dropping_records(self):
        path = Path(self.temp.name) / "large.csv"
        path.write_text(
            "USERNAME,ROLE_NAME,ROLE_VALID_FROM,ROLE_VALID_TO\n"
            + "".join(
                f"DEMO_ONE,ZO:MM:M:PR_REL_ST_G{i}_N6:ALL,20000101,99991231\n"
                for i in range(201)
            )
        )
        candidate = config.get_settings().model_dump()
        candidate["user_csv_path"] = str(path)
        self.assertEqual(
            self.client.post(
                "/api/configuration", headers=H, json=candidate
            ).status_code,
            200,
        )
        first = self.get("releases")
        last = self.get("releases?matrix_offset=200")
        self.assertEqual(first["matrix_total"], 201)
        self.assertEqual(len(first["matrix"]), 200)
        self.assertEqual(len(last["matrix"]), 1)
        complete=self.get("releases?matrix_complete=true")
        self.assertEqual(len(complete["matrix"]),201)
        self.assertEqual(complete["matrix"],first["matrix"]+last["matrix"])
        path.write_text(
            "USERNAME,USER_GROUP,USER_VALID_FROM,USER_VALID_TO\n"
            + "".join(f"DEMO_ONE,GROUP_{i},20000101,99991231\n" for i in range(51))
        )
        self.assertEqual(self.client.post("/api/refresh", headers=H).status_code, 200)
        first = self.get("users/DEMO_ONE")
        last = self.get("users/DEMO_ONE?account_offset=50")
        self.assertEqual(first["account_total"], 51)
        self.assertEqual(len(first["accounts"]), 50)
        self.assertEqual(len(last["accounts"]), 1)

    def test_catalogue_role_with_literal_slash_resolves_to_details(self):
        self.catalogue.write_text(CATALOGUE + "MM,ZC:MM:PART/EN*,ZS:PART,ME23N\n")
        self.assertEqual(self.client.post("/api/refresh", headers=H).status_code, 200)
        response = self.client.get("/api/roles/ZC%3AMM%3APART%2FEN%2A", headers=H)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["agr_name"], "ZC:MM:PART/EN*")

    def test_contact_variants_are_paginated_without_merging_users_or_hiding_records(
        self,
    ):
        path = Path(self.temp.name) / "contacts.csv"
        path.write_text(
            "USERNAME,FIRST_NAME,EMAIL\n"
            + "".join(
                f"DEMO_ONE,Variant{i},variant{i}@example.invalid\n" for i in range(101)
            )
        )
        candidate = config.get_settings().model_dump()
        candidate["user_csv_path"] = str(path)
        self.assertEqual(
            self.client.post(
                "/api/configuration", headers=H, json=candidate
            ).status_code,
            200,
        )
        first = self.get("users/DEMO_ONE")
        last = self.get("users/DEMO_ONE?name_offset=100&email_offset=100")
        self.assertEqual(first["names_total"], 101)
        self.assertEqual(len(first["names"]), 100)
        self.assertEqual(first["emails_total"], 101)
        self.assertEqual(len(last["emails"]), 1)
        self.assertEqual(len(last["names"]), 1)

    def test_large_transaction_evidence_is_bounded_but_reverse_lookup_remains_complete(
        self,
    ):
        self.catalogue.write_text(
            CATALOGUE
            + "".join(f"MM,ZC:MM:BUY:EN*,ZS:BUY,DEMO_T{i:03}\n" for i in range(200))
        )
        self.assertEqual(self.client.post("/api/refresh", headers=H).status_code, 200)
        evidence = next(
            a
            for a in self.get("users/DEMO_ALFA?scope=business")["items"]
            if a["role_name"] == "ZC:MM:BUY:ENP"
        )
        self.assertEqual(len(evidence["tcodes"]), 100)
        self.assertEqual(evidence["tcode_count"], 201)
        self.assertEqual(self.get("users?tcode=DEMO_T199")["total"], 1)
        self.assertEqual(
            len(
                cache.get_snapshot().users.users["DEMO_ALFA"]["assignments"][0][
                    "tcodes"
                ]
            ),
            201,
        )

    def test_local_security_boundaries_query_bounds_and_removed_preview(self):
        self.assertEqual(self.client.get("/api/access/users").status_code, 403)
        self.assertEqual(
            self.client.get(
                "/api/access/users", headers={**H, "Origin": "http://evil.invalid"}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get("/api/access/users?limit=101", headers=H).status_code, 422
        )
        self.assertIn(
            self.client.post(
                "/api/classification/preview", headers=H, json={}
            ).status_code,
            (404, 405),
        )
        self.assertEqual(
            self.client.get("/api/access/users", headers=H).headers["cache-control"],
            "no-store",
        )

    def test_both_source_presets_persist_and_active_deletion_restores_default(self):
        candidate = config.get_settings().model_dump()
        candidate["import_profiles"].append(
            ImportProfile(id="custom", name="Custom role").model_dump()
        )
        candidate["user_import_profiles"].append(
            UserImportProfile(id="custom", name="Custom user").model_dump()
        )
        candidate["active_import"] = candidate["active_user_import"] = "custom"
        response = self.client.post("/api/configuration", headers=H, json=candidate)
        self.assertEqual(response.status_code, 200)
        candidate = response.json()["settings"]
        candidate["import_profiles"] = [
            p for p in candidate["import_profiles"] if p["id"] != "custom"
        ]
        candidate["user_import_profiles"] = [
            p for p in candidate["user_import_profiles"] if p["id"] != "custom"
        ]
        response = self.client.post("/api/configuration", headers=H, json=candidate)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["settings"]["active_import"], "default")
        self.assertEqual(response.json()["settings"]["active_user_import"], "default")
        self.assertTrue(self.catalogue.exists())
        self.assertEqual(len(cache.get_snapshot().users.users), 7)
        config.get_settings.cache_clear()
        self.assertEqual(config.get_settings().user_csv_path, str(FIXTURE.resolve()))

    def test_legacy_rules_archived_without_execution_preferences_and_exports_preserved(
        self,
    ):
        legacy = config.get_settings().model_dump()
        legacy["schema_version"] = 2
        legacy["classification_profiles"] = [
            {"id": "broken", "rules": [{"pattern": "["}]}
        ]
        legacy["active_classification"] = "missing"
        legacy["module_overrides"] = {
            "FI": {"color": "#123456", "icon": "Package", "enabled": False}
        }
        settings = AppConfig.model_validate(legacy)
        self.assertEqual(settings.schema_version, 3)
        self.assertEqual(
            settings.legacy_classification["active_classification"], "missing"
        )
        self.assertEqual(settings.module_overrides["FI"].color, "#123456")
        private = export_configuration(settings, True)
        public = export_configuration(settings)
        self.assertEqual(private["settings"]["data_csv_path"], "")
        self.assertEqual(private["settings"]["user_csv_path"], "")
        self.assertIsNone(public["settings"]["legacy_classification"])
        restored = read_portable(
            PortableConfig.model_validate(private), str(self.catalogue), str(FIXTURE)
        )
        self.assertEqual(restored.user_csv_path, str(FIXTURE))
        self.assertEqual(restored.module_overrides, settings.module_overrides)


class UserCsvFormatTests(unittest.TestCase):
    def test_mapping_delimiter_encoding_detection_and_required_username(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mapped.csv"
            path.write_bytes(
                "User;Assigned;Prénom\nDEMO_TEST;ZC:FI:ENO;Éxample\n".encode("cp1252")
            )
            profile = UserImportProfile(
                id="mapped",
                name="Synthetic",
                mapping={
                    "USERNAME": "User",
                    "ROLE_NAME": "Assigned",
                    "FIRST_NAME": "Prénom",
                },
            )
            parser = UserCsvImport(path, profile)
            self.assertEqual(parser.inspect_header()["encoding"], "cp1252")
            self.assertEqual(parser.inspect_header()["delimiter"], ";")
            result = build_users(str(path), profile, {})
            self.assertEqual(result.users["DEMO_TEST"]["names"], [("Éxample", "")])
            path.write_text("ROLE_NAME\nZC:FI:ENO\n")
            with self.assertRaises(ValueError):
                list(
                    UserCsvImport(
                        path, UserImportProfile(id="default", name="Standard")
                    ).records()
                )

    def test_source_byte_row_and_distinct_user_limits_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "limited.csv"
            path.write_text("USERNAME\nDEMO_ONE\nDEMO_TWO\nDEMO_THREE\n")
            profile = UserImportProfile(id="default", name="Standard")
            for target in [
                ("csv_import.MAX_BYTES", 10),
                ("csv_import.MAX_ROWS", 2),
                ("user_access.MAX_USERS", 2),
            ]:
                with patch(*target), self.assertRaises(ValueError):
                    build_users(str(path), profile, {})

    def test_reversed_dates_invalid_headers_and_width_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "invalid.csv"
            profile = UserImportProfile(id="default", name="Standard")
            for data in [
                "USERNAME,USERNAME\nDEMO_A,DEMO_B\n",
                "USERNAME,ROLE_NAME\nDEMO_A\n",
                "USERNAME,ROLE_NAME\nDEMO_A,ZC:FI:*\n",
                "USERNAME,ROLE_VALID_FROM,ROLE_VALID_TO\nDEMO_A,20260102,20260101\n",
            ]:
                path.write_text(data)
                with self.assertRaises(ValueError):
                    build_users(str(path), profile, {})
