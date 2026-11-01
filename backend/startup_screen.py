"""Self-contained trusted startup document; no network or file URL access."""
import base64
import json
from io import BytesIO
from pathlib import Path


def startup_html(logo: Path, token: str):
    from PIL import Image
    with Image.open(logo) as source:
        source.thumbnail((280, 200), Image.Resampling.LANCZOS)
        output = BytesIO()
        source.save(output, format='PNG')
    image = base64.b64encode(output.getvalue()).decode()
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<style>:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:var(--bg,#0d0d1a);color:var(--text,#f1f5f9);font-family:Segoe UI,Arial,sans-serif;min-height:100vh;display:grid;place-items:center;padding:28px}.card{display:flex;flex-direction:column;align-items:center;text-align:center;width:min(440px,100%);padding:40px;border-radius:20px;background:var(--surface,#111827)}img{display:block;flex:none;height:100px;width:100px;object-fit:contain}h1{font-size:30px;margin:20px 0 13px}p{margin:0}#status,#error,#recovery{margin-top:15px}#recovery{font-size:13px}button{margin-top:13px}.muted{color:var(--text,#bcc6dd);font-size:13px;line-height:1.6}.spinner{width:28px;height:28px;border:3px solid #343b59;border-top-color:var(--accent,#8da4ee);border-radius:50%;margin:30px 0 5px;animation:spin 1s linear infinite}.error{display:none;color:var(--error,#ffb4a9)}#status{font-size:15px}button{background:var(--accent,#7c85d4);color:var(--on-accent,#000000);padding:10px 16px;border:0;border-radius:8px;font:inherit;cursor:pointer}button:focus-visible{outline:3px solid var(--text,#ffffff);outline-offset:4px}@keyframes spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.spinner{animation:none}}</style></head><body><main class="card"><img alt="SAP Lens" src="data:image/png;base64,''' + image + '''"><h1>SAP Lens</h1><p class="muted">Your local SAP role workspace</p><div id="spinner" class="spinner" aria-hidden="true"></div><p id="status" role="status" aria-live="polite">Starting backend…</p><p id="error" class="error" role="alert"></p><p class="muted" id="recovery">The application manages its local service automatically.</p><button onclick='window.pywebview.api.close_application(''' + json.dumps(token) + ''')'>Close SAP Lens</button></main><script>window.sapLensStartup={setState:function(label,error){document.getElementById('status').textContent=label;if(error){document.getElementById('spinner').style.display='none';document.getElementById('error').style.display='block';document.getElementById('error').textContent=error;document.getElementById('recovery').textContent='Close and reopen SAP Lens to retry. Your saved settings are retained.'}}};</script></body></html>'''


def state_script(label, error=None):
    # Only authored status strings; never interpolate exceptions/paths/capabilities.
    return 'window.sapLensStartup && window.sapLensStartup.setState(' + json.dumps(label) + ',' + json.dumps(error) + ')'


def palette_script(settings):
    from theme_colors import contrast
    palettes = {}
    for mode in ['light', 'dark']:
        palette = getattr(settings.theme_colors, mode).model_dump()
        palette['on_accent'] = '#ffffff' if contrast('#ffffff', palette['accent']) >= contrast('#000000', palette['accent']) else '#000000'
        palette['error'] = next((color for color in ['#b42318', '#ffb4a9'] if contrast(color, palette['surface']) >= 4.5), palette['text'])
        palettes[mode] = palette
    data = json.dumps({'mode':settings.theme, 'palettes':palettes})
    return """(()=>{const data=""" + data + """;const mode=data.mode==='system'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):data.mode;const colors=data.palettes[mode];const map={background:'--bg',surface:'--surface',text:'--text',accent:'--accent',on_accent:'--on-accent',error:'--error'};Object.entries(map).forEach(([key,token])=>document.documentElement.style.setProperty(token,colors[key]));document.documentElement.style.colorScheme=mode;})()"""
