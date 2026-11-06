"""Generate the synthetic, schema-compatible XLSX reference template deterministically."""
from pathlib import Path
import sys
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from sod_reference import RISK,ACTIVITY


def generate(target):
    namespace='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    relationships='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    sheets=[('Risks',['Risk',*RISK],['R_EXAMPLE','Synthetic risk','Example area','Describe the business conflict.','Describe the potential impact.','Describe compensating controls.','Describe review guidance.','']),
            ('Activities',['Activity',*ACTIVITY],['ACT_EXAMPLE','Synthetic activity','Example area','Describe the business capability.','Describe review guidance.','']),
            ('Definitions',['Term','Definition'],['Example term','Replace or remove this synthetic example term.'])]
    workbook=Element('workbook',xmlns=namespace);listing=SubElement(workbook,'sheets')
    rels=Element('Relationships',xmlns='http://schemas.openxmlformats.org/package/2006/relationships')
    types=Element('Types',xmlns='http://schemas.openxmlformats.org/package/2006/content-types')
    SubElement(types,'Default',Extension='rels',ContentType='application/vnd.openxmlformats-package.relationships+xml')
    SubElement(types,'Default',Extension='xml',ContentType='application/xml')
    SubElement(types,'Override',PartName='/xl/workbook.xml',ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml')
    entries={}
    for index,(name,headers,example) in enumerate(sheets,1):
        SubElement(listing,'sheet',name=name,sheetId=str(index),attrib={f'{{{relationships}}}id':f'r{index}'})
        SubElement(rels,'Relationship',Id=f'r{index}',Type=relationships+'/worksheet',Target=f'worksheets/sheet{index}.xml')
        SubElement(types,'Override',PartName=f'/xl/worksheets/sheet{index}.xml',ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml')
        sheet=Element('worksheet',xmlns=namespace);data=SubElement(sheet,'sheetData')
        for number,values in enumerate((headers,example),1):
            row=SubElement(data,'row',r=str(number))
            for column,value in enumerate(values):
                cell=SubElement(row,'c',r=f'{chr(65+column)}{number}',t='inlineStr')
                SubElement(SubElement(cell,'is'),'t').text=value
        entries[f'xl/worksheets/sheet{index}.xml']=tostring(sheet,encoding='utf-8',xml_declaration=True)
    rootrels=Element('Relationships',xmlns='http://schemas.openxmlformats.org/package/2006/relationships')
    SubElement(rootrels,'Relationship',Id='r1',Type=relationships+'/officeDocument',Target='xl/workbook.xml')
    entries.update({'[Content_Types].xml':tostring(types),'_rels/.rels':tostring(rootrels),'xl/workbook.xml':tostring(workbook),'xl/_rels/workbook.xml.rels':tostring(rels)})
    with ZipFile(target,'w') as archive:
        for name,raw in sorted(entries.items()):
            info=ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=ZIP_DEFLATED
            archive.writestr(info,raw)


if __name__=='__main__': generate(ROOT/'backend/resources/sod-reference-template.xlsx')
