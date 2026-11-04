#!/usr/bin/env python3
"""Profile real SoD APIs with a temporary synthetic CSV corpus; never reads user storage."""
import argparse
import cProfile
import json
import os
import pstats
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from fastapi.testclient import TestClient
import cache
import config
from main import create_app
import sod_decisions as decisions
import sod_governance as governance
import sod_scope as scope
from routers import sod_analysis as analysis_api
from validate import isolated_environment


def measure(client,url,headers,samples):
    def call():
        response=client.get(url,headers=headers)
        response.raise_for_status()
        return response
    # Cold means source-analysis/index caches cleared, not a dropped OS filesystem cache.
    with analysis_api._cache_lock:
        analysis_api._cached_key=analysis_api._cached_snapshot=analysis_api._cached_value=None
    with scope._cache_lock:scope._derived.clear()
    start=time.perf_counter();response=call();cold=(time.perf_counter()-start)*1000
    expected=response.json();times=[]
    with patch.object(decisions,'read',wraps=decisions.read) as reads,patch.object(governance,'derive',wraps=governance.derive) as derive,patch.object(analysis_api,'analyze',wraps=analysis_api.analyze) as analyze:
        for _ in range(samples):
            start=time.perf_counter();response=call();times.append((time.perf_counter()-start)*1000)
            if response.json()!=expected:raise RuntimeError('Warm/cold API output changed without a mutation.')
        read_count=reads.call_count/samples
        analysis_hits=1-analyze.call_count/samples;index_hits=1-derive.call_count/samples
    tracemalloc.start();call();_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    return dict(cold_derived_ms=round(cold,3),p50_ms=round(statistics.median(times),3),p95_ms=round(sorted(times)[min(len(times)-1,int(.95*len(times)))],3),
                decision_store_reads=read_count,payload_bytes=len(response.content),python_peak_kib=round(peak/1024,1),source_analysis_hit_rate=analysis_hits,prepared_index_hit_rate=index_hits)


def measure_writes(post, selection, items, samples, bulk=False):
    """Measure JSON-store work separately from HTTP/validation; there is no SQL database."""
    times=[];storage=[];recalculation=[];reads=[]
    original_write=decisions._write
    original_states=governance.states
    def timed_write(data):
        started=time.perf_counter()
        try:return original_write(data)
        finally:storage.append((time.perf_counter()-started)*1000)
    def timed_states(*args,**kwargs):
        started=time.perf_counter()
        try:return original_states(*args,**kwargs)
        finally:recalculation.append((time.perf_counter()-started)*1000)
    for index in range(samples):
        body=dict(context='current',expected_revision=decisions.read().revision,expected_generation=selection['generation'],items=items,
                  reviewer='Synthetic Profiler',justification='Synthetic save measurement')
        if bulk:body.update(action='Remove' if index%2 else 'Keep',atomic=True,replace_existing=True)
        else:body.update(decision='Remove' if index%2 else 'Keep')
        with patch.object(decisions,'_write',new=timed_write),patch.object(governance,'states',new=timed_states),patch.object(decisions,'read',wraps=decisions.read) as read:
            started=time.perf_counter()
            post('/api/sod/decisions/assignment'+('/bulk' if bulk else ''),body)
            times.append((time.perf_counter()-started)*1000)
            reads.append(read.call_count)
    def distribution(values):
        return dict(p50_ms=round(statistics.median(values),3),p95_ms=round(sorted(values)[min(len(values)-1,int(.95*len(values)))],3)) if values else dict(p50_ms=0,p95_ms=0)
    return dict(**distribution(times),assignments_per_save=len(items),api_requests_per_measured_save=1,
                json_store_reads_per_save=statistics.mean(reads),sql_query_count=0,storage_write=distribution(storage),derived_states=distribution(recalculation))


def run(users,samples):
    headers={'X-SAP-Lens':'synthetic-profile-capability'}
    with tempfile.TemporaryDirectory(prefix='sap-lens-profile-') as temporary:
        folder=Path(temporary)
        with patch.dict(os.environ,isolated_environment(folder),clear=True):
            config.get_settings.cache_clear();cache.clear_cache()
            try:
                with TestClient(create_app(session_token=headers['X-SAP-Lens']),base_url='http://127.0.0.1:18743') as client:
                    def get(path):
                        response=client.get(path,headers=headers);response.raise_for_status();return response.json()
                    def post(path,body):
                        response=client.post(path,headers=headers,json=body)
                        if response.is_error:raise RuntimeError(f'Synthetic setup {path}: {response.status_code}; {response.text[:800]}')
                        return response.json()
                    roles='AGR_NAME,TEXT,CHILD_AGR,TCODE\n'+''.join(f'{role},Synthetic,{role}_S,{code}\n' for role,code in [('ROLE_A1','X1'),('ROLE_A2','X1'),('ROLE_B','X2'),('ROLE_C','X3')])
                    assignments='USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\n'+''.join(f'SYN_PERF{i:05d},{role},FIN,20000101,99991231\n' for i in range(users) for role in ('ROLE_A1','ROLE_A2','ROLE_B','ROLE_C'))
                    matrix='RISK,CRITICITY,TYPE,TEXT,ACTVT1,ACTVT2,ACTIVITY_SLOT,ACTIVITY,TCODE,TTEXT\n'
                    for risk,b,code in [('R1','B','X2'),('R2','C','X3')]:
                        matrix+=f'{risk},H,S,Synthetic,A,{b},ACTVT1,A,X1,Synthetic\n{risk},H,S,Synthetic,A,{b},ACTVT2,{b},{code},Synthetic\n'
                    imports={}
                    for source,content in [('roles',roles),('users',assignments),('sod',matrix)]:
                        path=folder/f'{source}.csv';path.write_text(content,encoding='utf-8')
                        revision=get('/api/configuration')['settings']['revision']
                        start=time.perf_counter();post(f'/api/data-sources/{source}/select',dict(path=str(path),revision=revision,mode='static'));imports[source]=round((time.perf_counter()-start)*1000,3)
                    settings=get('/api/configuration')['settings'];settings['features'].update(sod=True,user_role_mapping=True);post('/api/configuration',settings)
                    selection=get('/api/sod/explorer/access_list/selection');picked={}
                    for row in selection['items']:picked.setdefault(row['user'],{key:row[key] for key in ('key','user','ref','evidence_version')})
                    post('/api/sod/decisions/assignment/bulk',dict(context='current',expected_revision=selection['revision'],expected_generation=selection['generation'],items=list(picked.values()),action='Keep',atomic=True,reviewer='Synthetic Profiler',justification='Synthetic performance corpus'))
                    endpoints={'overview':'/api/sod/overview','risk_matrix':'/api/sod/matrix/risk','activity_matrix':'/api/sod/matrix/activity',
                               'role_assignment_review':'/api/sod/subject?user=SYN_PERF00000','activity_review':'/api/sod/subject?user=SYN_PERF00000&activity=A',
                               'risk_review':'/api/sod/subject?user=SYN_PERF00000&risk=R1','remediation':'/api/sod/remediation',
                               'filtered_page':'/api/sod/explorer/access_list?group=FIN&offset=50&limit=50'}
                    result=dict(python=sys.version.split()[0],platform=sys.platform,users=users,assignments=users*4,risks=2,samples=samples,import_ms=imports,
                                measurements={name:measure(client,url,headers,samples) for name,url in endpoints.items()})
                    profiler=cProfile.Profile();profiler.enable();get(endpoints['risk_review']);profiler.disable()
                    result['profile_top']=[dict(function=f'{Path(key[0]).name}:{key[2]}',calls=value[1],self_ms=round(value[2]*1000,3),cumulative_ms=round(value[3]*1000,3)) for key,value in sorted(pstats.Stats(profiler).stats.items(),key=lambda pair:pair[1][3],reverse=True)[:12]]
                    item=next(iter(picked.values()))
                    result['decision_save']=measure_writes(post,selection,[item],samples)
                    result['bulk_decision_save']=measure_writes(post,selection,list(picked.values())[:100],samples,bulk=True)
                    return result
            finally:cache.clear_cache();config.get_settings.cache_clear()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--users',type=int,default=200);parser.add_argument('--samples',type=int,default=9);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if not 1<=args.users<=1000 or not 3<=args.samples<=50:parser.error('Use 1–1000 synthetic users and 3–50 samples.')
    result=run(args.users,args.samples);text=json.dumps(result,indent=2)+'\n'
    if args.output:args.output.write_text(text,encoding='utf-8');print(f'Synthetic profile saved: {args.output}')
    else:print(text)
