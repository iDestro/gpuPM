import { test, expect } from '@playwright/test';
async function login(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByLabel('管理员账号').fill('admin');
  await page.getByLabel('密码',{exact:true}).fill('Strong-admin-pass-42');
  await page.getByRole('button',{name:/登\s*录/}).click();
  await expect(page.getByText('服务器总览',{exact:true}).last()).toBeVisible();
}
test('administrator can navigate every live API screen without errors',async({page})=>{
  const errors: string[]=[];
  page.on('pageerror',e=>errors.push(e.message));
  await login(page);
  const pages=[['/tasks','GPU 任务'],['/groups','业务优先级组'],['/users','用户业务策略'],['/accounts','Linux 本地账号'],
    ['/system-groups','Linux 系统组'],['/storage','存储与容量'],['/shares','团队共享目录'],['/login-events','SSH 登录记录'],['/settings','策略配置'],['/audit','操作审计']];
  for(const [path,title] of pages){
    await page.goto(path);
    await expect(page.getByText(title,{exact:true}).last()).toBeVisible();
    await expect(page.getByText('HTTP 422')).toHaveCount(0);
  }
  expect(errors).toEqual([]);
});
test('task policy edits persist and protected task cannot be terminated',async({page})=>{
  await login(page);
  await page.goto('/tasks/demo-task-1');
  await page.getByRole('button',{name:'编辑策略'}).click();
  await page.getByLabel('备注').fill('browser-verified-note');
  await page.getByLabel('保护任务（超时仍提醒，不自动终止）').click();
  await page.getByRole('button',{name:/保\s*存/}).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByText('browser-verified-note')).toBeVisible();
  await expect(page.getByRole('button',{name:'终止整个任务'})).toBeDisabled();
});
test('soft deletion retains account and restoration leaves prior disable restriction',async({page})=>{
  await login(page);
  await page.goto('/accounts');
  const alice=page.getByRole('row').filter({has:page.getByRole('button',{name:'alice',exact:true})});
  await alice.getByRole('button',{name:/停\s*用/ }).click();
  await page.getByLabel('操作原因').fill('browser-disable');
  await page.getByRole('button',{name:'确认执行'}).click();
  await expect(page.getByText('请求已提交，以下为服务器返回结果')).toBeVisible();
  await page.getByRole('button',{name:/关\s*闭/ }).click();
  await alice.getByRole('button',{name:'软删除'}).click();
  await page.getByLabel('操作原因').fill('browser-soft-delete');
  await page.getByRole('button',{name:'确认执行'}).click();
  await expect(page.getByText('请求已提交，以下为服务器返回结果')).toBeVisible();
  await page.getByRole('button',{name:/关\s*闭/ }).click();
  await page.getByRole('combobox',{name:'账号状态'}).focus();
  await page.getByRole('combobox',{name:'账号状态'}).press('ArrowDown');
  await page.getByText('已软删除',{exact:true}).click();
  await alice.getByRole('button',{name:/恢\s*复/ }).click();
  await page.getByLabel('操作原因').fill('browser-restore');
  await page.getByRole('button',{name:'确认执行'}).click();
  await expect(page.getByText('请求已提交，以下为服务器返回结果')).toBeVisible();
  const result=await page.request.get('/api/system-users?state=all');
  const account=(await result.json()).find((a:any)=>a.username==='alice');
  expect(account.status).toBe('disabled');
  expect(account.deleted_at).toBeNull();
  expect(account.home).toBe('/home/alice');
  expect(account.data_dir).toBe('/data/alice');
});
