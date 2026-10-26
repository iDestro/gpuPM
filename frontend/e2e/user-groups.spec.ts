import { test, expect } from '@playwright/test';
import { login } from './auth';

test('group overrides and personal assignment survive switches; legacy links and narrow dialog work', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await login(page);
  const session = await (await page.request.get('/api/auth/me')).json();
  const headers = {'X-CSRF-Token':session.csrf_token};
  const users = await (await page.request.get('/api/users')).json();
  const alice = users.find((u:any)=>u.username==='alice');
  const groups = await (await page.request.get('/api/groups')).json();
  const custom = groups.find((g:any)=>g.is_custom);
  let groupId:number|undefined;
  const name = `e2e-policy-${Date.now()}`;
  try {
    await page.goto('/groups');
    await expect(page.getByRole('heading',{name:'任务策略组',exact:true})).toBeVisible();
    await expect(page.getByRole('menuitem',{name:'用户业务策略',exact:true})).toHaveCount(0);
    await page.getByRole('button',{name:'新建任务策略组',exact:true}).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('组名').fill(name);
    await dialog.getByRole('switch',{name:'优先级 (0–100)：继承策略配置',exact:true}).click();
    await dialog.getByRole('spinbutton',{name:'优先级 (0–100)',exact:true}).fill('83');
    await dialog.getByRole('switch',{name:'最大运行时间：继承策略配置',exact:true}).click();
    await dialog.getByRole('button',{name:'不限时',exact:true}).click();
    await dialog.getByRole('button',{name:/保\s*存/}).click();
    await expect(dialog).toHaveCount(0);
    const created = (await (await page.request.get('/api/groups')).json()).find((g:any)=>g.name===name);
    groupId=created.id;
    expect(created.policy_overrides).toEqual({priority:83,max_runtime_seconds:null});
    const row=page.getByRole('row').filter({hasText:name});
    await expect(row).toContainText('不限时');
    const update = await page.request.patch(`/api/users/${alice.uid}`,{headers,data:{group_id:groupId,personal_policy:{priority:91}}});
    expect(update.ok(),await update.text()).toBeTruthy();
    await page.goto(`/accounts/${alice.account_ref}`);
    await page.getByRole('button',{name:'配置任务策略',exact:true}).click();
    await dialog.getByRole('combobox',{name:'任务策略组',exact:true}).focus();
    await dialog.getByRole('combobox',{name:'任务策略组',exact:true}).press('ArrowDown');
    await page.getByText('自定义组',{exact:true}).last().click();
    await expect(dialog.getByRole('spinbutton',{name:'优先级 (0–100)',exact:true})).toHaveValue('91');
    await dialog.getByRole('button',{name:/保\s*存/}).click();
    await expect(dialog).toHaveCount(0);
    let changed = (await (await page.request.get('/api/users')).json()).find((u:any)=>u.uid===alice.uid);
    expect(changed.group_id).toBe(custom.id); expect(changed.effective_policy.priority).toBe(91);
    await page.getByRole('button',{name:'配置任务策略',exact:true}).click();
    await dialog.getByRole('combobox',{name:'任务策略组',exact:true}).focus();
    await dialog.getByRole('combobox',{name:'任务策略组',exact:true}).press('ArrowDown');
    await page.getByText(name,{exact:true}).last().click();
    await dialog.getByRole('button',{name:/保\s*存/}).click();
    await expect(dialog).toHaveCount(0);
    changed=(await (await page.request.get('/api/users')).json()).find((u:any)=>u.uid===alice.uid);
    expect(changed.personal_policy.priority).toBe(91);expect(changed.effective_policy.priority).toBe(83);
    await page.goto('/advanced/system-groups');await expect(page).toHaveURL(/\/system-groups$/);
    await page.goto('/users');await expect(page).toHaveURL(/\/accounts$/);
    await page.goto('/groups');
    await page.locator('.language-select').click();await page.getByText('English',{exact:true}).last().click();
    await page.setViewportSize({width:375,height:812});
    await page.getByRole('button',{name:'Create task policy group',exact:true}).click();
    await expect(dialog.getByRole('switch',{name:'Maximum runtime: inherit global policy',exact:true})).toBeChecked();
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
    await page.screenshot({path:'test-results/user-groups-mobile.png',fullPage:true});
    await dialog.getByRole('button',{name:'Cancel',exact:true}).click();
    await expect(dialog).toHaveCount(0);
    expect(errors).toEqual([]);
  } finally {
    const restore=await page.request.patch(`/api/users/${alice.uid}`,{headers,data:{group_id:alice.group_id,personal_policy:alice.personal_policy}});
    expect(restore.ok(),await restore.text()).toBeTruthy();
    if(groupId) {const removed=await page.request.delete(`/api/groups/${groupId}?move_to=1`,{headers});expect(removed.ok(),await removed.text()).toBeTruthy();}
  }
});

test('group detail adds members and moves them back without changing native groups', async ({page})=>{
  await login(page);
  const session=await (await page.request.get('/api/auth/me')).json();
  const headers={'X-CSRF-Token':session.csrf_token};
  const users=await (await page.request.get('/api/users')).json();
  const alice=users.find((u:any)=>u.username==='alice');
  const nativeBefore=await (await page.request.get('/api/system-groups?scope=all')).json();
  const created=await page.request.post('/api/groups',{headers,data:{name:`member-flow-${Date.now()}`}});
  expect(created.ok()).toBeTruthy();
  const group=await created.json();
  try {
    await page.goto('/groups');
    await page.getByRole('button',{name:group.name,exact:true}).click();
    await page.getByRole('button',{name:'添加成员',exact:true}).click();
    const assignment=page.getByRole('dialog',{name:`调整成员至 ${group.name}`,exact:true});
    await expect.poll(()=>assignment.evaluate(el=>getComputedStyle(el).transform)).toBe('none');
    await assignment.locator('.ant-select-selector').click();
    await assignment.getByRole('combobox',{name:'选择成员'}).fill('alice');
    await page.locator('.ant-select-item-option-content').filter({hasText:'alice ·'}).click();
    await assignment.locator('.ant-modal-title').click();
    await page.screenshot({path:'test-results/group-members-dialog.png'});
    await assignment.getByRole('button',{name:/保\s*存/}).click();
    await expect(assignment).toHaveCount(0);
    const detail=page.getByRole('dialog',{name:group.name,exact:true});
    await expect(detail.getByRole('link',{name:'alice',exact:true})).toBeVisible();
    await detail.getByRole('button',{name:'移回默认组'}).click();
    const move=page.getByRole('dialog',{name:'调整成员至 默认组',exact:true});
    await move.getByRole('button',{name:/保\s*存/}).click();
    await expect(move).toHaveCount(0);
    await expect(detail.getByRole('link',{name:'alice',exact:true})).toHaveCount(0);
    expect(await (await page.request.get('/api/system-groups?scope=all')).json()).toEqual(nativeBefore);
  } finally {
    await page.request.patch(`/api/users/${alice.uid}`,{headers,data:{group_id:alice.group_id}});
    await page.request.delete(`/api/groups/${group.id}?move_to=1`,{headers});
  }
});
