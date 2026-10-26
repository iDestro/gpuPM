import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { queryClient, setSession } from './api';
import { AccountDetail } from './pages';
const account: Record<string, any> = {id:'alice',username:'alice',uid:1001,gid:1001,home:'/home/alice',data_dir:'/data/alice',
  groups:['alice'],shell:'/bin/bash',status:'active',managed:true,is_human:true,protected:false,disabled:false,
  deleted_at:null,expires_on:null,require_password_change:false,revision:1,priority:73,group_id:2};
function setup(row=account) {
  setSession({username:'admin',csrf_token:'test-csrf'});
  const request = vi.fn().mockImplementation(async (url: string) => new Response(JSON.stringify(url === '/api/health' ? {mutations:true,mode:'demo'} : url.endsWith('/activity') ? {processes:[],sessions:[],scheduled:[],coverage:'test'} :
    url.endsWith('/change-preview') ? {token:'scope-token',expires_at:'2099-01-01T00:00:00Z'} :
    url.endsWith('/storage') ? {filesystems:[{id:'fs',path:'/data'}]} :
    url === '/api/users' || url === '/api/groups' ? [] : url === '/api/settings' ? {} :
    {...row,revision:5}
  )));
  vi.stubGlobal('fetch',request);
  render(<MemoryRouter><QueryClientProvider client={queryClient}><AccountDetail account={row} /></QueryClientProvider></MemoryRouter>);
  return request;
}
afterEach(()=>{cleanup();vi.unstubAllGlobals();queryClient.clear();});
test('soft deleted account cannot edit credentials or policy',async()=>{
  setup({...account,deleted_at:'2026-10-14T00:00:00Z',status:'deleted'});
  expect(screen.getByRole('button',{name:'重置密码'})).toBeDisabled();
  expect(screen.getByRole('button',{name:'密码策略'})).toBeDisabled();
});
test('detail edit uses fetched current revision rather than old table row',async()=>{
  const request=setup();
  await waitFor(()=>expect(request).toHaveBeenCalled());
  await userEvent.click(screen.getByRole('button',{name:'密码策略'}));
  await userEvent.click(screen.getByRole('button',{name:/保\s*存/}));
  await screen.findByText(/范围由服务器核验/);
  await userEvent.type(screen.getByLabelText('操作原因'),'策略调整');
  await userEvent.click(screen.getByRole('button',{name:'确认执行'}));
  await waitFor(()=>expect(request.mock.calls.some((c)=>String(c[0]).endsWith('/password-policy'))).toBe(true));
  const call=request.mock.calls.find((c)=>String(c[0]).endsWith('/password-policy'))!;
  expect(JSON.parse(call[1].body).revision).toBe(5);
});


test('GPU worker detail identifies device and per-process memory',async()=>{
  const { TaskDetail } = await import('./pages');
  const { Routes, Route } = await import('react-router-dom');
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async(url:string)=>new Response(JSON.stringify(url === '/api/health' ? {mutations:true,mode:'demo'} : url.endsWith('/gpus') ? {items:[{uuid:'gpu-one',index:0,name:'GPU test'}]} :
    {id:'task',name:'training',uid:1001,username:'alice',status:'running',is_human:true,protected:false,revision:1,
     members:[{identity:{boot_id:'boot',pid:4001,start_ticks:5},pid:4001,ppid:4000,command:'train',status:'S',gpu_memory:{'gpu-one':2*1024**3}},
              {identity:{boot_id:'boot',pid:4002,start_ticks:6},pid:4002,ppid:4001,command:'loader',status:'S',gpu_memory:{}}],context:[]}
  ))));
  render(<MemoryRouter initialEntries={['/tasks/task']}><QueryClientProvider client={queryClient}><Routes><Route path='/tasks/:id' element={<TaskDetail/>}/></Routes></QueryClientProvider></MemoryRouter>);
  expect((await screen.findAllByText(/GPU 0.*2.0 GiB/)).length).toBeGreaterThan(0);
  expect((await screen.findAllByText('非 GPU 辅助进程')).length).toBeGreaterThan(0);
});

test('demo mode remains visible across administration pages',async()=>{
  const { default: App }=await import('./App');
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async(url:string)=>new Response(JSON.stringify(url === '/api/health' ? {mutations:true,mode:'demo'} : url.endsWith('/health') ? {status:'ok',mode:'demo',agent:'ok',mutations:true} :
    url.endsWith('/auth/me') ? {username:'admin',csrf_token:'token'} : []
  ))));
  render(<MemoryRouter initialEntries={['/accounts']}><QueryClientProvider client={queryClient}><App/></QueryClientProvider></MemoryRouter>);
  expect(await screen.findByText('演示模式 · 不操作宿主机')).toBeVisible();
});

test('account awaiting root recovery cannot change credentials',async()=>{
  setup({...account,recovery_required:true,login_policy_status:'recheck_required'});
  await screen.findByText('账号变更尚未完成，请由服务器管理员核对目录和登录状态后恢复管理。');
  await userEvent.click(screen.getByText('原始账号信息'));
  await screen.findByText('5');
  expect(screen.getByRole('button',{name:'重置密码'})).toBeDisabled();
});

test('nonhuman account details remain readonly',async()=>{
  setup({...account,is_human:false});
  await userEvent.click(screen.getByText('原始账号信息'));
  await screen.findByText('5');
  for (const name of ['重置密码','密码策略']) expect(screen.getByRole('button',{name})).toBeDisabled();
});

test.each([false,true])('readonly task disables every mutation when human=%s',async(is_human)=>{
  const { TaskDetail } = await import('./pages');
  const { Routes, Route } = await import('react-router-dom');
  vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(url === '/api/health' ? {mutations:true,mode:'demo'} : url.endsWith('/gpus') ? {items:[]} :
    {id:'task',name:'readonly',is_human,protected:is_human,members:[{identity:{pid:1},pid:1,ppid:0,status:'S'}],context:[]}))));
  render(<MemoryRouter initialEntries={['/tasks/task']}><QueryClientProvider client={queryClient}><Routes><Route path='/tasks/:id' element={<TaskDetail/>}/></Routes></QueryClientProvider></MemoryRouter>);
  await screen.findByRole('heading',{name:'readonly'});
  expect((screen.getByRole('button',{name:'编辑策略'}) as HTMLButtonElement).disabled).toBe(!is_human);
  for(const name of ['终止整个任务','终止进程','拆分所选进程','排除所选归属']) expect(screen.getByRole('button',{name})).toBeDisabled();
  expect(screen.getAllByRole('checkbox').every(input=>(input as HTMLInputElement).disabled)).toBe(true);
});

test('task editing offers only runtime and clears a legacy absolute expiry on save',async()=>{
  const {TaskDetail}=await import('./pages');
  const {Routes,Route}=await import('react-router-dom');
  setSession({username:'admin',csrf_token:'csrf'});
  const task={orphan_reminder:true,orphan_wait_seconds:300,id:'task',name:'sample',priority:50,revision:2,is_human:true,protected:false,members:[],context:[],max_runtime_seconds:3600,expires_at:'2099-01-01T00:00:00Z',deadline_action:'notify',deadline_at:'2026-10-14T04:00:00Z'};
  const fetch=vi.fn(async(url:string,_options?:RequestInit)=>new Response(JSON.stringify(url === '/api/health' ? {mutations:true,mode:'demo'} : url.endsWith('/gpus')?{items:[]}:task)));
  vi.stubGlobal('fetch',fetch);
  render(<MemoryRouter initialEntries={['/tasks/task']}><QueryClientProvider client={queryClient}><Routes><Route path='/tasks/:id' element={<TaskDetail/>}/></Routes></QueryClientProvider></MemoryRouter>);
  await userEvent.click(await screen.findByRole('button',{name:'编辑策略'}));
  expect(screen.queryByLabelText('指定到期时间 · Asia/Shanghai')).not.toBeInTheDocument();
  expect(screen.getByText('预计结束时间')).toBeInTheDocument();
  await userEvent.click(within(screen.getByRole('group',{name:'最大运行时间'})).getByRole('button',{name:'4小时'}));
  await userEvent.click(screen.getByRole('button',{name:/保\s*存/}));
  await waitFor(()=>expect(fetch.mock.calls.some(([,options])=>(options as RequestInit)?.method==='PATCH')).toBe(true));
  const patch=fetch.mock.calls.find(([,options])=>(options as RequestInit)?.method==='PATCH');
  expect(JSON.parse(String((patch?.[1] as RequestInit)?.body))).toMatchObject({max_runtime_seconds:14400,expires_at:null,revision:2});
},10000);

test('account retains directory usage without quota controls or requests',async()=>{
  setup();
  await screen.findByText('登录安全');
  expect(screen.queryByRole('button',{name:'配置配额'})).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('tab',{name:'个人目录用量'}));
  expect(screen.getByText('采样时间')).toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes('/quotas'))).toBe(false);
});
test('login policy preview conflict returns to preserved draft with refreshed revision',async()=>{
 const request=setup();let changed=false;
 request.mockImplementation(async(url:string)=>{
   if(url==='/api/health') return Response.json({mutations:true});
   if(url.endsWith('/change-preview')){changed=true;return Response.json({detail:{code:'revision_conflict',message:'changed'}},{status:409});}
   if(url==='/api/system-users/alice')return Response.json({...account,revision:changed?6:5});
   if(url==='/api/users'||url==='/api/groups')return Response.json([]);
   return Response.json({});
 });
 await waitFor(()=>expect(screen.getByRole('button',{name:'密码策略'})).toBeEnabled());await userEvent.click(screen.getByRole('button',{name:'密码策略'}));await userEvent.click(screen.getByRole('switch'));await userEvent.click(screen.getByRole('button',{name:/保\s*存/}));
 await screen.findByText('账号或配置版本已改变，请刷新后重新预览。');await userEvent.click(screen.getByRole('button',{name:'返回编辑并核对'}));await screen.findByRole('dialog',{name:'密码策略'});expect(screen.getByRole('switch')).toBeChecked();await userEvent.click(screen.getByRole('button',{name:/保\s*存/}));
 await waitFor(()=>expect(request.mock.calls.filter(c=>String(c[0]).endsWith('/change-preview'))).toHaveLength(2));
 const calls=request.mock.calls.filter(c=>String(c[0]).endsWith('/change-preview'));expect(JSON.parse(calls[1][1].body)).toMatchObject({revision:6,changes:{require_password_change:true}});
},20000);
