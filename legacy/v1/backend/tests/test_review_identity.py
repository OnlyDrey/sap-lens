"""Stable actor snapshots preserve legacy evidence and permit explicit self-approval."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import review_identity as identity
import sod_decisions as decisions
from server_access import actor
from fastapi import HTTPException


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':self.temp.name,'SAP_LENS_DEPLOYMENT_MODE':'desktop'})
        self.env.start();self.addCleanup(self.env.stop)
        for context,value in ((identity.IDENTITY,None),(identity.MODE,None)):
            token=context.set(value);self.addCleanup(context.reset,token)

    def item(self):return dict(key='a'*64,user='SYNTHETIC',ref='ROLE_A',evidence_version='b'*64,evidence=dict(synthetic=True))

    def test_server_ignores_forged_reviewer_and_retains_snapshot_after_rename(self):
        who=dict(id='c'*32,username='reviewer',display_name='Verified Reviewer',provenance='server-session')
        identity.IDENTITY.set(who);identity.MODE.set('server')
        event=decisions.record('assignment','current',[self.item()],'Keep','Forged name','Justification',0)['events'][0]
        self.assertEqual(event['reviewer'],'reviewer');self.assertEqual(event['actor_identity'],who)
        report=decisions.log_report('current','csv','Synthetic','Draft','1','b'*64,prepared_by='Forged preparer')
        self.assertEqual(report['prepared_by'],'reviewer')
        self.assertEqual(report['actor_identity'],who)
        identity.IDENTITY.set({**who,'display_name':'Renamed Reviewer'})
        decisions.record('assignment','current',[self.item()],'Investigate','Other forged name','Check access',1)
        events=list(reversed(decisions.history('assignment','current','a'*64)))
        self.assertEqual(events[0],event)
        self.assertEqual(events[1]['actor_identity']['id'],event['actor_identity']['id'])
        self.assertNotEqual(events[1]['actor_identity']['display_name'],event['actor_identity']['display_name'])

    def test_local_profile_is_stable_editable_revision_checked_and_not_verified(self):
        identity.MODE.set('desktop')
        self.assertEqual(actor('Arbitrary frontend reviewer'),'Local reviewer')
        before=identity.profile()
        after=identity.profile('Synthetic local reviewer',0)
        self.assertEqual(before['identity']['id'],after['identity']['id'])
        self.assertEqual(identity.snapshot()['provenance'],'desktop-local')
        self.assertEqual(actor('Arbitrary frontend reviewer'),'Synthetic local reviewer')
        with self.assertRaises(HTTPException):identity.profile('Stale display name',0)
        path=Path(self.temp.name)/'reviewer-profile.json'
        path.write_bytes(b'invalid')
        with self.assertRaises(HTTPException):identity.profile()
        self.assertEqual(path.read_bytes(),b'invalid')

    def test_legacy_models_serialize_without_inventing_an_actor(self):
        value=dict(event_id='a'*32,kind='assignment',context='current',timestamp=datetime.now(timezone.utc).isoformat(),key='a'*64,user='SYNTHETIC',ref='ROLE_A',decision='Keep',reviewer='Legacy reviewer',justification='Historical reason',evidence_version='b'*64,evidence_snapshot='d'*64)
        event=decisions.Event.model_validate(value)
        self.assertNotIn('actor_identity',event.model_dump())
        self.assertEqual(event.reviewer,'Legacy reviewer')
        self.assertNotIn('actor_identity',json.loads(event.model_dump_json()))

    def test_explicit_self_approval_is_recorded_and_not_inferred_from_other_decisions(self):
        who=dict(id='c'*32,username='reviewer',display_name='Reviewer',provenance='server-session')
        identity.IDENTITY.set(who)
        event=decisions.record('activity','current',[self.item()],'Approved','ignored','Review activity',0)['events'][0]
        self.assertEqual(event['approver'],'')
        self.assertEqual(decisions.latest('current')['acceptance'],{})
        result=decisions.record('acceptance','current',[self.item()],'Accepted','forged','Explicit formal acceptance',1,approver='forged approver')
        event=result['events'][0]
        self.assertEqual(event['reviewer'],event['approver'])
        self.assertEqual(event['actor_identity'],who)
        self.assertEqual(len(decisions.read().contexts['current']['activity']['a'*64]),1)
