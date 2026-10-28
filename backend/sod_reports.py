"""One frozen evidence model, rendered as editable DOCX or office-free PDF."""
from collections import Counter
from datetime import date,datetime,timezone
from hashlib import sha256
from html import escape
from io import BytesIO
import json
from pathlib import Path
import threading
from typing import Literal
from zipfile import ZipFile,ZIP_DEFLATED,ZipInfo
from fastapi import HTTPException
from pydantic import Field,model_validator,field_validator
from config_models import StrictModel
from branding import logo_bytes
import sod_periods as periods
import sod_decisions as decisions
import sod_governance as governance
import sod_scope as scope

SECTIONS=['executive','methodology','sources','risk_overview','activity_results','assignment_results','risk_acceptance','controls','remediation','changes','conclusion','appendices']
MAX_ROWS=20000
MAX_OUTPUT=32*1024*1024
render_lock=threading.RLock()
HEADINGS={
 'en':['Executive Summary','Scope & Methodology','Data Sources & Evidence Limitations','Risk Overview','Activity Review Results','Role Assignment Review Results','Risk Acceptance Decisions','Compensating Controls','Outstanding Remediation','Changes Since Previous Review','Conclusion and Approval','Detailed Appendices'],
 'no':['Sammendrag','Omfang og metode','Datakilder og begrensninger','Risikooversikt','Resultater: aktivitetsgjennomgang','Resultater: rolletildelinger','Beslutninger om risikoaksept','Kompenserende kontroller','Gjenstående utbedring','Endringer siden forrige gjennomgang','Konklusjon og godkjenning','Vedlegg']}

class Options(StrictModel):
    title:str=Field(default='SoD Access Review',min_length=1,max_length=160)
    language:Literal['en','no']='en'
    prepared_by:str=Field(default='',max_length=120)
    reviewer:str=Field(default='',max_length=120)
    reviewer_role:str=Field(default='',max_length=120)
    approver:str=Field(default='',max_length=120)
    approver_role:str=Field(default='',max_length=120)
    report_date:date=Field(default_factory=date.today)
    document_version:str=Field(default='1.0',min_length=1,max_length=80)
    status:Literal['Draft','For review','Approved snapshot']='Draft'
    management_comments:str=Field(default='',max_length=12000)
    include_appendices:bool=True
    sections:list[Literal['executive','methodology','sources','risk_overview','activity_results','assignment_results','risk_acceptance','controls','remediation','changes','conclusion','appendices']]=Field(default_factory=lambda:list(SECTIONS),max_length=12)
    previous_period_id:str|None=Field(default=None,pattern=r'^[a-f0-9]{32}$')
    @field_validator('*',mode='before')
    @classmethod
    def readable(cls,value):
        return value.strip() if isinstance(value,str) else value
    @model_validator(mode='after')
    def unique_sections(self):
        if len(self.sections)!=len(set(self.sections)):raise ValueError('Choose each report section once.')
        return self


def clean(value):
    text='' if value is None else str(value)
    return ''.join(c if c in '\t\r\n' or 0x20<=ord(c)<=0xD7FF or 0xE000<=ord(c)<=0xFFFD or 0x10000<=ord(c)<=0x10FFFF else '\ufffd' for c in text)

def localized_date(value):
    if not value:return '—'
    day=date.fromisoformat(str(value)[:10]);return f'{day.day:02}.{day.month:02}.{day.year:04}'

def localized_stamp(value):
    if not value:return '—'
    stamp=datetime.fromisoformat(str(value))
    if stamp.tzinfo:stamp=stamp.astimezone(timezone.utc)
    return f'{stamp.day:02}.{stamp.month:02}.{stamp.year:04} {stamp.hour:02}:{stamp.minute:02}'



NO_LIMITATION='Potensielle konflikter er basert på rolle- og transaksjonsdata, ikke bekreftet effektiv SAP-autorisasjon. Navn er egenrapporterte og er ikke verifiserte digitale signaturer.'
EN_LIMITATION='Potential conflicts are based on role-derived transaction evidence, not verified effective SAP authorization. Names are self-reported and are not verified digital signatures.'


def _limitation(language):
    return NO_LIMITATION if language=='no' else EN_LIMITATION


def _table(header,rows):
    return [header,*rows] if rows else []


def _event_text(item):
    event=item['event']
    return (event.reviewer if event else '')+' / '+localized_stamp(event.timestamp if event else None)


def _counts(state,kind,*names):
    return sum(1 for life,_ in state[kind].values() if life in names)


def _issued(period_id):
    return [row for row in decisions.context_summary(period_id)['reports']]


def model(identifier,options):
    options=Options.model_validate(options.model_dump() if isinstance(options,Options) else options)
    details=periods.details(identifier);period=details['period'];saved=details['snapshot'];frozen=period['state'] in periods.FROZEN
    if options.status=='Approved snapshot' and not frozen:raise HTTPException(422,'Only a frozen approved period can be labelled Approved snapshot.')
    approval=saved.get('approval',{})
    if frozen and any(value and value!=approval.get(key) for key,value in [('reviewer',options.reviewer),('approver',options.approver)]):raise HTTPException(422,'A report cannot override the recorded approval identity of an approved snapshot.')
    findings=saved['analysis']['users'];legacy_reviews=saved['reviews']['items'];risks=saved['risks']
    path_count=sum(len(paths) for row in findings for paths in row['evidence'].values())
    mapping_count=sum(len(rows) for risk in risks for rows in risk['source']['activities'].values())
    if options.include_appendices and 'appendices' in options.sections and path_count+len(findings)+len(risks)+mapping_count+len(legacy_reviews)>MAX_ROWS:raise HTTPException(413,'Detailed report exceeds 20,000 rows. Exclude appendices and use complete CSV exports for detailed evidence.')
    previous=None
    if options.previous_period_id:
        previous_detail=periods.details(options.previous_period_id)
        if previous_detail['period']['state'] not in periods.FROZEN:raise HTTPException(422,'Choose an approved previous period for reproducible report comparison.')
        previous=periods.compare(options.previous_period_id,identifier)
    v2=details['model']==2
    limitation=_limitation(options.language)
    bundle=scope.load(identifier);view=scope.model_for(bundle);state=governance.states(view,scope.latest_for(bundle));actions=scope.actions_for(bundle)
    frozen_verification=(bundle['frozen_decisions'] or {}).get('verification') or {}
    verify=(lambda user,aid:frozen_verification.get(aid,'Not assessed at approval')) if bundle['frozen_decisions'] is not None else scope.make_verifier()
    rows,summary=governance.remediation_rows(view,state,actions,verify,today=options.report_date) if v2 else ([],{})
    items=governance.queue_items(view,state) if v2 else []
    by_kind={kind:[item for item in items if item['kind']==kind] for kind in decisions.DECISIONS}
    by_risk=Counter(row['risk_id'] for row in findings);by_criticality=Counter(row['criticality'] for row in findings)
    by_category=Counter((row.get('risk') or {}).get('business_category') or 'Not specified' for row in findings)
    enabled=[row for row in risks if row['local']['enabled'] and row['source']['supported']]
    open_actions=[item for item in actions if item.status in {'Open','In progress'}]
    overdue=[item for item in open_actions if item.due_date and item.due_date<options.report_date]
    untracked=len({(row['user'],row['assignment_id']) for row in rows if row['recommended']=='Remove assignment' and not row['action']})
    sections=[]
    def section(key,paragraphs,tables=()):
        if key in options.sections:sections.append(dict(key=key,title=HEADINGS[options.language][SECTIONS.index(key)],paragraphs=paragraphs,tables=[table for table in tables if table]))
    users_evaluated=saved['source_counts']['users']
    user_risk=len(findings)
    if v2:
        metrics=[['Measure','Count','Unit'],['SAP users evaluated',str(users_evaluated),'users'],['Users with detected potential conflicts',str(len(view)),'users'],['Detected potential conflicts',str(user_risk),'user-risk findings'],
                 ['Activities in review scope',str(len(state['activity'])),'user-activity pairs'],['Activities approved',str(_counts(state,'activity','Approved')),'activities'],['Activities approved conditionally',str(_counts(state,'activity','Conditional')),'activities'],
                 ['Activities marked for removal',str(_counts(state,'activity','Removal required')),'activities'],['Activity reviews pending or outdated',str(_counts(state,'activity','Pending','Outdated')),'activities'],
                 ['Role assignments to keep',str(_counts(state,'assignment','Keep')),'assignments'],['Role assignments marked for removal',str(_counts(state,'assignment','Removal required')),'assignments'],
                 ['Risks accepted',str(_counts(state,'acceptance','Accepted')),'user-risk findings'],['Risks rejected',str(_counts(state,'acceptance','Rejected')),'user-risk findings'],['Risk decisions pending or outdated',str(_counts(state,'acceptance','Pending','Outdated')),'user-risk findings'],
                 ['Open remediation actions',str(len(open_actions)),'actions'],['Overdue remediation actions',str(len(overdue)),'actions'],['Removal recommendations without a tracked action',str(untracked),'assignments']]
        lead=[f"{len(view)} of {users_evaluated} evaluated SAP users have {user_risk} detected potential conflicts across {len(enabled)} enabled supported risks.",f"Review status: {period['state']}. A proposed removal is not completed remediation; {len(open_actions)} tracked actions remain open."]
    else:
        metrics=[['Measure','Count','Unit'],['SAP users evaluated',str(users_evaluated),'users'],['Users with detected potential conflicts',str(len({row['subject'] for row in findings})),'users'],['Detected potential conflicts',str(user_risk),'user-risk findings'],*[[f'Legacy risk decisions: {key}',str(value),'findings'] for key,value in saved['reviews']['summary'].items()]]
        lead=[f"{len({row['subject'] for row in findings})} of {users_evaluated} evaluated SAP users have {user_risk} detected potential conflicts.",'This period predates activity, role-assignment and risk-acceptance review; only legacy risk decisions are available.']
    section('executive',[*lead,limitation],[metrics])
    meta=saved['source_metadata'];names={'roles':'Role Catalogue','users':'User–Role Mapping','sod':'SoD Matrix','employees':'Employee Directory'}
    section('methodology',[f"Evaluation date: {localized_date(saved['evaluation_date'])}. Review period: {localized_date(period['start'])} - {localized_date(period['end'])}. Policy: {saved['analysis']['methodology']['policy']}.",
        'Method: potential conflicts are calculated from imported role and transaction evidence and enabled risk definitions. Reviewers decide whether each user needs a conflict-relevant activity, whether each supplying role assignment is necessary, and separately whether each remaining risk is accepted. Review decisions never change the calculation.',
        saved['limitation'],'Unsupported and locally disabled risks are excluded; unknown assignment validity is not treated as active.'],[_table(['Scope','Count'],[[key,str(value)] for key,value in saved['source_counts'].items()])])
    section('sources',['Missing or incomplete sources are not evidence that no access or conflict exists.',limitation,'Source versions and checksums are listed in the technical appendix.'],
            [_table(['Source','Imported (UTC)','Checked (UTC)'],[[names.get(key,key),localized_stamp(meta.get(key,{}).get('imported_at')),localized_stamp(meta.get(key,{}).get('checked_at'))] for key in saved['source_versions']])])
    section('risk_overview',['Source criticality codes are preserved literally; no unsupported severity interpretation is applied.'],
            [_table(['Source criticality','Findings'],[[key,str(value)] for key,value in sorted(by_criticality.items())]),_table(['Risk','Potential findings'],[[key,str(value)] for key,value in sorted(by_risk.items())]),_table(['Business area','Findings'],[[key,str(value)] for key,value in sorted(by_category.items())])])
    if v2:
        a_items=by_kind['activity'];s_items=by_kind['assignment'];r_items=by_kind['acceptance']
        section('activity_results',['Each user-activity pair is reviewed once and may contribute to several risks.'],[_table(['Decision','Activities'],[[key,str(value)] for key,value in sorted(Counter(item['lifecycle'] for item in a_items).items())]),
            _table(['SAP user / activity','Decision','Reviewer / timestamp','Justification / conditions'],[[item['user']+' / '+item['ref'],item['lifecycle'],_event_text(item),(item['event'].justification+('\n'+item['event'].controls if item['event'].controls else '')) if item['event'] else ''] for item in a_items if item['lifecycle'] in {'Conditional','Removal required'}])])
        section('assignment_results',['An approved activity does not mean every supplying role assignment is necessary. A removal decision is a recommendation, not confirmed removal in SAP.'],[_table(['Decision','Assignments'],[[key,str(value)] for key,value in sorted(Counter(item['lifecycle'] for item in s_items).items())]),
            _table(['SAP user / role','Decision','Reviewer / timestamp','Justification'],[[item['user']+' / '+item['ref'],item['lifecycle'],_event_text(item),item['event'].justification if item['event'] else ''] for item in s_items if item['lifecycle'] in {'Removal required','Keep'}])])
        section('risk_acceptance',['Risk acceptance is a separate business decision. Accepted risks remain detected conflicts.'],[_table(['Decision','Risks'],[[key,str(value)] for key,value in sorted(Counter(item['lifecycle'] for item in r_items).items())]),
            _table(['SAP user / risk','Decision','Reviewer / approver','Expires','Justification'],[[item['user']+' / '+item['ref'],item['lifecycle'],(item['event'].reviewer+' / '+item['event'].approver) if item['event'] else '',localized_date(item['event'].expires) if item['event'] and item['event'].expires else '—',item['event'].justification if item['event'] else ''] for item in r_items if item['event']])])
        control_rows=[[item['user']+' / '+item['ref'],item['event'].controls,item['event'].reviewer] for item in a_items+r_items if item['event'] and item['event'].controls]
    else:
        section('activity_results',['Not recorded: this period predates activity review.'])
        section('assignment_results',['Not recorded: this period predates role-assignment review.'])
        legacy=lambda row:(row.get('event') or {}).get('annotation',{})
        section('risk_acceptance',['Legacy risk decisions are retained as recorded and were not converted to risk acceptance.'],[_table(['SAP user / risk','Legacy decision','Reviewer / rationale'],[[row['finding']['subject']+' / '+row['finding']['risk_id'],row['decision'],legacy(row).get('reviewer','')+' / '+legacy(row).get('rationale','')] for row in legacy_reviews if row.get('event')])])
        control_rows=[[row['finding']['subject']+' / '+row['finding']['risk_id'],legacy(row).get('mitigating_controls',''),legacy(row).get('reviewer','')] for row in legacy_reviews if legacy(row).get('mitigating_controls')]
    section('controls',['Controls are recorded by reviewers and are not independently verified by SAP Lens.'],[_table(['SAP user / risk or activity','Controls or conditions','Reviewer'],control_rows)])
    action_rows=[[item.user+' / '+(item.activity or item.risk_id or item.role),item.recommended,item.owner or '—',localized_date(item.due_date.isoformat() if item.due_date else None),item.status+(' (overdue)' if item in overdue else '')] for item in actions if item.status!='Cancelled']
    section('remediation',['A manually completed action is not proof that access was removed. Only later source evidence can establish absence, subject to source completeness.',
        f"{untracked} removal recommendations have no tracked action."],[_table(['Recommended handling','Rows'],[[key,str(summary.get(key,0))] for key in governance.GROUPS]) if v2 else [],_table(['User / reference','Recommended','Owner','Due','Status'],action_rows)])
    section('changes',['No previous review selected; change analysis was not calculated.'] if previous is None else ['Missing records or changed coverage do not establish resolved access.',f"Source coverage changed: {previous['source_coverage_changed']}. Changed risk definitions: {', '.join(previous['changed_risks']) or 'None'}."],
            [] if previous is None else [_table(['Change classification','Findings'],[[key,str(value)] for key,value in previous['summary'].items()])])
    section('conclusion',[options.management_comments or 'No additional management comments recorded.',f"Recorded period approval: {'Yes' if frozen else 'No'} ({period['state']}). Report generation alone does not approve a review.",
        f"Reviewer: {approval.get('reviewer') or options.reviewer or '________________'} · {options.reviewer_role}",f"Approver: {approval.get('approver') or options.approver or '________________'} · {options.approver_role}",
        f"Recorded approval date: {localized_date(approval.get('date'))}",'Reviewer signature: ________________________    Date: ______________','Approver signature: ________________________    Date: ______________',limitation])
    if options.include_appendices and 'appendices' in options.sections:
        lang=options.language
        catalogue_rows=[['Risk / source criticality / type','Activities','Business guidance / consequence / controls']];transaction_rows=[['Risk','Activity slot / identifier','Transaction','Description']]
        for row in risks:
            source=row['source'];local=row['local'];guidance='\n'.join(local.get(field+'_'+lang,'') for field in ('explanation','consequence','mitigating_controls','review_guidance'))
            catalogue_rows.append([row['risk_id']+' / '+source['criticality']+' / '+source['risk_type']+' / '+('Enabled' if local['enabled'] else 'Disabled')+' / '+row['description_review_status'],source['activity1']+' / '+source['activity2'],guidance or source['source_text']])
            for slot,mappings in source['activities'].items():
                for mapping in mappings:transaction_rows.append([row['risk_id'],slot+' / '+mapping['activity'],mapping['tcode'],mapping['ttext'] or 'Not supplied'])
        evidence_rows=[['SAP user / risk','Side / T-code','Assigned / catalogue role','Single role / validity']]
        for row in findings:
            for side,paths in row['evidence'].items():
                for path in paths:evidence_rows.append([row['subject']+' / '+row['risk_id'],side+' / '+path['tcode'],path.get('actual_assigned_role','')+'\n'+path['matched_catalogue_pattern']+' / '+path.get('matching_status',''),path['single_role']+'\n'+localized_date(path.get('role_valid_from'))+' - '+localized_date(path.get('role_valid_to'))+'\n'+path.get('interval_status','')+' / '+path.get('user_group','')])
        decision_rows=[['Type','SAP user / reference','Decision','Reviewer / approver / timestamp','Justification / controls']]+[[item['kind'],item['user']+' / '+item['ref'],item['lifecycle'],(item['event'].reviewer+' / '+item['event'].approver+' / '+localized_stamp(item['event'].timestamp)) if item['event'] else '',(item['event'].justification+'\n'+item['event'].controls) if item['event'] else ''] for item in items if item['event']]
        remediation_detail=[['SAP user','Activity / risks','Role / assignment','Recommended / owner / status','Verification']]+[[row['user'],row['activity']+' / '+', '.join(row['risks']),row['role']+'\n'+row['assignment_id'][:12],row['recommended']+' / '+(row['owner'] or '—')+' / '+row['action_status'],row['verification']] for row in rows]
        technical=[['Item','Value'],['Snapshot SHA-256',details['checksum']],['Review period identifier',period['id']],['Evaluation policy',saved['analysis']['methodology']['policy']],['Snapshot captured (UTC)',localized_stamp(saved['captured_at'])],
                   *[['Source version: '+names.get(key,key),value] for key,value in saved['source_versions'].items()],*[['Period transition: '+item['to_state'],localized_stamp(item['timestamp'])+' / '+item['actor']+(' / '+item['note'] if item['note'] else '')] for item in period.get('history',[])]]
        section('appendices',[f"Source capture: {localized_stamp(saved['captured_at'])} UTC. Methodology: {saved['analysis']['methodology']['policy']}.",limitation],[catalogue_rows,transaction_rows,evidence_rows,decision_rows if len(decision_rows)>1 else [],remediation_detail if len(remediation_detail)>1 else [],technical])
    total=sum(len(table) for item in sections for table in item['tables'])
    if total>MAX_ROWS:raise HTTPException(413,'Detailed report exceeds 20,000 rows. Exclude appendices and use complete CSV exports for detailed evidence.')
    data=dict(version=2,title=options.title,language=options.language,status=options.status,document_version=options.document_version,report_date=options.report_date.isoformat(),prepared_by=options.prepared_by,period=period,organization=saved['organization'],logo_id=saved['logo_id'],snapshot_checksum=details['checksum'],sections=sections,limitation=limitation)
    return _seal(data)


def _seal(data):
    serialized=json.dumps(data,sort_keys=True,ensure_ascii=False).encode()
    if len(serialized)>8*1024*1024:raise HTTPException(413,'Report model exceeds 8 MiB. Exclude appendices and export detailed CSV evidence separately.')
    data['model_checksum']=sha256(serialized).hexdigest()
    return data


class RemediationOptions(StrictModel):
    title:str=Field(default='Access Remediation Report',min_length=1,max_length=160)
    language:Literal['en','no']='en'
    prepared_by:str=Field(default='',max_length=120)
    report_date:date=Field(default_factory=date.today)
    document_version:str=Field(default='1.0',min_length=1,max_length=80)
    recommended:list[Literal['Remove assignment','Investigate assignment','Apply compensating control','Maintain access','No action required']]=Field(default_factory=lambda:list(governance.GROUPS),max_length=5)


def remediation_model(context,options):
    """Operational report for one review context; independent of the formal approval document."""
    options=RemediationOptions.model_validate(options.model_dump() if isinstance(options,RemediationOptions) else options)
    bundle=scope.load(context);view=scope.model_for(bundle);state=governance.states(view,scope.latest_for(bundle));actions=scope.actions_for(bundle)
    frozen=bundle['frozen_decisions']
    verify=(lambda user,aid:(frozen.get('verification') or {}).get(aid,'Not assessed at approval')) if frozen is not None else scope.make_verifier()
    rows,summary=governance.remediation_rows(view,state,actions,verify,today=options.report_date)
    rows=[row for row in rows if row['recommended'] in options.recommended]
    if len(rows)>MAX_ROWS:raise HTTPException(413,'Remediation report exceeds 20,000 rows. Filter by recommended handling or use CSV.')
    from config import get_settings
    settings=get_settings();period=bundle['period'] or dict(id='current',name='Current evidence',start=bundle['as_of'],end=bundle['as_of'],state='Current',history=[])
    en=options.language=='en'
    titles={'Remove assignment':'Remove assignment' if en else 'Fjern tildeling','Investigate assignment':'Investigate assignment' if en else 'Undersøk tildeling','Apply compensating control':'Apply compensating control' if en else 'Innfør kompenserende kontroll','Maintain access':'Maintain access' if en else 'Behold tilgang','No action required':'No action required' if en else 'Ingen tiltak nødvendig'}
    sections=[dict(key='summary',title='Summary' if en else 'Sammendrag',paragraphs=['A proposed removal is not completed remediation. Verification reflects source evidence only after a refresh and only when source coverage is complete.' if en else 'Et forslag om fjerning er ikke gjennomført utbedring. Verifisering bygger på kildedata etter oppdatering og kun ved fullstendig dekning.',_limitation(options.language)],
                    tables=[[['Recommended handling','Rows'],*[[titles[key],str(summary.get(key,0))] for key in governance.GROUPS],['Awaiting review (excluded)',str(summary.get('undecided',0))],['Overdue tracked actions',str(summary.get('overdue',0))]]])]
    for key in governance.GROUPS:
        if key not in options.recommended:continue
        group=[row for row in rows if row['recommended']==key]
        table=[['SAP user','Activity / risks','Role / validity','Decisions','Reason / controls','Owner / due / status','Verification']]+[[row['user'],row['activity']+' / '+', '.join(row['risks']),row['role']+'\n'+localized_date(row['valid_from'])+' - '+localized_date(row['valid_to']),f"Activity: {row['activity_decision']}\nAssignment: {row['assignment_decision']}\nRisk: {', '.join(row['risk_acceptance'])}",row['reason'] or row['controls'],(row['owner'] or '—')+' / '+localized_date(row['due_date'])+' / '+row['action_status']+(' (overdue)' if row['overdue'] else ''),row['verification']] for row in group]
        sections.append(dict(key=key,title=titles[key],paragraphs=[f'{len(group)} rows.'],tables=[table] if group else []))
    data=dict(version=2,kind='remediation',title=options.title,language=options.language,status='Draft',document_version=options.document_version,report_date=options.report_date.isoformat(),prepared_by=options.prepared_by,
              period=period,organization=settings.organization.model_dump(),logo_id=settings.logo_id,snapshot_checksum=(bundle['generation'] if bundle['period'] else 'live-evidence'),sections=sections,limitation=_limitation(options.language),
              rows=[{key:row[key] for key in ('user','activity','risks','role','assignment_id','valid_from','valid_to','activity_decision','assignment_decision','risk_acceptance','recommended','reason','controls','owner','due_date','action_status','overdue','verification')} for row in rows])
    return _seal(data)


def report_logo(data):
    content=logo_bytes(data['logo_id'])
    if data['logo_id'] and content is None:raise HTTPException(409,'The frozen report logo is unavailable or invalid. Restore its private branding backup before exporting.')
    return content


def render_docx(data):
    from docx import Document
    from docx.shared import Inches,Pt
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    document=Document();section=document.sections[0];section.top_margin=section.bottom_margin=Inches(.65)
    style=document.styles['Normal'];style.font.name='Arial';style.font.size=Pt(10)
    document.core_properties.title=clean(data['title']);document.core_properties.author=clean(data['prepared_by']);document.core_properties.created=document.core_properties.modified=datetime.fromisoformat(data['report_date']).replace(tzinfo=timezone.utc)
    section.header.paragraphs[0].text=clean(data['organization']['name'])+' · SAP Lens'
    footer=section.footer.paragraphs[0];footer.text='SAP Lens · ';field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
    logo=report_logo(data)
    if logo:
        from PIL import Image as RasterImage
        with RasterImage.open(BytesIO(logo)) as image:width,height=image.size
        scale=min(1.4/width,.9/height)
        document.add_picture(BytesIO(logo),width=Inches(width*scale),height=Inches(height*scale))
    document.add_heading(clean(data['title']),0)
    for text in (data['organization']['name'],data['organization']['platform']+' · '+data['organization']['system_id']+' / '+data['organization']['client'],data['period']['name'],localized_date(data['period']['start'])+' - '+localized_date(data['period']['end']),data['status']+' · '+data['document_version'],'Prepared by: '+(data['prepared_by'] or 'Not specified'),'Report date: '+localized_date(data['report_date']),data['limitation']):document.add_paragraph(clean(text))
    document.add_paragraph('Snapshot reference: '+data['snapshot_checksum'][:12]+' · Report model reference: '+data['model_checksum'][:12]);document.add_page_break()
    for item in data['sections']:
        document.add_heading(item['title'],level=1)
        for text in item['paragraphs']:document.add_paragraph(clean(text))
        for rows in item['tables']:
            table=document.add_table(rows=1,cols=len(rows[0]));table.style='Light Shading Accent 1'
            for index,text in enumerate(rows[0]):table.rows[0].cells[index].text=clean(text)
            repeat=OxmlElement('w:tblHeader');table.rows[0]._tr.get_or_add_trPr().append(repeat)
            for row in rows[1:]:
                cells=table.add_row().cells
                for index,text in enumerate(row):cells[index].text=clean(text)
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:run.font.size=Pt(8)
    document.add_heading('Document integrity' if data['language']=='en' else 'Dokumentintegritet',level=1)
    document.add_paragraph('Snapshot SHA-256: '+data['snapshot_checksum']);document.add_paragraph('Report model SHA-256: '+data['model_checksum'])
    output=BytesIO();document.save(output)
    # Normalize ZIP timestamps/order so identical frozen models render reproducibly.
    normalized=BytesIO()
    with ZipFile(BytesIO(output.getvalue())) as source,ZipFile(normalized,'w',ZIP_DEFLATED) as target:
        for name in sorted(source.namelist()):
            info=ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=ZIP_DEFLATED;target.writestr(info,source.read(name))
    return normalized.getvalue()


def render_pdf(data):
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,LongTable,TableStyle,Image
    from reportlab.pdfgen.canvas import Canvas
    fonts=Path(reportlab.__file__).parent/'fonts'
    if 'SAPLens' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('SAPLens',str(fonts/'Vera.ttf')));pdfmetrics.registerFont(TTFont('SAPLens-Bold',str(fonts/'VeraBd.ttf')))
    supported=pdfmetrics.getFont('SAPLens').face.charToGlyph
    strings=[data['title'],data['prepared_by'],data['organization']['name'],data['organization']['platform'],data['organization']['system_id'],data['organization']['client'],data['period']['name']]
    for section in data['sections']:
        strings.extend([section['title'],*section['paragraphs']]);strings.extend(str(value) for table in section['tables'] for row in table for value in row)
    if any(ord(char) not in supported for value in strings for char in clean(value) if char not in '\n\r\t'):
        raise HTTPException(422,'Some report characters are outside the bundled PDF font coverage. Use editable DOCX for this content or replace unsupported symbols explicitly.')
    styles=getSampleStyleSheet()
    for name in ('Normal','BodyText'):styles[name].fontName='SAPLens';styles[name].fontSize=9;styles[name].leading=13
    for name in ('Title','Heading1','Heading2'):styles[name].fontName='SAPLens-Bold'
    cell=ParagraphStyle('Cell',fontName='SAPLens',fontSize=7.5,leading=10,wordWrap='CJK')
    paragraph=lambda text,style=styles['BodyText']:Paragraph(escape(clean(text)).replace('\n','<br/>'),style)
    output=BytesIO();document=SimpleDocTemplate(output,pagesize=A4,rightMargin=40,leftMargin=40,topMargin=48,bottomMargin=48,title=clean(data['title']),author=clean(data['prepared_by']))
    flow=[];logo=report_logo(data)
    if logo:
        from PIL import Image as RasterImage
        with RasterImage.open(BytesIO(logo)) as image:width,height=image.size
        scale=min(100/width,70/height);flow.append(Image(BytesIO(logo),width=width*scale,height=height*scale))
    flow.extend([paragraph(data['title'],styles['Title']),Spacer(1,18)])
    for text in (data['organization']['name'],data['organization']['platform']+' · '+data['organization']['system_id']+' / '+data['organization']['client'],data['period']['name'],localized_date(data['period']['start'])+' - '+localized_date(data['period']['end']),data['status']+' · '+data['document_version'],'Prepared by: '+(data['prepared_by'] or 'Not specified'),'Report date: '+localized_date(data['report_date']),data['limitation'],'Snapshot reference: '+data['snapshot_checksum'][:12]+' · Report model reference: '+data['model_checksum'][:12]):flow.extend([paragraph(text),Spacer(1,10)])
    flow.append(PageBreak())
    for item in data['sections']:
        flow.append(paragraph(item['title'],styles['Heading1']))
        for text in item['paragraphs']:flow.extend([paragraph(text),Spacer(1,8)])
        for rows in item['tables']:
            table=LongTable([[paragraph(text,cell) for text in row] for row in rows],colWidths=[document.width/len(rows[0])]*len(rows[0]),repeatRows=1,splitInRow=1,hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e8edf3')),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5),('LINEBELOW',(0,0),(-1,0),.5,colors.HexColor('#758296')),('LINEBELOW',(0,1),(-1,-1),.2,colors.HexColor('#d4dae2'))]));flow.extend([table,Spacer(1,12)])
    flow.append(paragraph('Document integrity' if data['language']=='en' else 'Dokumentintegritet',styles['Heading1']))
    for text in ('Snapshot SHA-256: '+data['snapshot_checksum'],'Report model SHA-256: '+data['model_checksum']):flow.extend([paragraph(text),Spacer(1,6)])
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont('SAPLens',8);canvas.drawString(40,26,'SAP Lens · '+data['document_version']);canvas.drawRightString(A4[0]-40,26,str(doc.page));canvas.restoreState()
    def canvas_factory(*args,**kwargs):kwargs['invariant']=1;return Canvas(*args,**kwargs)
    document.build(flow,onFirstPage=footer,onLaterPages=footer,canvasmaker=canvas_factory)
    return output.getvalue()


def render(data,kind):
    from reportlab.platypus.doctemplate import LayoutError
    try:
        with render_lock:payload=render_docx(data) if kind=='docx' else render_pdf(data) if kind=='pdf' else None
    except (ValueError,OSError,RuntimeError,LayoutError,UnicodeError):
        raise HTTPException(422,'Report layout could not be generated safely. Exclude appendices or shorten unusually long content and retry.') from None
    if payload is None:raise HTTPException(422,'Choose DOCX or PDF.')
    if len(payload)>MAX_OUTPUT:raise HTTPException(413,'Report exceeds 32 MiB. Exclude detailed appendices and use CSV for evidence.')
    return payload
