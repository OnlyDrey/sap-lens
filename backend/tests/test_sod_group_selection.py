"""Selected groups are exact source identifiers, independently from dropdown search."""
import test_sod_governance as fixture
import cache

class ExactGroupTests(fixture.GovernanceCase):
    def setUp(self):
        super().setUp()
        self.groups=['SYN-GROUP','SYN-GROUP-ONE','SYN-GROUP-TWO','SYN-GROUP-THREE']
        cache._cache=fixture.snapshot(extra_users={f'SYN_FILTER_{i}':fixture.user('ROLE_AB',group=group) for i,group in enumerate(self.groups)})
    def test_exact_groups_or_and_and_patterns_remain_separate(self):
        for index,group in enumerate(self.groups):
            rows=self.get('/api/sod/queue/users',groups=[group])['items']
            self.assertEqual([row['user'] for row in rows],[f'SYN_FILTER_{index}'])
        rows=self.get('/api/sod/queue/users',groups=self.groups[:2])['items']
        self.assertEqual({row['user'] for row in rows},{'SYN_FILTER_0','SYN_FILTER_1'})
        self.assertEqual(self.get('/api/sod/queue/users',groups=['SYN-GROUP*'])['total'],0)
        self.assertEqual(self.get('/api/sod/queue/users',groups=self.groups[:2],username='SYN_FILTER_1')['total'],1)
        self.assertEqual(self.get('/api/sod/queue/users',groups=['SYN-GROUP'],role='ROLE_A*')['total'],1)
        self.assertEqual(self.get('/api/sod/queue/users',groups=['SYN-GROUP'],role='ROLE_B*')['total'],0)
    def test_matrix_explorer_selection_and_exports_share_exact_scope(self):
        for route in ['/api/sod/matrix/risk','/api/sod/matrix/activity','/api/sod/explorer/user_risk','/api/sod/explorer/user_activity','/api/sod/explorer/access_list']:
            result=self.get(route,group='SYN-GROUP')
            rows=result.get('rows',result.get('items',[]))
            self.assertEqual({row['user'] for row in rows},{'SYN_FILTER_0'},route)
        response=self.client.get('/api/sod/queue/export',headers=fixture.H,params={'groups':'SYN-GROUP'})
        self.assertEqual(response.status_code,200);self.assertIn('SYN_FILTER_0',response.text)
        self.assertNotIn('SYN_FILTER_1',response.text)
    def test_saved_group_selection_roundtrip_preserves_exact_values(self):
        self.post('/api/saved-filters',dict(name='Synthetic exact groups',view='sod_queue',filters={'groups':self.groups[:2]}))
        entries=self.get('/api/saved-filters')['items']
        restored=next(item for item in entries if item['name']=='Synthetic exact groups')['filters']
        self.assertEqual(restored['groups'],self.groups[:2])
        self.assertEqual({row['user'] for row in self.get('/api/sod/queue/users',**restored)['items']},{'SYN_FILTER_0','SYN_FILTER_1'})
    def test_queue_sorts_full_filtered_scope_before_pagination_with_stable_ties(self):
        subject='SYN_FILTER_1'
        self.decide('assignment',[self.assignment_item(subject,'ROLE_AB')],'Remove')
        params={'groups':self.groups,'limit':1}
        for key in ['progress','activity','assignment','risk','removal']:
            row=self.get('/api/sod/queue/users',queue_sort=key,descending=True,**params)['items'][0]
            self.assertEqual(row['user'],subject,key)
        self.assertEqual(self.get('/api/sod/queue/users',queue_sort='progress',**params)['items'][0]['user'],'SYN_FILTER_0')
        self.assertEqual(self.get('/api/sod/queue/users',queue_sort='username',descending=True,**params)['items'][0]['user'],'SYN_FILTER_3')
        tied=self.get('/api/sod/queue/users',queue_sort='acceptance',descending=True,groups=self.groups)['items']
        self.assertEqual([row['user'] for row in tied],[f'SYN_FILTER_{i}' for i in range(4)])
        self.assertEqual(self.get('/api/sod/queue/users',queue_sort='progress',descending=True,group='SYN-GROUP')['items'][0]['user'],'SYN_FILTER_0')
        default=self.get('/api/sod/queue/users',groups=self.groups)['items']
        self.assertEqual(default[-1]['user'],subject)
        page=self.get('/api/sod/queue/users',groups=self.groups,queue_sort='username',offset=2,limit=1)
        self.assertEqual(page['items'][0]['user'],'SYN_FILTER_2')

    def test_default_queue_prioritizes_pending_users_then_username_not_item_count(self):
        cache._cache=fixture.snapshot(extra_users={'SYN_00':fixture.user('ROLE_AB')})
        for descending in (False,True):
            rows=self.get('/api/sod/queue/users',group='FIN',descending=descending)['items']
            self.assertEqual([row['user'] for row in rows],['SYN_00','SYN_A'])
            self.assertLess(rows[0]['outstanding'],rows[1]['outstanding'])
