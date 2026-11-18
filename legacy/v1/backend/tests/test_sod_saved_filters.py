"""SoD investigations use the existing saved-filter store and schema boundary."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from routers.saved_filters import router


class SodSavedFilterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':self.temp.name});self.env.start();self.addCleanup(self.env.stop)
        app=FastAPI();app.include_router(router);self.client=TestClient(app)

    def test_user_and_role_filters_are_independent_and_persist(self):
        for view in ('sod_users','sod_roles'):
            response=self.client.post('/api/saved-filters',json=dict(name='Synthetic investigation',view=view,filters=dict(search='SYN*',sort='risk_id',descending=True,selected_roles=['ZC:SYNTHETIC'])))
            self.assertEqual(response.status_code,200,response.text)
        items=self.client.get('/api/saved-filters').json()['items'];self.assertEqual(len(items),2)
        process=subprocess.run([sys.executable,'-c',"import saved_filters; assert {r['view'] for r in saved_filters.read()} == {'sod_users','sod_roles'}"],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(process.returncode,0,'Saved SoD filters did not survive process restart')

    def test_result_datasets_cannot_be_stored(self):
        for view in ('sod_users','sod_roles'):
            response=self.client.post('/api/saved-filters',json=dict(name='Invalid',view=view,filters={'evidence':['private-record']}))
            self.assertEqual(response.status_code,422)
        self.assertEqual(self.client.get('/api/saved-filters').json()['items'],[])

    def test_existing_rename_update_delete_guards_apply(self):
        item=self.client.post('/api/saved-filters',json=dict(name='Original',view='sod_users',filters={'validity':'active'})).json()
        response=self.client.post('/api/saved-filters',json=dict(id=item['id'],expected=item['modified'],name='Renamed',view='sod_users',filters={},rename=True))
        self.assertEqual(response.status_code,200);renamed=response.json();self.assertEqual(renamed['filters'],{'validity':'active'})
        response=self.client.post('/api/saved-filters',json=dict(id=item['id'],expected=item['modified'],name='Stale',view='sod_users',filters={'validity':'all'}))
        self.assertEqual(response.status_code,409)
        response=self.client.post('/api/saved-filters/delete',json=dict(id=renamed['id'],expected=renamed['modified']))
        self.assertEqual(response.status_code,200)
