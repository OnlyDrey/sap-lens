"""Derived assessment is not acceptance, fabricated history or verified remediation."""
import test_sod_governance as fixture
import sod_decisions as decisions

class CoverageTests(fixture.GovernanceCase):
    def test_roles_cover_activities_and_risks_without_fabricating_decisions(self):
        before=self.subject('SYN_A')['overview']
        for row in before['assignments']:
            self.decide('assignment',[dict(key=row['id'],user='SYN_A',ref=row['role'],evidence_version=row['evidence_version'])], 'Remove' if row['role']=='ROLE_B' else 'Keep')
        revision=decisions.read().revision
        result=self.subject('SYN_A')['overview']
        self.assertTrue(all(row['review_coverage']['reviewed'] for row in result['activities']))
        risks={row['risk_id']:row for row in result['risks']}
        self.assertEqual(risks['R1']['review_coverage']['label'],'Reviewed — removal planned')
        self.assertFalse(risks['R2']['review_coverage']['removal_planned'])
        self.assertTrue(all(row['acceptance']=='Pending' and row['event'] is None for row in result['risks']))
        self.assertTrue(all(not row['review_coverage']['risk_accepted'] and not row['review_coverage']['remediation_verified'] for row in result['risks']))
        queue=next(row for row in self.get('/api/sod/queue/users')['items'] if row['user']=='SYN_A')
        self.assertEqual((queue['decided'],queue['total'],queue['formal_acceptance']['decided']),(9,9,0))
        self.assertEqual(len(self.risk_matrix()['rows'][0]['cells']),2)
        self.assertEqual(decisions.read().revision,revision)
    def test_explicit_risk_review_covers_activities_but_does_not_propagate_to_shared_risk_or_roles(self):
        self.decide('acceptance',[self.acceptance_item('SYN_A','R1')],'Accepted',approver='Other Reviewer',controls='Synthetic control')
        overview=self.subject('SYN_A')['overview']
        acts={row['activity']:row for row in overview['activities']}
        self.assertEqual(acts['A']['review_coverage']['provenance'],'Reviewed through risk review')
        self.assertTrue(acts['B']['review_coverage']['reviewed']);self.assertFalse(acts['C']['review_coverage']['reviewed'])
        self.assertFalse(next(row for row in overview['risks'] if row['risk_id']=='R2')['review_coverage']['reviewed'])
        self.assertTrue(all(row['decision']=='Pending' and not row['review_coverage']['reviewed'] for row in overview['assignments']))
    def test_overlap_requires_all_providers_and_removal_plan_is_not_a_single_remove(self):
        self.decide('assignment',[self.assignment_item('SYN_A','ROLE_A1')],'Remove')
        result=self.subject('SYN_A')['overview']
        self.assertFalse(next(row for row in result['activities'] if row['activity']=='A')['review_coverage']['reviewed'])
        self.assertFalse(any(row['review_coverage']['removal_planned'] for row in result['risks']))
        self.decide('assignment',[self.assignment_item('SYN_A','ROLE_A2')],'Remove')
        result=self.subject('SYN_A')['overview']
        self.assertTrue(all(row['review_coverage']['removal_planned'] for row in result['risks']))
        self.assertTrue(all(not row['review_coverage']['remediation_verified'] for row in result['risks']))
    def test_reset_and_other_context_do_not_count_as_current_coverage(self):
        self.decide('activity',[self.activity_item('SYN_A','A')],'Approved')
        self.assertTrue(next(row for row in self.subject('SYN_A')['overview']['activities'] if row['activity']=='A')['review_coverage']['reviewed'])
        self.decide('activity',[self.activity_item('SYN_A','A')],'Pending')
        self.assertFalse(next(row for row in self.subject('SYN_A')['overview']['activities'] if row['activity']=='A')['review_coverage']['reviewed'])
    def test_outdated_role_evidence_does_not_cover_an_activity(self):
        import copy
        import sod_governance as governance
        import sod_scope as scope
        for name in ('ROLE_A1','ROLE_A2'):
            self.decide('assignment',[self.assignment_item('SYN_A',name)],'Keep')
        bundle=scope.load('current');model=copy.deepcopy(scope.model_for(bundle));latest=scope.latest_for(bundle)
        activity=model['SYN_A']['activities']['A'];aid=next(iter(activity['assignments']))
        model['SYN_A']['assignments'][aid]['evidence_version']='f'*64
        state=governance.states(model,latest)
        self.assertEqual(state['assignment'][aid][0],'Outdated')
        self.assertFalse(state['coverage']['activity'][activity['key']]['reviewed'])
