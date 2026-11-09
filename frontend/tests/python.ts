import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * The Python interpreter for every subprocess a browser test or the test server starts. Never a bare `python` from PATH when a
 * better answer exists: on Windows that is often a different version (3.13+ or the Microsoft Store stub), which breaks the backend.
 * Order: SAP_LENS_TEST_PYTHON (set by scripts/run-tests.py to its own Python 3.12 interpreter), the project .venv, then PYTHON or `python`.
 */
export function testPython(): string {
  if (process.env.SAP_LENS_TEST_PYTHON) return process.env.SAP_LENS_TEST_PYTHON
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
  const venv = process.platform === 'win32' ? path.join(root, '.venv', 'Scripts', 'python.exe') : path.join(root, '.venv', 'bin', 'python')
  if (existsSync(venv)) return venv
  return process.env.PYTHON || 'python'
}

export const PYTHON = testPython()
