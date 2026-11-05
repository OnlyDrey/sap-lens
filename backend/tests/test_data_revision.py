"""Revision-aware consistency: every API response names its data revision; reviews are validated against current data and the version the user saw."""
import threading
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import server_access
from routers import account_review
import test_account_review as account_fixture
import test_sod_governance as sod_fixture
import sod_decisions

H = account_fixture.H


class Actor:
    """Stands in for the server's per-request account (the middleware sets and resets it around each request)."""
    def __init__(self, name):
        self.name = name

    def get(self):
        return self.name

    def set(self, value):
        return None

    def reset(self, token):
        return None


def parts(token):
    boot, publication, directory = token.split('.')
    return boot, int(publication), int(directory)


class Base(account_fixture.AccountReviewTests):
    """The account-review fixture (six synthetic SAP users, a small directory) without re-running its own tests."""

    def row(self, username='DEMO_NORMAL'):
        return next(r for r in self.get('?include_completed=true')['items'] if r['username'] == username)

    def post(self, row, state='Investigating', **extra):
        body = dict(state=state, reviewer='Synthetic Reviewer', rationale='Synthetic investigation', evidence_version=row['evidence_version'], **extra)
        return self.client.post('/api/account-review/decision/' + row['username'], headers=H, json=body)


for _name in [name for name in dir(account_fixture.AccountReviewTests) if name.startswith('test_')]:
    setattr(Base, _name, None)            # unittest skips non-callables: only the tests below run


class RevisionToken(Base):
    def test_every_api_response_carries_the_revision_and_configuration_exposes_it(self):
        for path in ('/api/account-review', '/api/configuration', '/api/access/users?limit=5', '/api/dashboard'):
            with self.subTest(path=path):
                token = self.client.get(path, headers=H).headers.get('X-Data-Revision')
                self.assertRegex(token, r'^[a-f0-9]+\.\d+\.\d+$')
        self.assertEqual(self.client.get('/api/configuration', headers=H).json()['data_generation'].split('.')[0], parts(cache.revision_token())[0])
        self.assertIsNone(self.client.get('/health/live').headers.get('X-Data-Revision'))              # only data-bearing API responses

    def test_the_revision_is_stable_until_data_is_published_and_then_increases(self):
        first = cache.revision_token()
        self.assertEqual(cache.revision_token(), first)
        self.assertEqual(self.client.get('/api/account-review', headers=H).headers['X-Data-Revision'], first)
        self.write_users(); cache.load_cache()                                                       # a publication
        second = cache.revision_token()
        self.assertEqual(parts(second)[0], parts(first)[0])
        self.assertGreater(parts(second)[1], parts(first)[1])
        self.assertEqual(cache.revision_token(), second)

    def test_a_directory_only_publication_changes_the_revision(self):
        before = parts(cache.revision_token())
        from employee_directory import store
        store.generation += 1                                                                         # what a directory-only publication does
        after = parts(cache.revision_token())
        self.assertEqual((after[1], after[2]), (before[1], before[2] + 1))

    def test_the_token_never_runs_ahead_of_the_data_a_handler_used(self):
        seen = {}
        original = account_review.current
        def publish_while_handling():
            result = original()
            cache._cache = cache._CacheState(users=cache.get_snapshot().users, roles=cache.get_snapshot().roles)       # published mid-request
            return result
        with patch.object(account_review, 'current', publish_while_handling):
            seen['during'] = self.client.get('/api/account-review', headers=H).headers['X-Data-Revision']
        self.assertGreater(parts(cache.revision_token())[1], parts(seen['during'])[1])                 # the response is labelled older than what is now current: a client re-reads

    def test_tokens_observed_by_concurrent_readers_never_go_backwards(self):
        errors, stop = [], threading.Event()
        def reader():
            last = 0
            while not stop.is_set():
                current = parts(cache.revision_token())[1]
                if current < last:
                    errors.append((last, current))
                last = current
        threads = [threading.Thread(target=reader) for _ in range(4)]
        for item in threads:
            item.start()
        for _ in range(40):
            cache._cache = cache._CacheState()
        stop.set()
        for item in threads:
            item.join(timeout=10)
        self.assertEqual(errors, [])


class ReviewSubmissions(Base):
    def test_a_decision_on_unchanged_evidence_survives_unrelated_data_changes(self):
        row = self.row()
        self.write_users(); cache.load_cache()                                                       # a refresh that changes nothing about this user
        self.assertEqual(self.post(row).status_code, 200)

    def test_a_decision_is_refused_when_the_users_evidence_changed_between_opening_and_saving(self):
        row = self.row('DEMO_NORMAL')
        self.write_users(shared=True); cache.load_cache()                                           # DEMO_NORMAL now shares an address: identity evidence changed
        refused = self.post(row)
        self.assertEqual(refused.status_code, 409)
        self.assertIn('evidence changed', refused.json()['detail'])
        self.assertEqual(self.client.get('/api/account-review/history/DEMO_NORMAL', headers=H).json()['total'], 0)    # nothing was written

    def test_a_decision_for_a_user_who_disappeared_is_refused(self):
        row = self.row('DEMO_EXPIRED')
        with self.csv.open('w') as stream:
            stream.write('USERNAME,ROLE_NAME,USER_GROUP,EMAIL,USER_VALID_FROM,USER_VALID_TO,USER_LOCKED,USER_TYPE\nDEMO_NORMAL,,DIALOG,normal@example.test,20000101,99991231,0,A\n')
        cache.load_cache()
        self.assertEqual(self.post(row).status_code, 404)

    def test_publication_between_validation_and_write_is_detected_and_nothing_is_stored(self):
        row = self.row()
        original = account_review.current
        def current_then_publish():
            result = original()
            cache._cache = cache._CacheState(users=cache.get_snapshot().users, roles=cache.get_snapshot().roles, last_loaded=cache.get_snapshot().last_loaded)   # replaced after the check
            return result
        with patch.object(account_review, 'current', current_then_publish):
            refused = self.post(row)
        self.assertEqual(refused.status_code, 409)
        self.assertIn('changed while saving', refused.json()['detail'])
        self.assertEqual(self.client.get('/api/account-review/history/DEMO_NORMAL', headers=H).json()['total'], 0)

    def test_two_users_reviewing_the_same_account_cannot_overwrite_each_other(self):
        first = self.row()
        stamp = first['decision']['timestamp'] if first['decision'] else ''
        with patch.object(server_access, 'ACTOR', Actor('alice')):                             # authenticated server users
            self.assertEqual(self.post(first, expected_decision=stamp).status_code, 200)
        with patch.object(server_access, 'ACTOR', Actor('bob')):
            stale = self.post(first, expected_decision=stamp)                                            # bob still sees the version before alice's decision
            self.assertEqual(stale.status_code, 409)
            self.assertIn('Another user changed', stale.json()['detail'])
            fresh = self.row()
            self.assertEqual(self.post(fresh, state='No action required', expected_decision=fresh['decision']['timestamp']).status_code, 200)
        self.assertEqual(self.client.get('/api/account-review/history/DEMO_NORMAL', headers=H).json()['total'], 1)       # alice's decision moved to history, bob's is current
        self.assertEqual(self.row()['decision']['state'], 'No action required')

    def test_a_desktop_client_that_sends_the_version_it_saw_is_protected_and_older_clients_still_work(self):
        row = self.row()
        self.assertEqual(self.post(row).status_code, 200)                                                # no version sent: behaves as before
        self.assertEqual(self.post(row, expected_decision='').status_code, 409)                         # a stale version sent without a server account
        current = self.row()
        self.assertEqual(self.post(current, state='No action required', expected_decision=current['decision']['timestamp']).status_code, 200)

    def test_concurrent_saves_of_one_account_are_serialised_and_exactly_one_wins_per_version(self):
        row = self.row()
        stamp = row['decision']['timestamp'] if row['decision'] else ''
        outcomes = []
        def save():
            outcomes.append(self.post(row, expected_decision=stamp).status_code)
        threads = [threading.Thread(target=save) for _ in range(4)]
        for item in threads:
            item.start()
        for item in threads:
            item.join(timeout=30)
        self.assertEqual(sorted(outcomes), [200, 409, 409, 409])



class SodSubmissions(sod_fixture.GovernanceCase):
    """SoD decisions carry the evidence generation and decision-store revision the reviewer saw; the server compares both with the current ones."""

    def view(self):
        return self.risk_matrix()

    def body(self, view, item, decision='Keep'):
        return dict(context='current', expected_revision=view['revision'], expected_generation=view['generation'], items=[item], decision=decision,
                    reviewer='Synthetic Reviewer', justification='Synthetic business need')

    def test_a_decision_built_from_data_that_changed_before_saving_is_refused_and_nothing_is_written(self):
        item = self.assignment_item('SYN_A', 'ROLE_A1')
        opened = self.view()
        state = cache.get_snapshot()
        state.users.users['SYN_A']['assignments'] = [a for a in state.users.users['SYN_A']['assignments'] if a['role_name'] != 'ROLE_C']          # a refresh removed an assignment
        cache._cache = state.__class__(**{**state.__dict__})
        refused = self.post('/api/sod/decisions/assignment', self.body(opened, item), 409)
        self.assertIn('changed', refused['detail'])
        self.assertEqual(sod_decisions.read().contexts, {})
        current = self.view()
        self.assertNotEqual(current['generation'], opened['generation'])
        self.assertEqual(len(self.post('/api/sod/decisions/assignment', self.body(current, self.assignment_item('SYN_A', 'ROLE_A1')))['events']), 1)     # reopened screen: accepted

    def test_two_reviewers_with_the_same_view_cannot_both_save(self):
        item = self.assignment_item('SYN_A', 'ROLE_A1')
        opened = self.view()
        self.post('/api/sod/decisions/assignment', self.body(opened, item))                      # first reviewer
        late = self.post('/api/sod/decisions/assignment', self.body(opened, item, 'Remove'), 409)  # second reviewer still holds the earlier decision-store revision
        self.assertIn('changed', late['detail'])
        self.assertEqual([event.decision for event in sod_decisions.read().contexts['current']['assignment'][item['key']]], ['Keep'])

    def test_a_decision_saved_while_publication_changes_the_evidence_is_refused(self):
        from routers import sod_analysis
        item = self.assignment_item('SYN_A', 'ROLE_A1')
        opened = self.view()
        real = sod_analysis.generation_for
        def changing(key):
            # The request-level comparison passes; the data then changes before the guarded write (the guard is the only caller named publication_guard).
            return 'c' * 64 if sys._getframe(1).f_code.co_name == 'publication_guard' else real(key)
        with patch.object(sod_analysis, 'generation_for', changing):
            self.post('/api/sod/decisions/assignment', self.body(opened, item), 409)
        self.assertEqual(sod_decisions.read().contexts, {})



if __name__ == '__main__':
    unittest.main()
