import { execFileSync } from 'node:child_process'

// Python's redirected stdout defaults to a Windows code page on some PCs.
// Write bytes explicitly; Node and the synthetic HTTP response both consume UTF-8.
export function bootstrapDocument(theme?: string, encoding = 'cp1252'): string {
  const script = `import sys
sys.path.insert(0, '../backend')
from pathlib import Path
from startup_screen import startup_html, palette_script
from config_models import AppConfig
html = startup_html(Path('../assets/sap-lens.png'), 'synthetic-preview')
if ${theme ? 'True' : 'False'}:
    html = html.replace('</body>', '<script>' + palette_script(AppConfig(theme=${JSON.stringify(theme ?? 'dark')})) + '</script></body>')
sys.stdout.buffer.write(html.encode('utf-8'))`
  return execFileSync('python', ['-X', 'utf8', '-c', script], {
    encoding: 'utf8', maxBuffer: 8 * 1024 * 1024,
    // Deliberately reproduce Windows' non-UTF-8 stdout setting on every platform.
    env: { ...process.env, PYTHONIOENCODING: encoding },
  })
}
