// Disposable .NET browser/dev host. No operator configuration or production data is inherited.
import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
const root = fileURLToPath(new URL('../', import.meta.url))
const dev = process.argv.includes('--dev')
const port = Number(process.env.AUTHLENS_BROWSER_TEST_PORT || (dev ? 18744 : 18745))
if (!Number.isInteger(port) || port < 1 || port > 65535) throw Error('Invalid test port')
const directory = mkdtempSync(path.join(tmpdir(), 'authlens-browser-'))
const token = 'synthetic-browser-capability-0000000000000000'
let child, stopping = false
const parent = process.ppid
async function stop(code = 0) {
  if (stopping) return
  stopping = true
  clearInterval(watch)
  try {
    if (child?.pid && child.exitCode === null) {
      const exited = new Promise(resolve => child.once('exit', resolve))
      child.kill('SIGTERM')
      if (!await Promise.race([exited.then(() => true), delay(8000).then(() => false)])) {
        if (process.platform === 'win32') {
          const killer = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'inherit' })
          await Promise.race([new Promise(resolve => killer.once('exit', resolve)), delay(5000)])
        } else child.kill('SIGKILL')
        await Promise.race([exited, delay(5000).then(() => { throw Error('Owned test process did not exit') })])
      }
    }
    rmSync(directory, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 })
  } catch (error) { console.error('Test host cleanup failed; owned workspace retained:', directory, error.message); code = 1 }
  process.exit(code)
}
const watch = setInterval(() => { try { process.kill(parent, 0) } catch { void stop(1) } }, 1000)
process.on('SIGTERM', () => void stop())
process.on('SIGINT', () => void stop())
async function run(args, env) {
  child = spawn(process.env.DOTNET || 'dotnet', args, { cwd: root, env, stdio: 'inherit', windowsHide: true })
  return new Promise((resolve, reject) => { child.once('error', reject); child.once('exit', (code, signal) => resolve(code ?? (signal ? 1 : 0))) })
}
try {
  const inherited = Object.fromEntries(Object.entries(process.env).filter(([name]) => !name.startsWith('AUTHLENS_') && name !== 'DATA_CSV_PATH'))
  const env = { ...inherited, AUTHLENS_BROWSER_DATA: directory, AUTHLENS_BROWSER_TOKEN: token,
    AUTHLENS_BROWSER_TEST_PORT: String(port), DOTNET_CLI_TELEMETRY_OPTOUT: '1', MSBUILDDISABLENODEREUSE: '1' }
  const project = 'backend/tests/AuthLens.BrowserHost/AuthLens.BrowserHost.csproj'
  let code = await run(['build', project, '-c', 'Release', '--nologo', '-v', 'quiet', '-nodeReuse:false', '-p:UseSharedCompilation=false'], env)
  if (!code && !stopping) code = await run(['backend/tests/AuthLens.BrowserHost/bin/Release/net10.0/AuthLens.BrowserHost.dll'], env)
  await stop(code)
} catch (error) { console.error('Disposable .NET host failed:', error.message); await stop(1) }
