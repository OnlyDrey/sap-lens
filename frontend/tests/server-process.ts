import { execFile, type ChildProcess } from 'node:child_process'
import { rm } from 'node:fs/promises'
import { promisify } from 'node:util'

const execute = promisify(execFile)
export function observeTestServer(child: ChildProcess) {
  let startupError: Error | undefined
  const closed = new Promise<void>(resolve => {
    child.once('error', error => { startupError = error })
    child.once('close', () => resolve())
  })
  return { child, closed, startupError: () => startupError }
}
export type OwnedTestServer = ReturnType<typeof observeTestServer>

async function bounded(promise: Promise<void>, milliseconds: number): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    await Promise.race([promise, new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error('Owned test server did not close within its shutdown deadline.')), milliseconds)
    })])
  } finally { clearTimeout(timer) }
}

export async function stopTestServer(owned: OwnedTestServer, options: {
  platform?: NodeJS.Platform
  terminateTree?: (pid: number) => Promise<void>
  deadline?: number
} = {}) {
  const { child, closed } = owned
  const platform = options.platform ?? process.platform
  const deadline = options.deadline ?? 10000
  if (child.pid && child.exitCode === null && child.signalCode === null) {
    if (platform === 'win32') {
      // Kill the tree while the spawned PID is still alive: a venv launcher may own a Python descendant.
      const terminate = options.terminateTree ?? (async (pid: number) => {
        await execute('taskkill', ['/PID', String(pid), '/T', '/F'], { timeout: deadline, windowsHide: true })
      })
      await terminate(child.pid)
    } else {
      // beforeAll starts the server in its own process group; never signal by executable name.
      try { process.kill(-child.pid, 'SIGTERM') } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ESRCH') throw error
      }
    }
  }
  try { await bounded(closed, deadline) } catch (error) {
    if (platform === 'win32' || !child.pid) throw error
    try { process.kill(-child.pid, 'SIGKILL') } catch (failure) {
      if ((failure as NodeJS.ErrnoException).code !== 'ESRCH') throw failure
    }
    await bounded(closed, 5000)
  }
}

export async function removeTestServerDirectory(root: string, platform: NodeJS.Platform = process.platform) {
  // After process-tree termination and close, Windows scanners/handle release can briefly deny deletion.
  // Node retries only its documented transient filesystem errors; exhaustion still fails teardown.
  await rm(root, { recursive: true, force: true, maxRetries: platform === 'win32' ? 5 : 0, retryDelay: 100 })
}
