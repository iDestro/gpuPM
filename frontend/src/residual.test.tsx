import {afterEach,expect,test,vi} from 'vitest';
import {cleanup,render,screen,within,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import {queryClient} from './api';
import {EditDialog,TerminationDialog,Operation,statusLabel} from './components';
import {Tasks} from './pages';
import {setLocale} from './i18n';
afterEach(()=>{cleanup();queryClient.clear();vi.unstubAllGlobals();setLocale('zh-CN');});
test.each([null,0,86401])('required residual waiting duration rejects %s',async(initial)=>{
  const save=vi.fn();
  render(<EditDialog title="编辑任务" fields={[{name:'orphan_wait_seconds',label:'残留等待时间',type:'duration',required:true,min:1,max:86400}]} initial={{orphan_wait_seconds:initial}} onSave={save} onClose={()=>{}}/>);
  expect(screen.queryByRole('button',{name:'不限时'})).not.toBeInTheDocument();
  const group=screen.getByRole('group',{name:'残留等待时间'});
  expect(within(group).getByRole('spinbutton',{name:'小时'})).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button',{name:/保\s*存/}));
  await screen.findByText('残留等待时间需为1秒至24小时');
  expect(save).not.toHaveBeenCalled();
});
test('residual preview sends explicit intent and shows exact identity, runtime and exclusions without executing',async()=>{
  const request=vi.fn(async(_url:string,_options?:RequestInit)=>new Response(JSON.stringify({token:'residual-scope',expires_at:'2099-01-01T00:00:00Z',targets:[{pid:99999,command:'python postprocess.py',identity:{pid:99999,start_ticks:7},create_time:new Date(Date.now()-600000).toISOString()}],excluded:[{identity:{pid:1},reason:'protected'}]})));
  vi.stubGlobal('fetch',request);
  render(<QueryClientProvider client={queryClient}><TerminationDialog task={{id:'residual'}} residualOnly onClose={()=>{}}/></QueryClientProvider>);
  await screen.findByText('python postprocess.py');
  expect(JSON.parse(String(request.mock.calls[0][1]?.body))).toEqual({residual_only:true});
  expect(screen.getAllByRole('columnheader',{name:'运行时间'}).some(header=>header.textContent==='运行时间')).toBe(true);
  expect(screen.getByText(/0时 10分/)).toBeInTheDocument();
  expect(screen.getByText('排除的进程')).toBeInTheDocument();
  expect(screen.getByRole('button',{name:'确认终止'})).toBeDisabled();
  expect(request).toHaveBeenCalledTimes(1);
});
test('active list keeps all live states visible and limits residual action to fresh applied human unprotected waiting tasks',async()=>{
  const base={is_human:true,protected:false,policy_status:'applied',orphan_reminder:true,orphan_wait_seconds:300,orphan_remaining_seconds:0};
  const items=[{...base,id:'eligible',name:'eligible',status:'awaiting_cleanup'},...['finalizing','cleaning'].map(status=>({...base,id:status,name:status,status})),{...base,id:'protected',name:'protected',status:'awaiting_cleanup',protected:true},{...base,id:'other',name:'other',status:'awaiting_cleanup',is_human:false},{...base,id:'stale',name:'stale',status:'awaiting_cleanup',stale:true},{...base,id:'unapplied',name:'unapplied',status:'awaiting_cleanup',policy_status:'pending'}];
  const request=vi.fn(async(url:string)=>new Response(JSON.stringify(url.startsWith('/api/tasks?')?{items,total:items.length,stale:false}:[])));
  vi.stubGlobal('fetch',request);
  render(<QueryClientProvider client={queryClient}><MemoryRouter><Tasks/></MemoryRouter></QueryClientProvider>);
  await screen.findByRole('link',{name:'eligible'});
  expect(request.mock.calls[0][0]).toContain('status=active');
  expect(screen.getByRole('link',{name:'finalizing'})).toBeVisible();
  expect(screen.getByRole('link',{name:'cleaning'})).toBeVisible();
  expect(screen.getAllByRole('button',{name:'终止残留进程'})).toHaveLength(1);
  expect(screen.getAllByText('残留提醒')).not.toHaveLength(0);
  setLocale('en-US');
  await waitFor(()=>expect(statusLabel('finalizing')).toBe('Finalizing'));
  expect(statusLabel('awaiting_cleanup')).toBe('Awaiting cleanup');
  expect(statusLabel('cleaning')).toBe('Cleaning');
});

test('queued termination progress polls until the operation completes',async()=>{
  let calls=0;
  vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({status:++calls===1?'queued':'succeeded',source:'demo',results:[]}))));
  render(<QueryClientProvider client={queryClient}><Operation id="queued-job"/></QueryClientProvider>);
  await screen.findByText('排队中');
  await screen.findByText('成功',{}, {timeout:2500});
  expect(calls).toBe(2);
});
test.each([1,86400])('required residual waiting duration submits valid boundary %s',async(seconds)=>{
  const save=vi.fn().mockResolvedValue({});
  render(<EditDialog title="编辑任务" fields={[{name:'orphan_wait_seconds',label:'残留等待时间',type:'duration',required:true,min:1,max:86400}]} initial={{orphan_wait_seconds:seconds}} onSave={save} onClose={()=>{}}/>);
  await userEvent.click(screen.getByRole('button',{name:/保\s*存/}));
  await waitFor(()=>expect(save).toHaveBeenCalledWith({orphan_wait_seconds:seconds}));
});
