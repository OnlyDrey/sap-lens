"""Local CSV rendering. Values remain unchanged in the source snapshot."""
import csv
import io
import re
from fastapi.responses import StreamingResponse
from user_access import sap_date, interval_status

ASSIGNMENT_COLUMNS = ['USERNAME','FIRST_NAME','LAST_NAME','EMAIL','USER_GROUP','ROLE_NAME',
                      'ROLE_VALID_FROM','ROLE_VALID_TO','ASSIGNMENT_STATUS','PR_PO',
                      'RELEASE_GROUP','RELEASE_STRATEGY','MATCHED_FILTER']
ASSIGNMENT_HEADER = '\ufeff' + ';'.join('"'+name+'"' for name in ASSIGNMENT_COLUMNS) + '\r\n'


ROLE_LIST_COLUMNS = ['ROLE_NAME','ROLE_DESCRIPTION','RELEASE_AREA','RELEASE_GROUP','RELEASE_STRATEGY','PR_PO']
ROLE_LIST_HEADER = '\ufeff' + ';'.join('"'+name+'"' for name in ROLE_LIST_COLUMNS) + '\r\n'


def spreadsheet_cell(value):
    text='' if value is None else str(value)
    return "'"+text if re.match(r'^[\s\x00-\x1f\ufeff]*[=+@-]',text) or text.startswith(('\t','\r','\n')) else text


def role_list_response(snapshot, roles, day):
    """Distinct technical release roles; assignment-level exports stay a separate contract."""
    def stream():
        yield ROLE_LIST_HEADER
        buffer=io.StringIO();writer=csv.writer(buffer,delimiter=';',quoting=csv.QUOTE_ALL,lineterminator='\r\n')
        for role in roles:
            values=[role['role_name'],role['description'],role['release_area'],role['release_group'],role['release_strategy'],role['document_type']]
            buffer.seek(0);buffer.truncate(0);writer.writerow([spreadsheet_cell(value) for value in values]);yield buffer.getvalue()
    revision=snapshot.last_loaded.isoformat() if snapshot.last_loaded else 'empty'
    return StreamingResponse(stream(),media_type='text/csv; charset=utf-8',headers={
        'Content-Disposition':f'attachment; filename="sap-lens-release-role-list-review-{day.isoformat()}.csv"',
        'X-SAP-Lens-Data-Revision':revision,'X-SAP-Lens-As-Of':day.isoformat(),'X-SAP-Lens-Role-Count':str(len(roles)),'Cache-Control':'no-store'})


def assignment_response(snapshot, entries, identities, count, kind, day):
    """One captured validated generation/day; never re-read a later page mid-export."""
    def local_date(value):
        parsed=sap_date(value)
        return f'{parsed.day:02}.{parsed.month:02}.{parsed.year:04}' if parsed else ''
    def stream():
        yield ASSIGNMENT_HEADER
        buffer=io.StringIO();writer=csv.writer(buffer,delimiter=';',quoting=csv.QUOTE_ALL,lineterminator='\r\n')
        for assignment,matched in entries:
            identity=identities[assignment['user_key']];release=assignment.get('release') or {}
            values=[assignment['username'],identity['first_name'],identity['last_name'],identity['email'],assignment['user_group'],assignment['role_name'],
                    local_date(assignment['valid_from']),local_date(assignment['valid_to']),
                    interval_status(sap_date(assignment['valid_from']),sap_date(assignment['valid_to']),day).title(),
                    release.get('document_type'),release.get('release_group'),release.get('release_strategy'),'Yes' if matched else 'No']
            buffer.seek(0);buffer.truncate(0);writer.writerow([spreadsheet_cell(value) for value in values]);yield buffer.getvalue()
    revision=snapshot.last_loaded.isoformat() if snapshot.last_loaded else 'empty'
    return StreamingResponse(stream(),media_type='text/csv; charset=utf-8',headers={
        'Content-Disposition':f'attachment; filename="sap-lens-{kind}-review-{day.isoformat()}.csv"',
        'X-SAP-Lens-Data-Revision':revision,'X-SAP-Lens-As-Of':day.isoformat(),'X-SAP-Lens-Assignment-Count':str(count),'Cache-Control':'no-store'})
