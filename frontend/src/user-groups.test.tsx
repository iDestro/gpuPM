import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { queryClient } from './api';
import { setLocale } from './i18n';
import { UserGroups, UserTaskPolicy, groupLabel } from './user-groups';
const effective = {priority:50,max_runtime_seconds:1800,protected:false,deadline_action:'notify',orphan_reminder:true,orphan_wait_seconds:300};
const groups = [{id:1,name:'默认组',is_default:true,policy_overrides:{},effective_policy:effective},{id:2,name:'自定义组',is_custom:true,policy_overrides:{},effective_policy:{}},{id:3,name:'research',policy_overrides:{priority:80},effective_policy:{...effective,priority:80}}];
const account = {id:'1001',uid:1001,username:'alice',is_human:true,managed:true,status:'active'};
const user = {...account,group_id:1,personal_policy:{priority:90},effective_policy:effective,policy_sources:{},policy_editable:true};
function setup(node:React.ReactNode) {
 const fetch = vi.fn(async(url:string, options?:RequestInit)=>new Response(JSON.stringify(url==='/api/groups'?groups:url==='/api/users'?[user]:url==='/api/settings'?{default_task_priority:50,default_max_runtime_seconds:1800,default_task_protected:false,default_deadline_action:'notify',default_orphan_reminder:true,default_orphan_wait_seconds:300}:{status:'succeeded'})));
 vi.stubGlobal('fetch',fetch);
 render(<QueryClientProvider client={queryClient}><MemoryRouter>{node}</MemoryRouter></QueryClientProvider>);
 return fetch;
}
afterEach(()=>{cleanup();vi.unstubAllGlobals();queryClient.clear();setLocale('zh-CN');});
test('built-ins are protected and deleting ordinary group migrates to default through query',async()=>{
 const fetch=setup(<UserGroups/>);
 const row=(await screen.findByText('research',{exact:true})).closest('tr')!;
 for(const name of ['默认组','自定义组']) expect(within(screen.getByText(name,{exact:true}).closest('tr')!).queryByRole('button',{name:/删\s*除/})).toBeNull();
 await userEvent.click(within(row).getByRole('button',{name:/删\s*除/}));
 await userEvent.click(screen.getByRole('button',{name:/保\s*存/}));
 await waitFor(()=>expect(fetch.mock.calls.some(([url,o])=>url==='/api/groups/3?move_to=1'&&o?.method==='DELETE')).toBe(true));
},15000);
test('explicit unlimited and inherited runtime generate different sparse overrides',async()=>{
 const fetch=setup(<UserGroups/>);
 const row=(await screen.findByText('research',{exact:true})).closest('tr')!;
 await userEvent.click(within(row).getByRole('button',{name:/编\s*辑/}));
 await userEvent.click(screen.getByRole('switch',{name:'最大运行时间：继承策略配置'}));
 await userEvent.click(screen.getByRole('button',{name:'不限时'}));
 await userEvent.click(screen.getByRole('button',{name:/保\s*存/}));
 await waitFor(()=>expect(fetch.mock.calls.some(([,o])=>o?.method==='PATCH')).toBe(true));
 const patch=fetch.mock.calls.find(([,o])=>o?.method==='PATCH');
 expect(JSON.parse(String(patch?.[1]?.body)).policy_overrides).toEqual({priority:80,max_runtime_seconds:null});
},15000);
test('switching into custom uses retained personal configuration and switching out does not erase it',async()=>{
 const fetch=setup(<UserTaskPolicy account={account}/>);
 await userEvent.click(await screen.findByRole('button',{name:'配置任务策略'}));
 await userEvent.click(screen.getByRole('combobox',{name:'任务策略组'}));
 await userEvent.click(screen.getByText('自定义组',{exact:true}));
 expect(screen.getByRole('spinbutton',{name:'优先级 (0–100)'})).toHaveValue('90');
 await userEvent.click(screen.getByRole('combobox',{name:'任务策略组'}));
 await userEvent.click(screen.getByText('research',{exact:true}));
 expect(screen.queryByRole('spinbutton',{name:'优先级 (0–100)'})).toBeNull();
 await userEvent.click(screen.getByRole('button',{name:/保\s*存/}));
 await waitFor(()=>expect(fetch.mock.calls.some(([,o])=>o?.method==='PATCH')).toBe(true));
 expect(JSON.parse(String(fetch.mock.calls.find(([,o])=>o?.method==='PATCH')?.[1]?.body))).toEqual({group_id:3});
},15000);
test('English labels and cancel close the unchanged dialog',async()=>{
 setLocale('en-US');setup(<UserGroups/>);
 await userEvent.click(await screen.findByRole('button',{name:'Create task policy group'}));
 expect(screen.getByRole('switch',{name:'Maximum runtime: inherit global policy'})).toBeChecked();
 await userEvent.click(screen.getByRole('button',{name:'Cancel'}));
 await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());
},15000);

test('returning an explicit runtime override to inheritance removes the field',async()=>{
 const fetch=setup(<UserGroups/>);
 const row=(await screen.findByText('research',{exact:true})).closest('tr')!;
 await userEvent.click(within(row).getByRole('button',{name:/编\s*辑/}));
 const inherit=screen.getByRole('switch',{name:'最大运行时间：继承策略配置'});
 await userEvent.click(inherit);
 await userEvent.click(screen.getByRole('button',{name:'不限时'}));
 await userEvent.click(inherit);
 await userEvent.click(screen.getByRole('button',{name:/保\s*存/}));
 await waitFor(()=>expect(fetch.mock.calls.some(([,o])=>o?.method==='PATCH')).toBe(true));
 expect(JSON.parse(String(fetch.mock.calls.find(([,o])=>o?.method==='PATCH')?.[1]?.body)).policy_overrides).toEqual({priority:80});
},15000);

test('invalid overridden duration blocks save and leaves dialog editable',async()=>{
 const fetch=setup(<UserGroups/>);
 await userEvent.click(await screen.findByRole('button',{name:'新建任务策略组'}));
 await userEvent.type(screen.getByLabelText('组名'),'invalid-duration');
 await userEvent.click(screen.getByRole('switch',{name:'最大运行时间：继承策略配置'}));
 await userEvent.clear(screen.getByRole('spinbutton',{name:'分钟'}));
 await userEvent.type(screen.getByRole('spinbutton',{name:'分钟'}),'0');
 await userEvent.click(screen.getByRole('button',{name:/保\s*存/}));
 expect(await screen.findByText('请填写有效的优先级或时间；不限时请点击“不限时”。')).toBeVisible();
 expect(screen.getByRole('dialog')).toBeVisible();
 expect(fetch.mock.calls.some(([,o])=>o?.method==='POST')).toBe(false);
},15000);


test('legacy ordinary groups with reserved names remain distinguishable',()=>{
 expect(groupLabel({name:'自定义组'})).toBe('自定义组（普通组）');
 expect(groupLabel({name:'自定义组（内置）',is_custom:true})).toBe('自定义组');
});

test('group detail assigns searchable members with expected original group and explicit target',async()=>{
 const fetch=setup(<UserGroups/>);
 await userEvent.click(await screen.findByRole('button',{name:'research'}));
 await userEvent.click(screen.getByRole('button',{name:'添加成员'}));
 const dialogs=screen.getAllByRole('dialog');
 const dialog=within(dialogs[dialogs.length-1]);
 await userEvent.type(dialog.getByRole('combobox',{name:'选择成员'}),'alice');
 await userEvent.click(await screen.findByText('alice · 默认组 → research',{exact:true}));
 await userEvent.click(dialog.getByRole('button',{name:/保\s*存/}));
 await waitFor(()=>expect(fetch.mock.calls.some(([url,o])=>url==='/api/groups/3/members'&&o?.method==='POST')).toBe(true));
 expect(JSON.parse(String(fetch.mock.calls.find(([url])=>url==='/api/groups/3/members')?.[1]?.body))).toEqual({members:[{uid:1001,group_id:1}]});
},15000);

test('failed batch assignment keeps selected members and cancel sends no second request',async()=>{
 const fetch=setup(<UserGroups/>);
 fetch.mockImplementation(async(url:string,options?:RequestInit)=>new Response(JSON.stringify(url==='/api/groups'?groups:url==='/api/users'?[user]:url==='/api/settings'?{}:{detail:{code:'membership_changed',message:'成员所属组已变化，请刷新后重新选择。'}}),{status:url.endsWith('/members')?409:200}));
 await userEvent.click(await screen.findByRole('button',{name:'research'}));
 await userEvent.click(screen.getByRole('button',{name:'添加成员'}));
 const dialogs=screen.getAllByRole('dialog'); const dialog=within(dialogs[dialogs.length-1]);
 await userEvent.type(dialog.getByRole('combobox',{name:'选择成员'}),'alice');
 await userEvent.click(await screen.findByText('alice · 默认组 → research',{exact:true}));
 await userEvent.click(dialog.getByRole('button',{name:/保\s*存/}));
 await waitFor(()=>expect(fetch.mock.calls.filter(([url])=>url.endsWith('/members'))).toHaveLength(1));
 expect(await dialog.findByText('成员所属组已变化，请刷新后重新选择。')).toBeVisible();
 expect(dialog.getByText('alice · 默认组 → research',{exact:true})).toBeVisible();
 await userEvent.click(dialog.getByRole('button',{name:/取\s*消/}));
 expect(fetch.mock.calls.filter(([url])=>url.endsWith('/members'))).toHaveLength(1);
},15000);
