import {test,expect} from '@playwright/test';
import {login} from './auth';
const fields=['name','priority','protected','max_runtime_seconds','deadline_action','cleanup_orphans','orphan_reminder','orphan_wait_seconds'];
test('new task defaults save in the web UI without overwriting existing task policies',async({page})=>{
  await login(page);
  const settings=await (await page.request.get('/api/settings')).json();
  const before=(await (await page.request.get('/api/tasks?scope=all')).json()).items;
  await page.goto('/settings');
  await expect(page.getByText('新任务默认策略',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'编辑策略',exact:true}).click();
  await page.getByRole('group',{name:'默认最大运行时间',exact:true}).getByRole('button',{name:'30分钟',exact:true}).click();
  await expect(page.getByLabel('默认任务保护')).toHaveAttribute('aria-checked','false');
  await page.getByLabel('默认任务保护').click();
  await page.getByLabel('默认任务优先级').fill('0');
  await page.getByLabel('默认残留提醒').click();
  await page.getByRole('button',{name:/保\s*存/}).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  const saved=await (await page.request.get('/api/settings')).json();
  expect(saved).toMatchObject({default_max_runtime_seconds:1800,default_task_protected:true,default_task_priority:0,default_orphan_reminder:false});
  const after=(await (await page.request.get('/api/tasks?scope=all')).json()).items;
  for(const task of before){
    const same=after.find(t=>t.id===task.id);
    expect(same).toBeTruthy();
    for(const field of fields)expect(same[field]).toEqual(task[field]);
  }
  await page.reload();
  await page.getByRole('button',{name:'编辑策略',exact:true}).click();
  await expect(page.getByLabel('默认任务保护')).toHaveAttribute('aria-checked','true');
  await expect(page.getByLabel('默认任务优先级')).toHaveValue('0');
  await page.getByLabel('默认任务保护').click();
  await page.getByLabel('默认任务优先级').fill(String(settings.default_task_priority));
  await page.getByLabel('默认残留提醒').click();
  await page.getByRole('button',{name:/保\s*存/}).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(await (await page.request.get('/api/settings')).json()).toEqual(settings);
});
