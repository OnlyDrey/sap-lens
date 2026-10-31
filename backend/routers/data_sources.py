"""Authenticated local-only refresh evidence, bounded pages and safe CSV export."""
import csv
import io
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from csv_lifecycle import history, read_private
from config import get_settings
from csv_exports import spreadsheet_cell

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
def details(identity: str, source: str = Query('', pattern=r'^(roles|users|employees|sod)?$'),
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
def export(identity: str, source: str = Query('', pattern=r'^(roles|users|employees|sod)?$'),
           kind: str = Query('', pattern=r'^(added|removed|modified)?$'), search: str = Query('', max_length=256)):
    data = report(identity)
    def stream():
        yield '\ufeff'
        buffer = io.StringIO()
        writer = csv.writer(buffer, quoting=csv.QUOTE_ALL)
        def line(values):
            buffer.seek(0); buffer.truncate(0)
            writer.writerow([spreadsheet_cell(v) for v in values])
            return buffer.getvalue()
        yield line(['Timestamp', 'Source', 'Change', 'Identifier', 'Field', 'Before', 'After'])
        for row in changes(data, source, kind, search):
            fields = row['fields'] or [dict(field=key, before=row.get('before', {}).get(key, ''), after=row.get('after', {}).get(key, ''))
                                        for key in sorted(set(row.get('before', {})) | set(row.get('after', {})))]
            for field in fields:
                yield line([data['timestamp'], row['source_name'], row['type'], row['identifier'], field['field'], field['before'], field['after']])
    return StreamingResponse(stream(), media_type='text/csv; charset=utf-8',
                             headers={'Content-Disposition': 'attachment; filename="SAP-Lens-refresh-changes.csv"'})


# Selection is an explicit import intent. Preview/digest APIs remain compatible,
# but normal selection does not require a second confirmation request.
from typing import Literal
from fastapi import Request
from pydantic import Field
from config_models import StrictModel, AppConfig, ImportProfile, UserImportProfile, SodImportProfile, FIELDS, USER_FIELDS


class SourceSelection(StrictModel):
    path: str = Field(min_length=1,max_length=4096)
    revision: int = Field(ge=0)
    mode: Literal['static','dynamic']
    profile: dict | None = Field(default=None,max_length=8)


@router.post('/{source}/select')
async def select_source(source:Literal['roles','users','employees','sod'], body:SourceSelection, request:Request):
    if not body.path.strip():
        raise HTTPException(400,'Choose a CSV file. Use Clear source data to remove a dataset intentionally.')
    current=get_settings()
    if current.revision!=body.revision:
        raise HTTPException(409,'Settings changed. Reload this source before selecting it again.')
    candidate=current.model_copy(deep=True)
    setattr(candidate,{'roles':'data_csv_path','users':'user_csv_path','employees':'employee_csv_path','sod':'sod_csv_path'}[source],body.path.strip())
    setattr(candidate.source_modes,source,body.mode)
    if body.profile is not None:
        if source=='employees':raise HTTPException(400,'This source uses its fixed documented schema.')
        if source=='sod':
            try:
                profile=SodImportProfile.model_validate({**body.profile,'id':'default','name':'Standard SoD matrix'})
            except ValueError:
                raise HTTPException(400,'The SoD import format is invalid. Review its delimiter, encoding and column mapping.') from None
            if profile.model_dump(exclude={'version'})!=candidate.sod_import.model_dump(exclude={'version'}):
                profile.version=max(profile.version,candidate.sod_import.version+1)
            candidate.sod_import=profile
    if body.profile is not None and source in {'roles','users'}:
        try:
            profile=(ImportProfile if source=='roles' else UserImportProfile).model_validate(body.profile)
            field,active=('import_profiles','active_import') if source=='roles' else ('user_import_profiles','active_user_import')
            profiles=getattr(candidate,field)
            previous=next((item for item in profiles if item.id==profile.id),None)
            if previous and profile.model_dump(exclude={'version'})!=previous.model_dump(exclude={'version'}):
                profile.version=max(profile.version,previous.version+1)
            setattr(candidate,field,[profile if item.id==profile.id else item for item in profiles] if previous else [*profiles,profile])
            setattr(candidate,active,profile.id)
        except ValueError:
            raise HTTPException(400,'The source import profile is invalid. Review its column mapping and format.') from None
    try:
        from configuration_routes import validate_configuration
        candidate=AppConfig.model_validate(candidate.model_dump())
        validate_configuration(candidate,current)
    except (ValueError,OSError):
        raise HTTPException(400,'The source location, mode or import profile is invalid. Check source access and server path policy.') from None
    report=await request.app.state.loader.load(configuration=candidate,operation='import',force=(source,))
    result=next((item for item in report['sources'] if item['source']==source),None)
    if not result or result['status'] not in {'updated','unchanged'}:
        raise HTTPException(409,'The source was not activated. Previous validated data is retained.')
    return dict(settings=get_settings().model_dump(),refresh=report,source=source,records=result['records'])


@router.get('/{source}/preview')
def snapshot_preview(source:Literal['roles','users','employees','sod'],offset:int=Query(0,ge=0),limit:int=Query(20,ge=1,le=100)):
    import cache
    from employee_directory import HEADERS
    snapshot=cache.get_snapshot()
    if source=='roles':rows=snapshot.source_records;columns=FIELDS;loaded=bool(snapshot.import_report)
    elif source=='users':rows=snapshot.users.source_records;columns=USER_FIELDS;loaded=bool(snapshot.users.report)
    elif source=='sod':
        from sod_import import HEADERS
        rows=snapshot.sod.get('records',[]);columns=HEADERS;loaded=bool(snapshot.sod)
    else:
        directory=snapshot.directory if snapshot.directory_bound else None
        rows=directory.rows if directory else [];columns=HEADERS;loaded=directory is not None
    return dict(source=source,loaded=loaded,columns=columns,items=[{key:row.get(key,'') for key in columns} for row in rows[offset:offset+limit]],total=len(rows),offset=offset,limit=limit)


def sod_metadata():
    settings = get_settings()
    reference = settings.data_lifecycle.sources.get('sod')
    return dict(path=settings.sod_csv_path, mode=settings.source_modes.sod, feature_enabled=settings.features.sod,
                format=dict(delimiter=settings.sod_import.delimiter, encoding=settings.sod_import.encoding, mapping=settings.sod_import.mapping),
                imported_at=reference.imported_at if reference else None, checked_at=reference.checked_at if reference else None, snapshot=reference.snapshot if reference else None)


@router.get('/sod/inspection')
def sod_snapshot_inspection():
    """Read-only inspection of the active SoD snapshot: counts, column interpretation, validation checks, warnings and import metadata."""
    import cache
    from sod_import import inspection
    snapshot = cache.get_snapshot()
    if not snapshot.sod:
        return dict(loaded=False, metadata=sod_metadata())
    return dict(loaded=True, metadata=sod_metadata(), **inspection(snapshot.sod))


from routers.employees import ImportRequest as DirectoryInspection

@router.post('/employees/inspect')
def inspect_directory_snapshot(body:DirectoryInspection):
    import cache
    from employee_preview import preview_page
    snapshot=cache.get_snapshot();directory=snapshot.directory if snapshot.directory_bound else None
    settings=get_settings()
    if directory is None:raise HTTPException(409,'No loaded Employee Directory snapshot is available.')
    if body.digest and body.digest not in {directory.digest,settings.employee_snapshot_id}:
        raise HTTPException(409,'The directory snapshot changed. Close and reopen Preview data.')
    return preview_page(directory,directory,snapshot,settings,body)


class SodFileInspection(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    delimiter: Literal['auto', ',', ';', '\t', '|'] = 'auto'
    encoding: Literal['auto', 'utf-8-sig', 'utf-16', 'cp1252'] = 'auto'
    mapping: dict[str, str] = Field(default_factory=dict, max_length=12)


@router.post('/sod/inspect')
def inspect_sod_file(body: SodFileInspection):
    """Read-only inspection of a candidate SoD CSV (format, header mapping, parser errors, counts, checks, sample rows). Nothing is imported, saved or cached."""
    from analysis_errors import AnalysisValidationError
    from sod_import import inspect_file
    try:
        profile = SodImportProfile(id='default', name='Standard SoD matrix', delimiter=body.delimiter, encoding=body.encoding, mapping=body.mapping)
        return inspect_file(body.path.strip(), profile)
    except ValueError:
        raise HTTPException(400, 'The SoD import format is invalid. Review its delimiter, encoding and column mapping.') from None
    except AnalysisValidationError as exc:
        raise HTTPException(400, str(exc)) from None
    except OSError:
        raise HTTPException(400, 'The CSV could not be opened. Check the path and file permissions.') from None
