import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { queryClient, ApiError } from './api';
import { PreviewDialog, ErrorAlert } from './components';
import { setLocale } from './i18n';
import { Accounts, AccountDetail } from './pages';
afterEach(()=>{cleanup(); setLocale('zh-CN'); queryClient.clear();vi.unstubAllGlobals();});
function mount(child:React.ReactNode){render(<MemoryRouter><QueryClientProvider client={queryClient}>{child}</QueryClientProvider></MemoryRouter>);}
test('account preview with empty process targets shows proposed changes and identity',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({kind:'account',token:'token',targets:[],host_scope:{username:'alice',shell:'/bin/sh'},changes:{shell:'/bin/bash'},paths:{home:'/home/alice'},impact:'Existing files retained'}))));
 mount(<PreviewDialog title="preview" previewPath="/system-users/alice/change-preview" executePath="/system-users/alice" onClose={()=>{}}/>);
 await waitFor(()=>expect(screen.getByText('/bin/bash')).toBeVisible());expect(screen.getByText('/bin/sh')).toBeVisible();expect(screen.getByText('alice')).toBeVisible();expect(screen.queryByText('PID')).not.toBeInTheDocument();
});
test.each([false,undefined])('native creation fails closed when mutations=%s',async(mutations)=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(url==='/api/health'?{mode:'host',mutations}:[]))));
 mount(<Accounts/>);await waitFor(()=>expect(queryClient.getQueryData(['/system-groups?scope=all'])).toEqual([]));await waitFor(()=>expect(screen.getByRole('button',{name:'创建账号'})).toBeDisabled());
});
test('known error code explains action and keeps raw diagnostics collapsed',async()=>{
 mount(<ErrorAlert error={new ApiError(409,'adoption_path_conflict','/data/alice ownership mismatch')}/>);
 expect(screen.getByText('目录检查未通过，请按预览中的检查项修复后重试。')).toBeVisible();
 await userEvent.click(screen.getByText('服务器诊断'));expect(screen.getByText('/data/alice ownership mismatch')).toBeVisible();
});
test('incomplete creation resumes with fresh credentials only in execution',async()=>{
 const account={id:'alice',username:'alice',uid:1001,gid:1001,is_human:true,managed:true,recovery_required:true,creation:{status:'incomplete',stage:'directories'},revision:4};
 const fetch=vi.fn(async(url:string)=>new Response(JSON.stringify(url==='/api/health'?{mutations:true}:url.endsWith('/change-preview')?{kind:'account',token:'resume-token',targets:[]}:url.startsWith('/api/system-users')?[account]:[])));
 vi.stubGlobal('fetch',fetch);mount(<Accounts/>);
 await userEvent.click(await screen.findByRole('button',{name:'继续创建'}));
 await userEvent.type(screen.getByLabelText('新密码'),'Fresh-password-123');await userEvent.click(screen.getByRole('button',{name:/保\s*存/}));
 await screen.findByText(/范围由服务器核验/);await userEvent.type(screen.getByLabelText('操作原因'),'恢复创建');await userEvent.click(screen.getByRole('button',{name:'确认执行'}));
 await waitFor(()=>expect(fetch.mock.calls.some(([url])=>url.endsWith('/resume'))).toBe(true));
 const calls=fetch.mock.calls as unknown as [string,RequestInit][];
 expect(JSON.parse(calls.find(([url])=>url.endsWith('/change-preview'))![1].body as string)).toEqual({action:'resume',revision:4,changes:{}});
 expect(JSON.parse(calls.find(([url])=>url.endsWith('/resume'))![1].body as string)).toMatchObject({password:'Fresh-password-123',reason:'恢复创建',revision:4,token:'resume-token'});
});

test('account detail exposes lifecycle policy login and activity without opening raw JSON',async()=>{
 const account={id:'alice',username:'alice',is_human:true,managed:true,revision:1,login_policy_status:'pending',last_success_login:{time:'2026-10-14T01:00:00Z',ip:'10.1.2.3'},lifecycle:{disabled:{active:true,at:null,reason:'离组审核'}}};
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(url==='/api/health'?{mutations:true}:url.endsWith('/activity')?{processes:[{pid:123,command:'python train.py'}],sessions:[],scheduled:[],coverage:{crontab:'unavailable'}}:url.endsWith('/storage')?{filesystems:[],users:[]}:url==='/api/users'||url==='/api/groups'?[]:url==='/api/settings'?{}:account))));
 mount(<AccountDetail account={account}/>);
 expect(await screen.findByText('离组审核')).toBeVisible();expect(screen.getByText('10.1.2.3')).toBeVisible();expect(await screen.findByText('python train.py')).toBeVisible();expect(screen.getByText('登录策略生效状态')).toBeVisible();
});
test('an open native editor loses submit capability when health becomes read-only',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(url==='/api/health'?{mutations:true}:[]))));mount(<Accounts/>);
 await waitFor(()=>expect(screen.getByRole('button',{name:'创建账号'})).toBeEnabled());await userEvent.click(screen.getByRole('button',{name:'创建账号'}));
 queryClient.setQueryData(['/health'],{mutations:false});
 await waitFor(()=>expect(screen.getByRole('button',{name:/保\s*存/})).toBeDisabled());
});
test('failed health refresh revokes cached write capability',async()=>{
 queryClient.setQueryData(['/health'],{mutations:true},{updatedAt:1});
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>url==='/api/health'?new Response('{}',{status:503}):new Response('[]')));
 mount(<Accounts/>);await screen.findByText('服务器连接不可用，已禁止系统写入。');expect(screen.getByRole('button',{name:'创建账号'})).toBeDisabled();
});
test('adoption failed checks prevent execution even with a reason',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(url==='/api/health'?{mutations:true}:{kind:'account',token:'token',adoption:{ready:false,checks:[{code:'home_path',path:'/home/alice',ok:false,actual:'root',expected:'alice'}],manual_steps:['Repair /home/alice ownership']}}))));
 mount(<PreviewDialog title="preview" previewPath="/system-users/alice/change-preview" executePath="/system-users/alice" onClose={()=>{}}/>);
 await screen.findByText('Repair /home/alice ownership');await userEvent.type(screen.getByLabelText('操作原因'),'adopt');expect(screen.getByRole('button',{name:'确认执行'})).toBeDisabled();
});

test('coded guidance is translated while original paths remain in diagnostics',async()=>{
 setLocale('en-US');mount(<ErrorAlert error={new ApiError(409,'creation_path_conflict','目录 /data/张三 不匹配')}/>);
 expect(screen.getByText('Directory checks failed. Resolve the preview checks before retrying.')).toBeVisible();
 await userEvent.click(screen.getByText('Server diagnostic'));expect(screen.getByText('目录 /data/张三 不匹配')).toBeVisible();
});
