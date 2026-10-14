import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { queryClient, setSession } from './api';
import { AccountDetail } from './pages';
const account: Record<string, any> = {id:'alice',username:'alice',uid:1001,gid:1001,home:'/home/alice',data_dir:'/data/alice',
  groups:['alice'],shell:'/bin/bash',status:'active',managed:true,is_human:true,protected:false,disabled:false,
  deleted_at:null,expires_on:null,require_password_change:false,revision:1,priority:73,group_id:2};
function setup(row=account, quotaRows: Record<string, any>[] = [{filesystem_id:"fs",soft_bytes:128,hard_bytes:4096,soft_inodes:20,hard_inodes:40,grace_seconds:60}]) {
  setSession({username:'admin',csrf_token:'test-csrf'});
  const request = vi.fn().mockImplementation(async (url: string) => new Response(JSON.stringify(
    url.endsWith('/activity') ? {processes:[],sessions:[],scheduled:[],coverage:'test'} :
    url.endsWith('/quotas') ? quotaRows :
    url.endsWith('/change-preview') ? {token:'scope-token',expires_at:'2099-01-01T00:00:00Z'} :
    url.endsWith('/storage') ? {filesystems:[{id:'fs',path:'/data',quota_supported:true,quota_enabled:true}]} :
    {...row,revision:5}
  )));
  vi.stubGlobal('fetch',request);
  render(<MemoryRouter><QueryClientProvider client={queryClient}><AccountDetail account={row} onClose={()=>{}} /></QueryClientProvider></MemoryRouter>);
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
test('quota editor preserves existing limits when editing one field',async()=>{
  setup();
  await waitFor(()=>expect(screen.getByRole('button',{name:'配置配额'})).toBeEnabled());
  await userEvent.click(screen.getByRole('button',{name:'配置配额'}));
  expect(screen.getByLabelText('空间软限额 (bytes)')).toHaveValue('128');
  expect(screen.getByLabelText('inode 硬限额')).toHaveValue('40');
});

test("quota read error prevents destructive zero fallback",async()=>{
  setup(account,[{filesystem_id:"fs",status:"quota_unavailable",error:"readback failed"}]);
  await screen.findByText(/readback failed/);
  expect(screen.getByRole("button",{name:"配置配额"})).toBeDisabled();
});

test('GPU worker detail identifies device and per-process memory',async()=>{
  const { TaskDetail } = await import('./pages');
  const { Routes, Route } = await import('react-router-dom');
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async(url:string)=>new Response(JSON.stringify(
    url.endsWith('/gpus') ? {items:[{uuid:'gpu-one',index:0,name:'GPU test'}]} :
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
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async(url:string)=>new Response(JSON.stringify(
    url.endsWith('/health') ? {status:'ok',mode:'demo',agent:'ok'} :
    url.endsWith('/auth/me') ? {username:'admin',csrf_token:'token'} : []
  ))));
  render(<MemoryRouter initialEntries={['/accounts']}><QueryClientProvider client={queryClient}><App/></QueryClientProvider></MemoryRouter>);
  expect(await screen.findByText('演示模式 · 不操作宿主机')).toBeVisible();
});
test('quota grace editor states current overage only and future filesystem defaults',async()=>{
  setup();
  await waitFor(()=>expect(screen.getByRole('button',{name:'配置配额'})).toBeEnabled());
  await userEvent.click(screen.getByRole('button',{name:'配置配额'}));
  expect(screen.getByLabelText('当前超限宽限期（秒）')).toHaveValue('60');
  expect(screen.getByText(/未超限时，未来首次超限使用文件系统默认宽限期/)).toBeInTheDocument();
});

test('account awaiting root recovery cannot change credentials',async()=>{
  setup({...account,recovery_required:true,login_policy_status:'recheck_required'});
  await screen.findByText('账号变更尚未完成，请由服务器管理员核对目录和登录状态后恢复管理。');
  await screen.findByText('5');
  expect(screen.getByRole('button',{name:'重置密码'})).toBeDisabled();
});

test('nonhuman account details remain readonly',async()=>{
  setup({...account,is_human:false});
  await screen.findByText('5');
  for (const name of ['重置密码','密码策略','配置配额']) expect(screen.getByRole('button',{name})).toBeDisabled();
});

test.each([false,true])('readonly task disables every mutation when human=%s',async(is_human)=>{
  const { TaskDetail } = await import('./pages');
  const { Routes, Route } = await import('react-router-dom');
  vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(url.endsWith('/gpus') ? {items:[]} :
    {id:'task',name:'readonly',is_human,protected:is_human,members:[{identity:{pid:1},pid:1,ppid:0,status:'S'}],context:[]}))));
  render(<MemoryRouter initialEntries={['/tasks/task']}><QueryClientProvider client={queryClient}><Routes><Route path='/tasks/:id' element={<TaskDetail/>}/></Routes></QueryClientProvider></MemoryRouter>);
  await screen.findByText('readonly');
  expect((screen.getByRole('button',{name:'编辑策略'}) as HTMLButtonElement).disabled).toBe(!is_human);
  for(const name of ['终止整个任务','终止进程','拆分所选进程','排除所选归属']) expect(screen.getByRole('button',{name})).toBeDisabled();
  expect(screen.getAllByRole('checkbox').every(input=>(input as HTMLInputElement).disabled)).toBe(true);
});
