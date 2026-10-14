import {expect, type Page} from '@playwright/test';
import {existsSync,readFileSync,writeFileSync,mkdirSync} from 'node:fs';
const sessionFile='test-results/admin-session.json';
export async function login(page:Page) {
  if(existsSync(sessionFile)) await page.context().addCookies(JSON.parse(readFileSync(sessionFile,'utf8')));
  if(!(await page.request.get('/api/auth/me')).ok()) {
    await page.goto('/');
    await page.getByLabel('管理员账号').fill('admin');
    await page.getByLabel('密码',{exact:true}).fill('Strong-admin-pass-42');
    await page.getByRole('button',{name:/登\s*录/}).click();
    await expect(page.getByRole('heading',{name:'服务器总览',exact:true})).toBeVisible();
    mkdirSync('test-results',{recursive:true});
    writeFileSync(sessionFile,JSON.stringify(await page.context().cookies()),{mode:0o600});
  } else await page.goto('/');
  await expect(page.getByRole('heading',{name:'服务器总览',exact:true})).toBeVisible();
}
