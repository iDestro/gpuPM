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
  await page.getByLabel('任务别名').fill('模型A训练');
  await page.getByLabel('备注').fill('browser-verified-note');
  await page.getByLabel('保护任务（超时仍提醒，不自动终止）').click();
  await page.getByRole('button',{name:/保\s*存/}).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByText('browser-verified-note')).toBeVisible();
  await expect(page.getByRole('button',{name:'终止整个任务'})).toBeDisabled();
  await expect(page.getByText('原始名称',{exact:true})).toBeVisible();
  await expect(page.getByText('alice / training',{exact:true})).toBeVisible();
  await page.goto('/tasks');
  const alias = page.getByRole('link',{name:'模型A训练',exact:true});
  await alias.hover();
  await expect(page.getByRole('tooltip')).toHaveText('原始名称：alice / training');
  await alias.click();
  await page.getByRole('button',{name:'编辑策略'}).click();
  await page.getByLabel('备注').fill('unsaved-cancel-check');
  await page.getByRole('button',{name:/取\s*消/}).click();
  await expect(page.getByText('放弃尚未保存的修改？',{exact:true}).last()).toBeVisible();
  await page.getByRole('button',{name:'继续编辑'}).click();
  await expect(page.getByLabel('备注')).toHaveValue('unsaved-cancel-check');
  await page.getByRole('dialog').getByRole('button',{name:'Close',exact:true}).click();
  await expect(page.getByText('放弃尚未保存的修改？',{exact:true}).last()).toBeVisible();
  await page.getByRole('button',{name:'放弃修改'}).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByText('browser-verified-note')).toBeVisible();

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
test('human defaults, readonly other rows and task list termination preview',async({page})=>{
  await login(page);
  const taskRequests: string[]=[];
  page.on('request',request=>{ if(request.url().includes('/api/tasks?')) taskRequests.push(request.url()); });
  await page.goto('/tasks');
  const humanRow=page.getByRole('row').filter({has:page.locator('a[href="/tasks/demo-task-2"]')});
  await page.getByRole('combobox',{name:'状态筛选'}).focus();
  await page.getByRole('combobox',{name:'状态筛选'}).press('ArrowDown');
  await page.getByText('已结束',{exact:true}).click();
  await expect(humanRow).toHaveCount(0);
  await page.getByRole('combobox',{name:'状态筛选'}).focus();
  await page.getByRole('combobox',{name:'状态筛选'}).press('ArrowDown');
  await page.getByText('运行中',{exact:true}).click();
  await humanRow.getByRole('button',{name:'终止任务'}).click();
  await expect(page.getByText('终止范围预览',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'确认终止'})).toBeDisabled();
  expect(taskRequests.some(url=>new URL(url).searchParams.get('scope')==='human' && new URL(url).searchParams.get('status')==='running')).toBe(true);
  await page.getByRole('button',{name:/取\s*消/}).click();
  await page.route('**/api/tasks?**',async route=>{
    const response=await route.fetch();
    const data=await response.json();
    await route.fulfill({response,json:{...data,items:data.items.map((row:any)=>({...row,is_human:false}))}});
  });
  await page.goto('/tasks');
  await expect(humanRow.getByRole('button',{name:'终止任务'})).toBeDisabled();
  await expect(humanRow.getByRole('checkbox')).toBeDisabled();
  await page.route('**/api/system-users?**',async route=>{
    const response=await route.fetch();
    const rows=await response.json();
    await route.fulfill({response,json:rows.map((row:any)=>({...row,is_human:false}))});
  });
  await page.goto('/accounts');
  const bob=page.getByRole('row').filter({has:page.getByRole('button',{name:'bob',exact:true})});
  await expect(bob.getByRole('button',{name:/编\s*辑/})).toBeDisabled();
  await expect(bob.getByRole('button',{name:/停\s*用/})).toBeDisabled();
  await page.getByRole('combobox',{name:'账号范围'}).focus();
  await page.getByRole('combobox',{name:'账号范围'}).press('ArrowDown');
  await page.getByText('其他账号（只读）',{exact:true}).click();
  await expect(bob).toHaveCount(0);
});
