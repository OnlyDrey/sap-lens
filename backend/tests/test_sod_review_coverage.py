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

    def test_period_coverage_matches_queue_without_relaxing_formal_approval(self):
        from datetime import date
        import sod_periods as periods
        pid=periods.create('Synthetic coverage',date(2026,1,1),date(2026,12,31),date(2026,10,27),periods.read().revision)['period']['id']
        for row in self.subject('SYN_A',context=pid)['overview']['assignments']:
            self.decide('assignment',[dict(key=row['id'],user='SYN_A',ref=row['role'],evidence_version=row['evidence_version'])],'Keep',context=pid)
        queue=self.get('/api/sod/queue/users',context=pid)['items']
        period=periods.find(periods.read(),pid)
        progress=periods.progress(period)
        self.assertEqual(progress['decided'],sum(row['decided'] for row in queue))
        self.assertEqual(progress['total'],sum(row['total'] for row in queue))
        self.assertGreater(progress['blocking'],0) # Assessment coverage never bypasses formal approval.

    def test_frozen_lifecycle_uses_approval_date_not_wall_clock(self):
        from datetime import date
        from unittest.mock import patch
        import sod_scope as scope
        bundle=dict(frozen=True,period={'approval_date':'2026-10-27'})
        with patch.object(scope,'latest_for',return_value={}),patch.object(scope.governance,'states',return_value={}) as derive:
            scope.states_for(bundle,{})
            self.assertEqual(derive.call_args.kwargs['today'],date(2026,10,27))

    def test_role_decision_labels_are_explicit_and_scoped_to_user_and_assignment(self):
        import cache
        cache._cache=fixture.snapshot(extra_users={'SYN_D':fixture.user('ROLE_A1','ROLE_B')})
        for decision,label,tone in [('Keep','Approved','success'),('Remove','Remove','error'),('Investigate','Investigate','warning'),('Pending','Pending','neutral')]:
            self.decide('assignment',[self.assignment_item('SYN_A','ROLE_A1')],decision)
            row=next(row for row in self.subject('SYN_A')['overview']['assignments'] if row['role']=='ROLE_A1')
            self.assertEqual((row['decision_summary']['label'],row['decision_summary']['tone']),(label,tone))
            self.assertEqual(row['decision_summary']['explicit'],decision!='Pending')
            other=next(row for row in self.subject('SYN_D')['overview']['assignments'] if row['role']=='ROLE_A1')
            self.assertEqual(other['decision_summary']['label'],'Pending')

    def test_approved_role_derives_activity_approval_without_fabricating_an_event(self):
        self.decide('assignment',[self.assignment_item('SYN_A','ROLE_A1')],'Keep')
        self.decide('assignment',[self.assignment_item('SYN_A','ROLE_A2')],'Remove')
        row=next(row for row in self.subject('SYN_A')['overview']['activities'] if row['activity']=='A')
        self.assertEqual(row['decision_summary']['label'],'Approved')
        self.assertEqual(row['decision_summary']['assignment_decisions'],{'Keep':1,'Removal required':1})
        self.assertTrue(row['review_coverage']['reviewed'])
        self.decide('assignment',[self.assignment_item('SYN_A','ROLE_A2')],'Keep')
        row=next(row for row in self.subject('SYN_A')['overview']['activities'] if row['activity']=='A')
        self.assertEqual(row['decision_summary']['label'],'Approved')
        self.decide('activity',[self.activity_item('SYN_A','A')],'Approved')
        row=next(row for row in self.subject('SYN_A')['overview']['activities'] if row['activity']=='A')
        self.assertEqual(row['decision_summary']['label'],'Approved')
        self.assertTrue(row['decision_summary']['explicit'])
        self.assertTrue(all(row['decision_summary']['label']=='Acceptance pending' for row in self.subject('SYN_A')['overview']['risks']))

    def test_stale_role_evidence_is_not_current_approval(self):
        import cache
        self.decide('assignment',[self.assignment_item('SYN_B','ROLE_AB')],'Keep')
        cache._cache=fixture.snapshot(extra=True,tcodes={'ROLE_AB':['X5']})
        row=self.subject('SYN_B')['overview']['assignments'][0]
        self.assertEqual(row['decision_summary']['label'],'Pending')
        self.assertFalse(row['decision_summary']['explicit'])
        self.assertTrue(row['decision_summary']['stale'])

    def test_bulk_decisions_update_summaries_but_not_acceptance_or_other_periods(self):
        from datetime import date
        import sod_periods as periods
        period=periods.create('Synthetic status period',date(2026,1,1),date(2026,12,31),date(2026,10,27),periods.read().revision)['period']['id']
        for action,label in [('Keep','Approved'),('Remove','Remove')]:
            selected=self.get('/api/sod/explorer/access_list/selection')
            items=[{key:row[key] for key in ('key','user','ref','evidence_version')} for row in selected['items']]
            self.post('/api/sod/decisions/assignment/bulk',dict(context='current',expected_revision=selected['revision'],expected_generation=selected['generation'],items=items,action=action,atomic=True,replace_existing=action=='Remove',reviewer='Synthetic Reviewer',justification='Synthetic bulk status test'))
            view=self.subject('SYN_A')['overview']
            self.assertTrue(all(row['decision_summary']['label']==label for row in view['assignments']))
            self.assertTrue(all(row['acceptance']=='Pending' for row in view['risks']))
        self.assertTrue(all(row['decision_summary']['label']=='Pending' for row in self.subject('SYN_A',context=period)['overview']['assignments']))

    def test_formal_acceptance_label_is_independent_of_assignment_decisions(self):
        for value,tone in [('Rejected','error'),('Accepted','success')]:
            self.decide('acceptance',[self.acceptance_item('SYN_A','R1')],value,approver='Other Reviewer')
            overview=self.subject('SYN_A')['overview']
            risk=next(row for row in overview['risks'] if row['risk_id']=='R1')
            self.assertEqual((risk['decision_summary']['label'],risk['decision_summary']['tone']),(value,tone))
            self.assertTrue(all(row['decision_summary']['label']=='Pending' for row in overview['assignments']))
            self.assertTrue(all(not row['decision_summary']['explicit'] for row in overview['activities']))

    def test_request_snapshot_reuses_reads_and_revision_without_cross_request_staleness(self):
        from unittest.mock import patch
        import sod_scope as scope
        item=self.assignment_item('SYN_A','ROLE_A1')
        bundle=scope.load('current')
        with patch.object(decisions,'read',wraps=decisions.read) as reads:
            latest=scope.latest_for(bundle)
            revision=scope.context_info(bundle)['revision']
            scope.actions_for(bundle)
            self.assertEqual(reads.call_count,1)
        self.decide('assignment',[item],'Keep')
        self.assertEqual(scope.context_info(bundle)['revision'],revision)
        self.assertEqual(scope.latest_for(bundle),latest)
        fresh=scope.load('current')
        self.assertGreater(scope.context_info(fresh)['revision'],revision)
        self.assertEqual(scope.latest_for(fresh)['assignment'][item['key']].decision,'Keep')
        self.assertGreater(scope.revision(),revision) # Write guards must remain live.

    def test_api_reads_one_snapshot_for_subject_matrices_and_remediation(self):
        from unittest.mock import patch
        for path,params in [('/api/sod/subject',{'user':'SYN_A'}),('/api/sod/matrix/risk',{}),('/api/sod/matrix/activity',{}),('/api/sod/remediation',{})]:
            with self.subTest(path=path),patch.object(decisions,'read',wraps=decisions.read) as reads:
                first=self.get(path,**params)
                self.assertEqual(reads.call_count,1)
            self.assertEqual(self.get(path,**params),first)

    def test_activity_effective_decision_matrix_and_explicit_disagreement(self):
        for left,right,expected in [('Keep','Remove','Approved'),('Keep','Investigate','Approved'),('Remove','Remove','Remove'),('Remove','Investigate','Investigate'),('Remove','Pending','Pending'),('Pending','Pending','Pending')]:
            with self.subTest(left=left,right=right):
                self.decide('assignment',[self.assignment_item('SYN_A','ROLE_A1')],left)
                self.decide('assignment',[self.assignment_item('SYN_A','ROLE_A2')],right)
                row=next(row for row in self.subject('SYN_A')['overview']['activities'] if row['activity']=='A')
                self.assertEqual(row['decision_summary']['label'],expected)
                self.assertIsNone(row['event'])
                self.assertFalse(row['decision_summary']['explicit'])
        self.decide('activity',[self.activity_item('SYN_A','A')],'Remove')
        self.decide('assignment',[self.assignment_item('SYN_A','ROLE_A1')],'Keep')
        row=next(row for row in self.subject('SYN_A')['overview']['activities'] if row['activity']=='A')
        self.assertEqual(row['decision_summary']['label'],'Remove')
        self.assertEqual(row['decision_summary']['derived_label'],'Approved')
        self.assertTrue(row['decision_summary']['disagreement'])

    def test_normal_risk_decisions_are_independent_of_acceptance_roles_and_periods(self):
        from datetime import date
        import sod_periods as periods
        pid=periods.create('Synthetic normal risk',date(2026,1,1),date(2026,12,31),date(2026,10,27),periods.read().revision)['period']['id']
        for decision in ['Approved','Remove','Investigate','Pending']:
            row=next(row for row in self.subject('SYN_A')['overview']['risks'] if row['risk_id']=='R1')
            item=dict(key=row['finding_id'],user='SYN_A',ref='R1',evidence_version=row['evidence_version'])
            self.decide('risk',[item],decision)
            view=self.subject('SYN_A')['overview'];risk=next(row for row in view['risks'] if row['risk_id']=='R1')
            self.assertEqual(risk['risk_review_summary']['label'],decision)
            self.assertEqual(risk['acceptance'],'Pending')
            self.assertTrue(all(row['decision']=='Pending' for row in view['assignments']))
            self.assertTrue(all(row['risk_review_summary']['label']=='Pending' for row in self.subject('SYN_A',context=pid)['overview']['risks']))
        self.decide('acceptance',[self.acceptance_item('SYN_A','R1')],'Accepted',approver='Other Reviewer')
        self.decide('risk',[item],'Remove')
        risk=next(row for row in self.subject('SYN_A')['overview']['risks'] if row['risk_id']=='R1')
        self.assertEqual(risk['acceptance'],'Accepted')
        self.assertEqual(risk['risk_review_summary']['label'],'Remove')
        history=self.get('/api/sod/decisions/risk/history',key=item['key'])
        self.assertEqual(len(history['items']),5)
        self.assertEqual(history['items'][0]['decision'],'Remove')

    def test_explicit_activity_investigation_and_absent_suppliers_are_not_approval(self):
        import copy
        import sod_governance as governance
        import sod_scope as scope
        self.decide('activity',[self.activity_item('SYN_A','A')],'Investigate')
        row=next(row for row in self.subject('SYN_A')['overview']['activities'] if row['activity']=='A')
        self.assertEqual(row['decision_summary']['label'],'Investigate')
        bundle=scope.load('current');model=copy.deepcopy(scope.model_for(bundle))
        activity=model['SYN_A']['activities']['B'];activity['assignments']=set()
        state=scope.states_for(bundle,model)
        self.assertEqual(governance.effective_decision(model['SYN_A'],state,'activity',activity['key'])['label'],'Pending')
        from server_access import may_access
        self.assertTrue(may_access('reviewer','POST','/api/sod/decisions/risk'))
        self.assertFalse(may_access('read-only','POST','/api/sod/decisions/risk'))
