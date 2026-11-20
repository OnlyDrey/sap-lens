"""Python v1 reference for the reporting decision (REPORTING_ARCHITECTURE.md): renders synthetic frozen report models with v1's own render_pdf and
render_docx, extracts them with independent parsers (poppler pdftotext/pdfinfo, python-docx), and records v1 branding.sanitize_image verdicts for crafted
images (PNG, JPEG with EXIF, WebP, animated GIF/WebP, corrupt, truncated, oversized, tiny, SVG). Writes everything to OUT_DIR.
Usage: python -I tools/reporting_reference.py BACKEND_DIR OUT_DIR"""
import io, json, os, subprocess, sys, tempfile
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, out = sys.argv[1:3]
sys.path.insert(0, backend)
from pathlib import Path
from PIL import Image
import branding, sod_reports
from fastapi import HTTPException

out = Path(out); (out / 'images').mkdir(parents=True, exist_ok=True)

def model(name, sections, logo=False, title='SoD Review Report – Q4 2026'):
    return dict(title=title, prepared_by='Åse Nørgaard', organization=dict(name='Example Æøå AS', platform='SAP S/4HANA', system_id='PRD', client='100'),
                period=dict(id='a' * 32, name='Q4 2026 review', start='2026-10-01', end='2026-12-31'), status='Reviewed', document_version='v1.2',
                status_statement=sod_reports.STATUS_STATEMENTS['Reviewed'], report_date='2026-11-16T09:30:00+00:00', limitation=sod_reports.LIMITATION,
                snapshot_checksum='0123456789abcdef' * 4, model_checksum='fedcba9876543210' * 4, sections=sections, logo_id='l' * 64 if logo else None, _name=name)

big = [['User', 'Activity', 'Risk', 'Decision']] + [[f'USER{i:04}', f'Create vendor {i}', f'R{i % 17:03}', 'Pending' if i % 3 else 'Accepted with controls'] for i in range(400)]
models = [
    model('standard', [dict(title=h, paragraphs=[f'{h} paragraph one.', 'Line one\nline two «quoted» – dash'], tables=[sod_reports.GLOSSARY] if i == 0 else []) for i, h in enumerate(sod_reports.HEADINGS[:4])], logo=True),
    model('large', [dict(title='Outstanding Risks and Actions', paragraphs=['All open items.'], tables=[big])]),
    model('empty', [dict(title='Executive Summary', paragraphs=[], tables=[])]),
    model('unicode', [dict(title='Ünïcödé ÆØÅ æøå ß €', paragraphs=['Søknad om tilgang: “ok” — 100 % © ®'], tables=[[['Navn', 'Merknad'], ['Bjørn', 'Kåre & Co <tag>']]])]),
    model('unsupported', [dict(title='Emoji', paragraphs=['Done ✅ 漢字'], tables=[])]),
]
logo_png = io.BytesIO(); Image.new('RGBA', (300, 120), (20, 90, 160, 255)).save(logo_png, 'PNG')
logo = branding.sanitize_image(logo_png.getvalue()); (out / 'logo.png').write_bytes(logo)
results = {}
for m in models:
    name = m.pop('_name')
    sod_reports.report_logo = lambda data: logo if data['logo_id'] else None
    entry = dict(model=m)
    for kind in ('pdf', 'docx'):
        try:
            payload = sod_reports.render(m, kind)
        except HTTPException as error:
            entry[kind] = dict(status=error.status_code, detail=error.detail); continue
        (out / f'{name}.v1.{kind}').write_bytes(payload)
        if kind == 'pdf':
            text = subprocess.run(['pdftotext', '-enc', 'UTF-8', '-', '-'], input=payload, capture_output=True, check=True).stdout.decode('utf-8')
            info = subprocess.run(['pdfinfo', '-'], input=payload, capture_output=True, check=True).stdout.decode('utf-8')
            fields = dict(line.split(':', 1) for line in info.splitlines() if ':' in line)
            entry['pdf'] = dict(status=200, words=text.split(), pages=int(fields['Pages']), title=fields.get('Title', '').strip(), author=fields.get('Author', '').strip())
        else:
            import docx
            document = docx.Document(io.BytesIO(payload))
            entry['docx'] = dict(status=200, paragraphs=[p.text for p in document.paragraphs if p.text], tables=[[[c.text for c in r.cells] for r in t.rows] for t in document.tables],
                                 header=[p.text for p in document.sections[0].header.paragraphs], title=document.core_properties.title, author=document.core_properties.author,
                                 images=len(document.inline_shapes), reproducible=sod_reports.render(m, kind) == payload)
    results[name] = entry

def save(name, image, fmt, **kw):
    buffer = io.BytesIO(); image.save(buffer, fmt, **kw); (out / 'images' / name).write_bytes(buffer.getvalue()); return buffer.getvalue()

cases = {}
rgb = Image.new('RGB', (1600, 900), (200, 30, 30))
save('photo.jpg', rgb, 'JPEG', exif=Image.Exif() if False else b'Exif\x00\x00II*\x00\x08\x00\x00\x00\x00\x00')
save('wide.png', Image.new('RGBA', (3000, 200), (0, 128, 0, 128)), 'PNG')
save('small.png', Image.new('RGBA', (40, 40), (0, 0, 255, 255)), 'PNG')
save('tiny.png', Image.new('RGBA', (8, 8), (0, 0, 255, 255)), 'PNG')
save('logo.webp', Image.new('RGBA', (500, 500), (10, 10, 10, 200)), 'WEBP')
save('animated.gif', Image.new('P', (50, 50)), 'GIF', save_all=True, append_images=[Image.new('P', (50, 50), 1)])
save('animated.webp', Image.new('RGB', (50, 50)), 'WEBP', save_all=True, append_images=[Image.new('RGB', (50, 50), (9, 9, 9))])
save('huge.png', Image.new('L', (5000, 10)), 'PNG')
save('meta.png', Image.new('RGBA', (100, 100)), 'PNG', pnginfo=__import__('PIL.PngImagePlugin', fromlist=['PngInfo']).PngInfo())
png = (out / 'images' / 'small.png').read_bytes()
(out / 'images' / 'truncated.png').write_bytes(png[:len(png) // 2])
(out / 'images' / 'corrupt.jpg').write_bytes(b'\xff\xd8\xff\xe0' + os.urandom(2000))
(out / 'images' / 'vector.svg').write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
(out / 'images' / 'big-file.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 2_000_100)
for path in sorted((out / 'images').iterdir()):
    for profile, kw in (('logo', {}), ('report', dict(formats=frozenset({'PNG', 'JPEG'}), max_bytes=1_000_000, min_side=32))):
        try:
            result = branding.sanitize_image(path.read_bytes(), **kw)
            with Image.open(io.BytesIO(result)) as image:
                cases[f'{path.name}|{profile}'] = dict(ok=True, size=list(image.size), mode=image.mode, format=image.format, info=sorted(image.info))
        except ValueError as error:
            cases[f'{path.name}|{profile}'] = dict(ok=False, error=str(error))
(out / 'reporting.python.json').write_text(json.dumps(dict(reports=results, images=cases), ensure_ascii=False, indent=0, sort_keys=True) + '\n', encoding='utf-8')
print({k: {kind: v.get(kind, {}).get('status') for kind in ('pdf', 'docx')} for k, v in results.items()}, len(cases), 'image cases')
