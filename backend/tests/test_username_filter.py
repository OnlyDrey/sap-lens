"""Exact SAP username lists in the User Directory: parsing, matching, feedback, and the same effective query for listing, paging, sorting, counts and export."""
import sys
import unittest
from pathlib import Path
from urllib.parse import quote
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_role_negative_tcode import TransactionFilterCase, H
import username_filter as uf

PASTED = """CROYNESTAD
RFORLAND
KEGELAND
MASLAND
VTVEITEN
EGLENDRANGE
IHELLE
ABERGMANN
RLUNDE
OARNTSEN
TSKIFJELD
KJØRGENSEN
RBRINGSVAERD
JHALSTVEDT
EKAALSTAD
TOYE
TSTIGE
AKOCH
GHARALDSEN
IOVREBO
SFROYSTAD
JLOVIK
KSULEN
IRISVOLL"""


class Parser(unittest.TestCase):
    def test_the_pasted_example_gives_24_unique_usernames_including_unicode(self):
        parsed = uf.parse_usernames(PASTED)
        self.assertEqual(len(parsed['requested']), 24)
        self.assertIn('KJØRGENSEN', parsed['requested'])
        self.assertEqual((parsed['duplicates'], parsed['invalid']), (0, []))

    def test_every_separator_gives_the_same_list(self):
        names = ['U1', 'U2', 'U3']
        for separator in ('\n', '\r\n', ',', ';', '\t', ' ', ' , ', ';\n', '  \t '):
            with self.subTest(separator=repr(separator)):
                self.assertEqual(uf.parse_usernames(separator.join(names))['requested'], names)

    def test_case_insensitive_duplicates_are_removed_and_the_first_spelling_is_kept(self):
        parsed = uf.parse_usernames('u1, U1;\nU2 u2 U3')
        self.assertEqual((parsed['requested'], parsed['duplicates']), (['u1', 'U2', 'U3'], 2))

    def test_empty_entries_vanish_and_emails_or_control_text_are_reported_not_matched(self):
        parsed = uf.parse_usernames(',,;; U1 ;; a.b@example.test \x01x ' + 'Z' * 41)
        self.assertEqual(parsed['requested'], ['U1'])
        self.assertEqual(len(parsed['invalid']), 3)
        self.assertEqual(uf.parse_usernames('')['requested'], [])

    def test_the_paste_rule_suggests_a_list_only_for_list_like_input(self):
        for text in (PASTED, 'U1,U2', 'U1;U2', 'U1\tU2', 'U1 U2 U3', 'CROYNESTAD RFORLAND KEGELAND'):
            self.assertTrue(uf.looks_like_username_list(text), text)
        for text in ('', 'U1', 'Kari Nordmann', 'purchasing manager oslo', 'kari@example.test', 'Kari Nordmann, Per Hansen'.replace(', ', ' ')):
            self.assertFalse(uf.looks_like_username_list(text), text)


class Listing(TransactionFilterCase):
    def q(self, names, extra=''):
        return self.users('usernames=' + quote(names) + extra)

    def test_exact_match_is_case_insensitive_and_never_a_substring(self):
        self.assertEqual(self.q('u1'), {'U1'})
        self.assertEqual(self.q('U'), set())                  # "U" is a prefix of every user, but only an exact name matches
        self.assertEqual(self.q('U1,U3;U5\nU7\tU2 u2'), {'U1', 'U2', 'U3', 'U5', 'U7'})

    def test_unknown_names_do_not_widen_the_result(self):
        self.assertEqual(self.q('U1,NOBODY'), {'U1'})
        self.assertEqual(self.q('NOBODY'), set())

    def test_the_list_combines_with_other_filters_by_and(self):
        everyone = self.users('')
        self.assertEqual(self.q('U1,U3,U4', '&group=G2'), self.users('group=G2') & {'U1', 'U3', 'U4'})
        self.assertEqual(self.q(','.join(sorted(everyone)), '&search=U3'), {'U3'})
        self.assertEqual(self.q('U1,U2', '&status=expired'), self.users('status=expired') & {'U1', 'U2'})

    def test_feedback_counts_requested_matched_unmatched_invalid_and_filtered_out(self):
        response = self.client.get('/api/access/users?limit=100&usernames=' + quote('U1,u1,U3,GHOST,a@b.test,U4') + '&group=G2', headers=H).json()
        feedback = response['username_filter']
        self.assertEqual((feedback['requested'], feedback['duplicates'], feedback['found']), (4 - 0, 1, 3))
        self.assertEqual(feedback['unmatched'], ['GHOST'])
        self.assertEqual(feedback['invalid'], ['a@b.test'])
        self.assertEqual(feedback['matched'] + len(feedback['filtered_out']), feedback['found'])
        self.assertEqual({item['username'] for item in response['items']}, self.users('group=G2') & {'U1', 'U3', 'U4'})
        self.assertIsNone(self.client.get('/api/access/users?limit=5', headers=H).json()['username_filter'])

    def test_paging_sorting_and_total_follow_the_same_selection(self):
        names = 'U1,U2,U3,U4,U5'
        first = self.client.get('/api/access/users?limit=2&offset=0&descending=true&usernames=' + names, headers=H).json()
        second = self.client.get('/api/access/users?limit=2&offset=2&descending=true&usernames=' + names, headers=H).json()
        self.assertEqual(first['total'], 5)
        self.assertEqual([i['username'] for i in first['items']] + [i['username'] for i in second['items']], ['U5', 'U4', 'U3', 'U2'])

    def test_the_export_uses_the_same_effective_list(self):
        rows = self.export('usernames=' + quote('u2;U4\nU6'))
        everyone = self.export('')
        self.assertEqual({row['USERNAME'] for row in rows}, {row['USERNAME'] for row in everyone} & {'U2', 'U4', 'U6'})
        self.assertEqual(len(rows), sum(row['USERNAME'] in {'U2', 'U4', 'U6'} for row in everyone))
        self.assertEqual({row['USERNAME'] for row in self.export('usernames=' + quote('U2,U4') + '&group=G2')}, {'U2', 'U4'} & self.users('group=G2'))

    def test_too_many_different_names_are_refused_not_truncated(self):
        too_many = ','.join(f'X{n}' for n in range(uf.MAX_USERNAMES + 1))
        response = self.client.get('/api/access/users?usernames=' + too_many, headers=H)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get('/api/access/users?usernames=' + ','.join(f'X{n}' for n in range(uf.MAX_USERNAMES)), headers=H).status_code, 200)

    def test_ordinary_search_is_unchanged(self):
        self.assertEqual(self.users('search=U3'), {'U3'})
        self.assertEqual(self.users('search='), self.users(''))


if __name__ == '__main__':
    unittest.main()
