import {test,expect} from '@playwright/test'
import {headers,seedGovernance,cleanup} from './sod-fixture'
import { layoutMatrix } from './matrix'
let directory=''
test.beforeEach(async({request})=>{directory=await seedGovernance(request)})
test.afterEach(async({request})=>{await cleanup(request,directory)})
for (const { theme, width } of layoutMatrix([375,800,1280,1600]))test(`application footer ${theme} ${width}`,{ tag: '@visual' }, async({page,request})=>{
 await request.post('/api/configuration/theme',{headers,data:{theme}})
 await page.setViewportSize({width,height:1000});await page.goto('/#session=browser-test-session')
 const footer=page.locator('footer:visible');await expect(footer.getByLabel('Application version')).toContainText('SAP Lens v')
 const link=footer.getByRole('link',{name:'GitHub repository',exact:true});await expect(link).toHaveAttribute('href','https://github.com/OnlyDrey/sap-lens');await expect(link).toHaveAttribute('rel','noopener noreferrer')
 await footer.scrollIntoViewIfNeeded();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
 await page.getByRole('button',{name:'Open settings',exact:true}).click();await expect(footer).toHaveCount(1);await footer.scrollIntoViewIfNeeded();await expect(link).toBeVisible()
})
