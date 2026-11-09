/**
 * Live progress for scripts/run-tests.py. Playwright's own reporters write for a terminal; when the runner captures several processes they
 * either buffer or carry box-drawing glyphs that Windows PowerShell 5.1 shows as `ΓÇ║`. This reporter writes one JSON object per line
 * (UTF-8, appended synchronously) to SAP_LENS_PROGRESS_FILE, and the runner renders the counts, each finished test and each failure as it
 * happens. Without that variable it does nothing, so a plain `npx playwright test` is unaffected.
 */
import { appendFileSync } from 'node:fs'
import path from 'node:path'
import type { FullResult, Reporter, Suite, TestCase, TestResult } from '@playwright/test/reporter'

const target = process.env.SAP_LENS_PROGRESS_FILE
const write = (event: Record<string, unknown>) => { if (target) appendFileSync(target, JSON.stringify(event) + '\n', 'utf-8') }
// eslint-disable-next-line no-control-regex
const plain = (text: string) => text.replace(/\u001b\[[0-9;]*m/g, '')

function describe(test: TestCase) {
  const file = path.basename(test.location.file)
  const parts = test.titlePath().filter(Boolean)
  const at = parts.findIndex((part) => part.endsWith(file) || part.endsWith('.spec.ts'))
  return { file, title: parts.slice(at + 1).join(' > '), line: test.location.line }
}

/** The first meaningful lines of an error: the assertion and its expected/received values, without colour codes or the call log. */
function summary(result: TestResult): string {
  const message = plain(result.errors.map((error) => error.message || error.value || '').find(Boolean) || '')
  const lines = message.split('\n').map((line) => line.trimEnd()).filter((line) => line.trim() && !/^\s*Call log:/.test(line))
  return lines.slice(0, 4).join('\n').slice(0, 600)
}

export default class ProgressReporter implements Reporter {
  onBegin(_config: unknown, suite: Suite) { write({ type: 'begin', total: suite.allTests().length }) }

  onTestBegin(test: TestCase, result: TestResult) { write({ type: 'test-begin', ...describe(test), retry: result.retry }) }

  onTestEnd(test: TestCase, result: TestResult) {
    const final = result.status === 'passed' || result.status === 'skipped' || result.retry >= test.retries
    write({ type: 'test-end', ...describe(test), status: result.status, outcome: final ? test.outcome() : 'retrying', retry: result.retry,
            duration: result.duration, error: result.status === 'passed' || result.status === 'skipped' ? '' : summary(result) })
  }

  onError(error: { message?: string; value?: string }) { write({ type: 'error', error: plain(error.message || error.value || '').split('\n').slice(0, 4).join('\n') }) }

  onEnd(result: FullResult) { write({ type: 'end', status: result.status }) }

  printsToStdio() { return false }
}
