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

SECTIONS=['executive','methodology','risk_overview','changes','review_results','controls','actions','conclusion','appendices']
MAX_ROWS=20000
MAX_OUTPUT=32*1024*1024
render_lock=threading.RLock()
HEADINGS={
 'en':['Executive Summary','Scope & Methodology','Risk Overview','Changes Since Previous Review','Review Results','Mitigating Controls','Remediation Actions','Conclusion and Approval','Appendices'],
 'no':['Sammendrag','Omfang og metode','Risikooversikt','Endringer siden forrige gjennomgang','Resultater fra gjennomgangen','Kompenserende kontroller','Utbedringstiltak','Konklusjon og godkjenning','Vedlegg']}

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
    sections:list[Literal['executive','methodology','risk_overview','changes','review_results','controls','actions','conclusion','appendices']]=Field(default_factory=lambda:list(SECTIONS),max_length=9)
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


def model(identifier,options):
    options=Options.model_validate(options.model_dump() if isinstance(options,Options) else options)
    details=periods.details(identifier);period=details['period'];saved=details['snapshot'];closed=period['state']=='Approved / closed'
    if options.status=='Approved snapshot' and not closed:raise HTTPException(422,'Only a frozen closed period can be labelled Approved snapshot.')
    approval=saved.get('approval',{})
    if closed and any(value and value!=approval.get(key) for key,value in [('reviewer',options.reviewer),('approver',options.approver)]):raise HTTPException(422,'A report cannot override the recorded approval identity of a closed snapshot.')
    findings=saved['analysis']['users'];reviews=saved['reviews']['items'];risks=saved['risks']
    path_count=sum(len(paths) for row in findings for paths in row['evidence'].values())
    mapping_count=sum(len(rows) for risk in risks for rows in risk['source']['activities'].values())
    if options.include_appendices and 'appendices' in options.sections and path_count+len(findings)+len(risks)+mapping_count+len(reviews)>MAX_ROWS:raise HTTPException(413,'Detailed report exceeds 20,000 rows. Exclude appendices and use complete CSV exports for detailed evidence.')
    previous=None
    if options.previous_period_id:
        previous_detail=periods.details(options.previous_period_id)
        if previous_detail['period']['state']!='Approved / closed':raise HTTPException(422,'Choose a closed previous period for reproducible report comparison.')
        previous=periods.compare(options.previous_period_id,identifier)
    by_risk=Counter(row['risk_id'] for row in findings);by_criticality=Counter(row['criticality'] for row in findings)
    by_category=Counter((row.get('risk') or {}).get('business_category') or 'Not specified' for row in findings)
    annotation=lambda row:(row.get('event') or {}).get('annotation',{})
    actions=[row for row in reviews if row['decision'] in {'Access removal required','Further investigation required'} and annotation(row).get('action_status') not in {'Completed','Not applicable'}]
    enabled=[row for row in risks if row['local']['enabled'] and row['source']['supported']]
    sections=[]
    def section(key,paragraphs,tables=[]):
        if key in options.sections:sections.append(dict(key=key,title=HEADINGS[options.language][SECTIONS.index(key)],paragraphs=paragraphs,tables=tables))
    limitation=('Potensielle konflikter er basert på rolle- og transaksjonsdata, ikke bekreftet effektiv SAP-autorisasjon. Navn er egenrapporterte og er ikke verifiserte digitale signaturer.' if options.language=='no' else 'Potential conflicts are based on role-derived transaction evidence, not verified effective SAP authorization. Names are self-reported and are not verified digital signatures.')
    section('executive',[f"{len(findings)} potential findings across {len({row['subject'] for row in findings})} SAP users; {len(enabled)} enabled supported risks.",f"Review status: {period['state']}. Outstanding remediation actions: {len(actions)}.",limitation],[[['Review lifecycle','Findings'],*[[key,str(value)] for key,value in saved['reviews']['summary'].items()]]])
    source_rows=[['Source','Snapshot version','Imported / checked (UTC)']]+[[key,value, localized_stamp(saved['source_metadata'].get(key,{}).get('imported_at'))+' / '+localized_stamp(saved['source_metadata'].get(key,{}).get('checked_at'))] for key,value in saved['source_versions'].items()]
    section('methodology',[f"Evaluation date: {localized_date(saved['evaluation_date'])}. Policy: {saved['analysis']['methodology']['policy']}.",saved['limitation'],limitation,'Unsupported and locally disabled risks are excluded from current findings; unknown assignment validity is not active.',f"Snapshot checksum: {details['checksum']}"],[source_rows,[['Scope','Count'],*[[key,str(value)] for key,value in saved['source_counts'].items()]]])
    section('risk_overview',['Source criticality codes are preserved literally; no unsupported severity or savings interpretation is applied.'],[[['Source criticality','Findings'],*[[key,str(value)] for key,value in sorted(by_criticality.items())]],[['Risk','Potential findings'],*[[key,str(value)] for key,value in sorted(by_risk.items())]],[['Business area','Findings'],*[[key,str(value)] for key,value in sorted(by_category.items())]]])
    section('changes',['No previous review selected; change analysis was not calculated.'] if previous is None else ['Missing records or changed coverage do not establish resolved access.',f"Source coverage changed: {previous['source_coverage_changed']}. Changed risk definitions: {', '.join(previous['changed_risks']) or 'None'}."],[] if previous is None else [[['Change classification','Findings'],*[[key,str(value)] for key,value in previous['summary'].items()]]])
    decisions=Counter((row['finding']['risk_id'],row['decision']) for row in reviews)
    section('review_results',['Recorded decisions remain distinct from lifecycle state. Detailed justifications are retained in the appendices and review CSV.'],[[['Risk','Decision','Findings'],*[[risk,decision,str(count)] for (risk,decision),count in sorted(decisions.items())]]])
    controls=[['SAP user / risk','Controls','Reviewer / rationale']]+[[row['finding']['subject']+' / '+row['finding']['risk_id'],annotation(row).get('mitigating_controls',''),annotation(row).get('reviewer','')+' / '+annotation(row).get('rationale','')] for row in reviews if annotation(row).get('mitigating_controls')]
    section('controls',['Controls are recorded by reviewers, not independently verified by SAP Lens.'],[controls] if len(controls)>1 else [])
    action_rows=[['SAP user / risk','Action owner / due','Status / completion notes','Required action']]+[[row['finding']['subject']+' / '+row['finding']['risk_id'],annotation(row).get('action_owner','')+' / '+localized_date(annotation(row).get('target_date')),annotation(row).get('action_status','')+' / '+annotation(row).get('completion_notes',''),row['decision']+' / '+annotation(row).get('rationale','')] for row in actions]
    section('actions',[f'{len(actions)} outstanding actions. Completing an action does not itself establish removal of SAP access.'],[action_rows] if len(action_rows)>1 else [])
    section('conclusion',[options.management_comments or 'No additional management comments recorded.',f"Locally recorded period approval: {'Yes' if closed else 'No'}. Report generation alone does not approve a review.",f"Reviewer: {approval.get('reviewer') or options.reviewer or '________________'} · {options.reviewer_role}",f"Approver: {approval.get('approver') or options.approver or '________________'} · {options.approver_role}",f"Recorded approval date: {localized_date(approval.get('date'))}",'Reviewer signature: ________________________    Date: ______________','Approver signature: ________________________    Date: ______________',limitation])
    if options.include_appendices and 'appendices' in options.sections:
        lang='no' if options.language=='no' else 'en'
        catalogue_rows=[['Risk / source criticality / type','Activities','Business guidance / consequence / controls']]
        transaction_rows=[['Risk','Activity slot / identifier','Transaction','Description']]
        for row in risks:
            source=row['source'];local=row['local'];guidance='\n'.join(local.get(field+'_'+lang,'') for field in ('explanation','consequence','mitigating_controls','review_guidance'))
            catalogue_rows.append([row['risk_id']+' / '+source['criticality']+' / '+source['risk_type']+' / '+('Enabled' if local['enabled'] else 'Disabled')+' / '+row['description_review_status'],source['activity1']+' / '+source['activity2'],guidance or source['source_text']])
            for slot,mappings in source['activities'].items():
                for mapping in mappings:transaction_rows.append([row['risk_id'],slot+' / '+mapping['activity'],mapping['tcode'],mapping['ttext'] or 'Not supplied'])
        evidence_rows=[['SAP user / risk','Side / T-code','Assigned / catalogue role','Single role / validity']]
        for row in findings:
            for side,paths in row['evidence'].items():
                for path in paths:evidence_rows.append([row['subject']+' / '+row['risk_id'],side+' / '+path['tcode'],path.get('actual_assigned_role','')+'\n'+path['matched_catalogue_pattern']+' / '+path.get('matching_status','')+' / '+json.dumps(path.get('source_provenance',[]),ensure_ascii=False),path['single_role']+'\n'+localized_date(path.get('role_valid_from'))+' - '+localized_date(path.get('role_valid_to'))+'\n'+path.get('interval_status','')+' / '+path.get('user_group','')])
        review_rows=[['SAP user / risk','Decision / lifecycle','Reviewer / timestamp','Justification / controls / action']]+[[row['finding']['subject']+' / '+row['finding']['risk_id'],row['decision']+' / '+row['lifecycle'],annotation(row).get('reviewer','')+' / '+localized_stamp((row.get('event') or {}).get('timestamp')),'\n'.join(annotation(row).get(key,'') or '' for key in ('rationale','mitigating_controls','action_owner','action_status','completion_notes'))] for row in reviews]
        section('appendices',[f"Source capture: {localized_stamp(saved['captured_at'])} UTC. Methodology: {saved['analysis']['methodology']['policy']}.",[limitation][0]],[catalogue_rows,transaction_rows,evidence_rows,review_rows])
    data=dict(version=1,title=options.title,language=options.language,status=options.status,document_version=options.document_version,report_date=options.report_date.isoformat(),prepared_by=options.prepared_by,period=period,organization=saved['organization'],logo_id=saved['logo_id'],snapshot_checksum=details['checksum'],sections=sections,limitation=limitation)
    serialized=json.dumps(data,sort_keys=True,ensure_ascii=False).encode()
    if len(serialized)>8*1024*1024:raise HTTPException(413,'Report model exceeds 8 MiB. Exclude appendices and export detailed CSV evidence separately.')
    data['model_checksum']=sha256(serialized).hexdigest()
    return data


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
    document.add_paragraph('Snapshot SHA-256: '+data['snapshot_checksum']);document.add_paragraph('Report model SHA-256: '+data['model_checksum']);document.add_page_break()
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
    for text in (data['organization']['name'],data['organization']['platform']+' · '+data['organization']['system_id']+' / '+data['organization']['client'],data['period']['name'],localized_date(data['period']['start'])+' - '+localized_date(data['period']['end']),data['status']+' · '+data['document_version'],'Prepared by: '+(data['prepared_by'] or 'Not specified'),'Report date: '+localized_date(data['report_date']),data['limitation'],'Snapshot SHA-256: '+data['snapshot_checksum'],'Report model SHA-256: '+data['model_checksum']):flow.extend([paragraph(text),Spacer(1,10)])
    flow.append(PageBreak())
    for item in data['sections']:
        flow.append(paragraph(item['title'],styles['Heading1']))
        for text in item['paragraphs']:flow.extend([paragraph(text),Spacer(1,8)])
        for rows in item['tables']:
            table=LongTable([[paragraph(text,cell) for text in row] for row in rows],colWidths=[document.width/len(rows[0])]*len(rows[0]),repeatRows=1,splitInRow=1,hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e8edf3')),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5),('LINEBELOW',(0,0),(-1,0),.5,colors.HexColor('#758296')),('LINEBELOW',(0,1),(-1,-1),.2,colors.HexColor('#d4dae2'))]));flow.extend([table,Spacer(1,12)])
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
