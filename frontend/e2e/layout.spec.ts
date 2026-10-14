import { test, expect } from '@playwright/test';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';

const sessionFile = 'test-results/layout-session.json';
const reason = 'Restore verified QA account management records omitted during trial deployment / ' + 'very-long-diagnostic-value-'.repeat(35);
async function login(page: any) {
  if (existsSync(sessionFile)) {
    await page.context().addCookies(JSON.parse(readFileSync(sessionFile, 'utf8')));
    await page.goto('/');
    await expect(page.getByText('服务器总览', {exact:true}).last()).toBeVisible();
    return;
  }
  await page.goto('/');
  await page.getByLabel('管理员账号').fill('admin');
  await page.getByLabel('密码', {exact:true}).fill('Strong-admin-pass-42');
  await page.getByRole('button', {name:/登\s*录/}).click();
  await expect(page.getByText('服务器总览', {exact:true}).last()).toBeVisible();
  writeFileSync(sessionFile, JSON.stringify(await page.context().cookies()), {mode:0o600});
}
async function longAudit(page: any) {
  await page.route('**/api/audit-logs?**', route => route.fulfill({json:{
    items:Array.from({length:40}, (_, i) => ({id:'layout-'+i,time:'2026-10-14T06:05:44Z',actor:'root-trial-reconciliation-with-long-actor-name',action:'account.management_import',target:'100'+i,result:'succeeded',reason,before:{managed:false},after:{managed:true}})), total:40,
  }}));
  await page.goto('/audit');
}

test('desktop long audit keeps navigation visible and rows compact, with full details available', async ({page}) => {
  await page.setViewportSize({width:1440,height:900});
  await login(page);
  await longAudit(page);
  const content=page.locator('.content-scroll');
  await expect(content).toHaveCount(1);
  const rows=page.locator('tr.ant-table-row');
  await expect(rows.first()).toBeVisible();
  expect((await rows.first().boundingBox())!.height).toBeLessThan(90);
  const before=(await page.locator('.sidebar').boundingBox())!;
  await content.evaluate(node => {node.scrollTop=node.scrollHeight;});
  expect(await content.evaluate(node=>node.scrollTop)).toBeGreaterThan(0);
  const after=(await page.locator('.sidebar').boundingBox())!;
  expect(after.y).toBe(before.y);
  expect(after.height).toBe(900);
  await expect(page.getByRole('menuitem', {name:'服务器总览'})).toBeVisible();
  expect((await page.locator('.topbar').boundingBox())!.y).toBe(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(1440);
  await content.evaluate(node=>{node.scrollTop=0;});
  await page.locator('.ant-table-row-expand-icon').first().click();
  await expect(page.locator('.ant-table-expanded-row').first()).toContainText(reason);
  await page.locator('.ant-table-row-expand-icon').first().click();
  await page.screenshot({path:'test-results/dashboard-audit-desktop.png',fullPage:true});
});

test('mobile navigation remains accessible and wide tables scroll inside content', async ({page}) => {
  await page.setViewportSize({width:375,height:812});
  await login(page);
  await page.getByRole('button',{name:'打开导航'}).click();
  const drawer=page.getByRole('dialog');
  await expect(drawer).toBeVisible();
  await drawer.getByRole('menuitem',{name:'GPU 任务'}).click();
  await expect(drawer).not.toBeVisible();
  await expect(page.getByRole('heading',{name:'GPU 任务'})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  const table=page.locator('.ant-table-content');
  expect(await table.evaluate(node=>node.scrollWidth)).toBeGreaterThan(await table.evaluate(node=>node.clientWidth));
  await table.evaluate(node=>{node.scrollLeft=node.scrollWidth;});
  expect(await table.evaluate(node=>node.scrollLeft)).toBeGreaterThan(0);
  await table.evaluate(node=>{node.scrollLeft=0;});
  await page.screenshot({path:'test-results/dashboard-tasks-mobile.png',fullPage:true});
  for (const path of ['/groups','/users','/system-groups','/storage','/shares','/accounts']) {
    await page.goto(path);
    const tables=page.locator('.ant-table-content');
    await expect(tables.first()).toBeVisible();
    for (const viewport of await tables.all()) {
      expect(await viewport.evaluate(node=>getComputedStyle(node).overflowX)).toMatch(/auto|scroll/);
      await viewport.evaluate(node=>{node.scrollLeft=node.scrollWidth;});
      expect(await viewport.evaluate(node=>node.scrollLeft)).toBeGreaterThan(0);
      await viewport.evaluate(node=>{node.scrollLeft=0;});
    }
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  }
  const account=page.getByRole('button',{name:'alice',exact:true});
  await expect(account).toBeInViewport();
  expect(await page.locator('td.ant-table-cell-fix-right').first().evaluate(node=>getComputedStyle(node).position)).toBe('static');

});


test('short desktop keeps all navigation reachable independently of content scroll', async ({page}) => {
  await page.setViewportSize({width:1280,height:600});
  await login(page);
  await longAudit(page);
  const navigation=page.locator('.sidebar-menu');
  expect(await navigation.evaluate(node=>node.scrollHeight)).toBeGreaterThan(await navigation.evaluate(node=>node.clientHeight));
  await navigation.evaluate(node=>{node.scrollTop=node.scrollHeight;});
  await expect(page.getByRole('menuitem',{name:'策略配置'})).toBeInViewport();
  const before=await navigation.evaluate(node=>node.scrollTop);
  await page.locator('.content-scroll').evaluate(node=>{node.scrollTop=node.scrollHeight;});
  expect(await navigation.evaluate(node=>node.scrollTop)).toBe(before);
  await expect(page.getByRole('menuitem',{name:'策略配置'})).toBeInViewport();
  await page.screenshot({path:'test-results/dashboard-short-desktop.png',fullPage:true});
});
