import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { seedSources, sessionUrl, goTo } from './support'

test('the isolated .NET host serves its identity and rejects unauthenticated API requests', async ({ request, baseURL }) => {
  const identity = await (await request.get('/product-version.json')).json()
  expect(identity.mode).toBe('dotnet')
  expect(identity.version).toBe(JSON.parse(readFileSync(new URL('../../backend/product-version.json', import.meta.url), 'utf8')).version)
  expect((await request.get('/health/ready')).status()).toBe(200)
  expect((await fetch(`${baseURL}/api/configuration`)).status).toBe(401)
})

test('the .NET browser fixture imports synthetic data and serves Role Lookup', async ({ page, request }) => {
  const source = await seedSources(request, { roles: 'AGR_NAME,TEXT,CHILD_AGR,TCODE\nZC:SYNTHETIC,Synthetic role,ZS:SYNTHETIC,MIGO\n' })
  try {
    await page.goto(sessionUrl)
    await goTo(page, 'Role Lookup')
    await expect(page.getByText('ZC:SYNTHETIC', { exact: true }).first()).toBeVisible()
  } finally { await source.cleanup() }
})
