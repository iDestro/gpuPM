import {afterEach,expect,test,vi} from 'vitest';
import {act,cleanup,render,screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClientProvider} from '@tanstack/react-query';
import {queryClient} from './api';
import {Settings} from './pages';
import {setLocale} from './i18n';
const settings={scan_interval_seconds:5,term_grace_seconds:10,default_max_runtime_seconds:3661,storage_scan_interval_seconds:900,warning_percent:80,critical_percent:95,default_deadline_action:'notify',mode:'host',home_base:'/home',data_base:'/data/实验人员',share_base:'/data/shared'};
afterEach(()=>{cleanup();vi.unstubAllGlobals();queryClient.clear();setLocale('zh-CN');});
function setup(){setLocale('zh-CN');vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(settings))));render(<QueryClientProvider client={queryClient}><Settings/></QueryClientProvider>);}
test('settings show precise units and Chinese terms with professional English while preserving raw paths',async()=>{
  setup();
  const term=await screen.findByText('GPU 扫描周期');
  expect(screen.getByText('5 秒')).toBeInTheDocument();
  expect(screen.getByText('1时 1分 1秒')).toBeInTheDocument();
  await userEvent.hover(term);
  expect(await screen.findByRole('tooltip')).toHaveTextContent('GPU polling interval');
  act(()=>setLocale('en-US'));
  expect(screen.getByText('GPU polling interval')).toBeInTheDocument();
  expect(screen.getByText('Host mode')).toBeInTheDocument();
  expect(screen.getByText('/data/实验人员')).toBeInTheDocument();
  expect(screen.queryByText('scan_interval_seconds')).not.toBeInTheDocument();
});
test('switching languages preserves an unsaved settings runtime and localizes discard confirmation',async()=>{
  setup();
  await userEvent.click(await screen.findByText('编辑策略',{selector:'span'}));
  await userEvent.click(screen.getByText('4小时',{selector:'span'}));
  act(()=>setLocale('en-US'));
  expect(screen.getByLabelText('Hours')).toHaveValue('4');
  await userEvent.click(screen.getByText('Cancel',{selector:'span'}));
  await screen.findByText('Continue editing',{selector:'span'});
  await userEvent.click(screen.getByText('Continue editing',{selector:'span'}));
  expect(screen.getByLabelText('Hours')).toHaveValue('4');
  expect(vi.mocked(fetch).mock.calls.every(([,options])=>options?.method!=='PATCH')).toBe(true);
},10000);
