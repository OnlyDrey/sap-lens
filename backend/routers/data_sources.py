"""Authenticated local-only refresh evidence, bounded pages and safe CSV export."""
import csv
import io
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from csv_lifecycle import history, read_private
from config import get_settings

router = APIRouter(prefix='/api/data-sources', tags=['Data Sources'])


def report(identity):
    if identity not in get_settings().data_lifecycle.history:
        raise HTTPException(404, 'Refresh report is no longer retained.')
    try: return read_private('reports', identity)
    except (OSError, ValueError):
        raise HTTPException(409, 'The private refresh report is unavailable. Check local storage.') from None


@router.get('/history')
def reports():
    return dict(items=history(), retention=5, privacy='Private local records; excluded from diagnostic exports.')


def changes(data, source='', kind='', search=''):
    term = search.strip().casefold()
    for result in data['sources']:
        if result['status'] not in {'updated', 'unchanged'} or source and result['source'] != source: continue
        for change in result.get('changes', []):
            if kind and change['type'] != kind: continue
            if term and term not in (change['identifier'] + ' ' + ' '.join(str(v) for row in ('before', 'after') for v in change.get(row, {}).values())).casefold(): continue
            yield dict(source=result['source'], source_name=result['name'], **change)


@router.get('/reports/{identity}')
def details(identity: str, source: str = Query('', pattern=r'^(roles|users|employees)?$'),
            kind: str = Query('', pattern=r'^(added|removed|modified)?$'), search: str = Query('', max_length=256),
            offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    data = report(identity)
    page, total = [], 0
    for row in changes(data, source, kind, search):
        if offset <= total < offset + limit: page.append(row)
        total += 1
    return dict(id=identity, timestamp=data['timestamp'], status=data['status'],
                sources=[{key: value for key, value in result.items() if key != 'changes'} for result in data['sources']],
                items=page, total=total, offset=offset, limit=limit)


@router.get('/reports/{identity}/export')
def export(identity: str, source: str = Query('', pattern=r'^(roles|users|employees)?$'),
           kind: str = Query('', pattern=r'^(added|removed|modified)?$'), search: str = Query('', max_length=256)):
    data = report(identity)
    def safe(value):
        value = str(value)
        return "'" + value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else value
    def stream():
        yield '\ufeff'
        buffer = io.StringIO()
        writer = csv.writer(buffer, quoting=csv.QUOTE_ALL)
        def line(values):
            buffer.seek(0); buffer.truncate(0)
            writer.writerow([safe(v) for v in values])
            return buffer.getvalue()
        yield line(['Timestamp', 'Source', 'Change', 'Identifier', 'Field', 'Before', 'After'])
        for row in changes(data, source, kind, search):
            fields = row['fields'] or [dict(field=key, before=row.get('before', {}).get(key, ''), after=row.get('after', {}).get(key, ''))
                                        for key in sorted(set(row.get('before', {})) | set(row.get('after', {})))]
            for field in fields:
                yield line([data['timestamp'], row['source_name'], row['type'], row['identifier'], field['field'], field['before'], field['after']])
    return StreamingResponse(stream(), media_type='text/csv; charset=utf-8',
                             headers={'Content-Disposition': 'attachment; filename="SAP-Lens-refresh-changes.csv"'})
