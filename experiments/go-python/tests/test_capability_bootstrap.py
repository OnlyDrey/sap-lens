"""Reproduction of the Phase 0 finding: can a local process obtain the session capability without an authenticated application handoff?

Synthetic data only; the backend is started with an isolated data directory by the Go host. These tests characterise CURRENT behaviour of the unchanged
SAP Lens backend (`browser_access=True`). Tests marked expectedFailure describe the behaviour a remediation must provide; when a remediation lands they
start passing and the decorator must be removed.
"""
import json
import unittest

import support
from support import NAVIGATE, Host, request


def setUpModule():
    support.need_runtime(None)


def capability_from(body):
    marker = b"'sap-lens-session',\""
    if marker not in body:
        return None
    return body.split(marker)[1].split(b'"')[0].decode()


class Bootstrap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.host = Host().start()

    @classmethod
    def tearDownClass(cls):
        cls.host.process.terminate()
        cls.host.process.wait(timeout=15)
        cls.host.__exit__()

    def get(self, headers):
        return request(self.host.url + '/', headers)

    # ---- characterisation of today's behaviour -----------------------------------------------------------------------------------------
    def test_finding_any_local_client_can_obtain_and_use_the_capability(self):
        """FINDING F1. No browser, no handoff: a plain HTTP client that sends the navigation headers gets a working capability."""
        status, body = self.get(NAVIGATE)
        capability = capability_from(body)
        self.assertEqual(status, 200)
        self.assertIsNotNone(capability)
        self.assertEqual(request(self.host.url + '/api/settings', {'X-SAP-Lens': capability})[0], 200)

    def test_capability_is_not_in_the_document_without_navigation_headers(self):
        self.assertIsNone(capability_from(self.get({})[1]))

    def test_capability_is_not_exposed_to_cross_site_requests(self):
        self.assertIsNone(capability_from(self.get({**NAVIGATE, 'Sec-Fetch-Site': 'cross-site'})[1]))

    def test_capability_is_not_exposed_with_a_foreign_origin(self):
        self.assertIsNone(capability_from(self.get({**NAVIGATE, 'Origin': 'http://evil.example'})[1]))

    def test_foreign_host_header_is_refused_before_the_bootstrap(self):
        self.assertEqual(self.get({**NAVIGATE, 'Host': 'evil.example'})[0], 403)

    def test_capability_is_per_launch(self):
        with Host() as other:
            first = capability_from(self.get(NAVIGATE)[1])
            second = capability_from(request(other.url + '/', NAVIGATE)[1])
            self.assertNotEqual(first, second)
            self.assertEqual(request(other.url + '/api/settings', {'X-SAP-Lens': first})[0], 403)

    # ---- behaviour a remediation must provide (currently failing by design) ----------------------------------------------------------------
    @unittest.expectedFailure
    def test_remediation_navigation_headers_alone_do_not_yield_a_capability(self):
        self.assertIsNone(capability_from(self.get(NAVIGATE)[1]))


if __name__ == '__main__':
    unittest.main()
