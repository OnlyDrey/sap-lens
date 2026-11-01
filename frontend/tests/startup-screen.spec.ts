import { test, expect, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const WIDTHS = [375, 800, 1280, 1600]
const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')

/** Horizontal centres of the logo, the application name and the status line, and the viewport centre. */
async function centres(page: Page, status: string) {
  return page.evaluate((selector) => {
    const middle = (box: DOMRect) => box.left + box.width / 2
    const text = (element: Element) => { const range = document.createRange(); range.selectNodeContents(element); return range.getBoundingClientRect() }
    const image = document.querySelector('img')!, name = document.querySelector('h1')!, line = document.querySelector(selector)!
    return { viewport: document.documentElement.clientWidth / 2, logo: middle(image.getBoundingClientRect()), name: middle(text(name)), status: middle(text(line)), overflow: document.documentElement.scrollWidth > innerWidth, display: getComputedStyle(image).display }
  }, status)
}
const expectCentred = (found: Awaited<ReturnType<typeof centres>>) => {
  for (const key of ['logo', 'name', 'status'] as const) expect(Math.abs(found[key] - found.viewport), key).toBeLessThan(1)
  expect(found.overflow).toBe(false)
  expect(found.display).toBe('block') // no inline baseline gap or text-align dependency
}

test.describe('web startup document (before the application script runs)', () => {
  test.use({ javaScriptEnabled: false })
  for (const width of WIDTHS) test(`logo, name and status share one centre at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await page.goto('/')
    await expect(page.locator('[role="status"]')).toHaveText('Connecting to local service…')
    expectCentred(await centres(page, '[role="status"]'))
  })
})

test.describe('desktop startup document', () => {
  let directory = '', file = ''
  test.beforeAll(() => {
    directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-startup-'))
    file = path.join(directory, 'startup.html')
    try {
      execFileSync('python3', ['-c', `import sys\nfrom pathlib import Path\nsys.path.insert(0, 'backend')\nfrom startup_screen import startup_html\nPath(sys.argv[1]).write_text(startup_html(Path('assets/sap-lens.png'), 'synthetic-capability'))`, file], { cwd: repository })
    } catch { file = '' }
  })
  test.afterAll(() => rmSync(directory, { recursive: true, force: true }))
  for (const width of WIDTHS) test(`logo, name and status share one centre at ${width}px, also while the status changes`, async ({ page }) => {
    test.skip(!file, 'The desktop startup document needs the Python backend with Pillow')
    await page.setViewportSize({ width, height: 800 })
    await page.goto(pathToFileURL(file).href)
    const before = await page.locator('.card').boundingBox()
    expectCentred(await centres(page, '#status'))
    await page.evaluate(() => (window as unknown as { sapLensStartup: { setState: (label: string) => void } }).sapLensStartup.setState('Connecting to local service…'))
    await expect(page.locator('#status')).toHaveText('Connecting to local service…')
    expectCentred(await centres(page, '#status'))
    expect(Math.abs((await page.locator('.card').boundingBox())!.y - before!.y)).toBeLessThan(2) // a new status line does not move the logo
    await page.evaluate(() => (window as unknown as { sapLensStartup: { setState: (label: string, error: string) => void } }).sapLensStartup.setState('Failed', 'The local service could not start.'))
    expectCentred(await centres(page, '#status'))
  })
})
