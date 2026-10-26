import {afterEach,expect,test,vi} from 'vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {MemoryRouter,Routes,Route} from 'react-router-dom';
import {QueryClientProvider} from '@tanstack/react-query';
import {queryClient} from './api';
import {Tasks,TaskDetail} from './pages';
import {setLocale} from './i18n';
function setup(){
 const request=vi.fn(async(url:string)=>new Response(JSON.stringify(url==='/api/health'?{mutations:true,mode:'demo'}:url==='/api/gpus'?{items:[{uuid:'gpu-uuid',index:0,name:'Test GPU'}]}:url.startsWith('/api/tasks?')?{items:[],total:0}:url.startsWith('/api/users')?[{uid:1001,username:'alice'}]:[])));
 vi.stubGlobal('fetch',request);
 render(<MemoryRouter><QueryClientProvider client={queryClient}><Tasks/></QueryClientProvider></MemoryRouter>);
 return request;
}
afterEach(()=>{cleanup();queryClient.clear();vi.unstubAllGlobals();setLocale('zh-CN');});
test('scope changes clear the visible user filter; reset synchronizes GPU and request parameters',async()=>{
 const request=setup();
 await userEvent.click(screen.getByRole('combobox',{name:'用户筛选'}));
 await userEvent.click(await screen.findByText('alice',{exact:true}));
 await userEvent.click(screen.getByRole('combobox',{name:'任务范围'}));
 await userEvent.click(screen.getByText('其他账号（只读）',{exact:true}));
 await waitFor(()=>expect(document.querySelector('.filters')).not.toHaveTextContent('alice'));
 await userEvent.click(screen.getByRole('combobox',{name:'GPU 筛选'}));
 await userEvent.click(await screen.findByText('GPU 0 · Test GPU',{exact:true}));
 await waitFor(()=>expect(request.mock.calls.some(([url])=>url.includes('gpu=gpu-uuid'))).toBe(true));
 await userEvent.click(screen.getByRole('button',{name:'重置筛选'}));
 await waitFor(()=>expect(document.querySelector('.filters')).not.toHaveTextContent('GPU 0 · Test GPU'));
 expect(screen.getByRole('combobox',{name:'任务范围'}).closest('.ant-select')).toHaveTextContent('人员账号');
 expect(screen.getByRole('combobox',{name:'状态筛选'}).closest('.ant-select')).toHaveTextContent('全部进行中任务');
},15000);
test('empty results explain default filters and provide a finished-task shortcut in both languages',async()=>{
 const request=setup();
 await screen.findByText('当前筛选条件下没有任务');
 expect(screen.getByText('默认仅显示人员账号的进行中任务；已结束任务请切换状态查看。')).toBeVisible();
 await userEvent.click(screen.getByRole('button',{name:'查看已结束任务'}));
 await waitFor(()=>expect(request.mock.calls.some(([url])=>url.includes('status=finished'))).toBe(true));
 setLocale('en-US');
 await screen.findByText('No tasks match the current filters');
 expect(screen.getByRole('button',{name:'Reset filters'})).toBeVisible();
});

test('failed task requests show retry guidance instead of presenting a successful empty list',async()=>{
 const request=setup();
 await screen.findByText('当前筛选条件下没有任务');
 request.mockImplementation(async(url:string)=>url.startsWith('/api/tasks?')?new Response(JSON.stringify({message:'collector unavailable'}),{status:503}):new Response(JSON.stringify([])));
 await queryClient.invalidateQueries({queryKey:['/tasks?page=1&page_size=20&sort=priority&scope=human&status=active']});
 await screen.findByText('任务加载失败，请重试',{}, {timeout:4000});
 expect(screen.getByRole('button',{name:/重\s*试/})).toBeVisible();
 expect(screen.queryByText('当前筛选条件下没有任务')).not.toBeInTheDocument();
},10000);

test('finished task details disable termination even for writable personnel accounts',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(url==='/api/health'?{mutations:true,mode:'demo'}:url==='/api/gpus'?{items:[]}: {id:'ended',name:'ended',is_human:true,status:'finished',members:[],context:[],anomalies:[],orphan_wait_seconds:300}))));
 render(<MemoryRouter initialEntries={["/tasks/ended"]}><QueryClientProvider client={queryClient}><Routes><Route path="/tasks/:id" element={<TaskDetail/>}/></Routes></QueryClientProvider></MemoryRouter>);
 await screen.findByRole('heading',{name:'ended'});
 expect(screen.getByRole('button',{name:'终止整个任务'})).toBeDisabled();
});
