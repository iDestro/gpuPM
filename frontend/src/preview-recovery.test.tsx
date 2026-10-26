import {afterEach,expect,test,vi} from 'vitest';
import {cleanup,render,screen,waitFor,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import {queryClient} from './api';
import {Accounts,Shares,SystemGroups} from './pages';
const alice={id:'a',username:'alice',managed:true,is_human:true,status:'active'};
afterEach(()=>{cleanup();queryClient.clear();vi.unstubAllGlobals();});
function mount(page:React.ReactNode){render(<MemoryRouter><QueryClientProvider client={queryClient}>{page}</QueryClientProvider></MemoryRouter>);}
test('share conflict preserves notes and members but requires review against refreshed members',async()=>{
 let conflict=false;const calls=vi.fn(async(url:string,options?:RequestInit)=>{
  if(url==='/api/health')return Response.json({mutations:true});
  if(url.includes('/change-preview')){conflict=true;return Response.json({detail:{code:'revision_conflict',message:'changed'}},{status:409});}
  if(url==='/api/shares')return Response.json([{id:'s',name:'research',revision:conflict?2:1,members:conflict?[{username:'bob',permission:'read'}]:[{username:'alice',permission:'read'}],notes:'old'}]);
  if(url.startsWith('/api/system-users'))return Response.json([alice,{...alice,username:'bob'}]);
  return Response.json({});
 });vi.stubGlobal('fetch',calls);mount(<Shares/>);
 await userEvent.click(await screen.findByRole('button',{name:'编辑授权'}));await userEvent.clear(screen.getByLabelText('备注'));await userEvent.type(screen.getByLabelText('备注'),'keep draft');await userEvent.click(screen.getByText('读写',{exact:true}));await userEvent.click(screen.getByRole('button',{name:/保\s*存/}));
 await screen.findByText('账号或配置版本已改变，请刷新后重新预览。');await userEvent.click(screen.getByRole('button',{name:'返回编辑并核对'}));
 const dialog=await screen.findByRole('dialog',{name:'修改共享授权'});expect(within(dialog).getByLabelText('备注')).toHaveValue('keep draft');expect(within(dialog).getByRole('radio',{name:'读写'})).toBeChecked();expect(within(dialog).getByText(/bob \(只读\)/)).toBeInTheDocument();
 expect(calls.mock.calls.filter(([url])=>url.includes('/change-preview'))).toHaveLength(1);expect(calls.mock.calls.some(([,o])=>o?.method==='PATCH')).toBe(false);
 await userEvent.click(within(dialog).getByRole('button',{name:/保\s*存/}));await waitFor(()=>expect(calls.mock.calls.filter(([url])=>url.includes('/change-preview'))).toHaveLength(2));
 const previews=calls.mock.calls.filter(([url])=>url.includes('/change-preview'));expect(JSON.parse(String(previews[1][1]?.body))).toMatchObject({revision:2,changes:{notes:'keep draft',members:[{username:'alice',permission:'write'}]}});
},20000);
test('native member addition conflict retains proposed members and shows concurrent current membership',async()=>{
 let conflict=false;const calls=vi.fn(async(url:string,options?:RequestInit)=>{
  if(url==='/api/health')return Response.json({mutations:true});
  if(url.includes('/change-preview')){conflict=true;return Response.json({detail:{code:'revision_conflict',message:'changed'}},{status:409});}
  if(url.startsWith('/api/system-groups'))return Response.json([{id:'g',name:'project',revision:conflict?2:1,members:conflict?['existing','bob']:['existing'],primary_users:[],assignable:true}]);
  if(url.startsWith('/api/system-users'))return Response.json([alice,{...alice,username:'bob'}]);return Response.json({});
 });vi.stubGlobal('fetch',calls);mount(<SystemGroups/>);
 await userEvent.click(await screen.findByRole('button',{name:/^成\s*员$/}));await userEvent.click(screen.getByRole('button',{name:'添加成员'}));await userEvent.type(screen.getByRole('combobox',{name:'选择成员'}),'alice');await userEvent.click(await screen.findByText(/alice · UID/));await userEvent.click(screen.getByRole('button',{name:/保\s*存/}));
 await screen.findByText('账号或配置版本已改变，请刷新后重新预览。');await userEvent.click(screen.getByRole('button',{name:'返回编辑并核对'}));
 const dialog=await screen.findByRole('dialog',{name:'修改权限组'});expect(within(dialog).getByText(/existing, bob/)).toBeInTheDocument();expect(within(dialog).getByText('alice',{exact:true})).toBeInTheDocument();expect(screen.getAllByRole('dialog')).toHaveLength(1);
 expect(calls.mock.calls.filter(([url])=>url.includes('/change-preview'))).toHaveLength(1);await userEvent.click(within(dialog).getByRole('button',{name:/保\s*存/}));await waitFor(()=>expect(calls.mock.calls.filter(([url])=>url.includes('/change-preview'))).toHaveLength(2));
 const previews=calls.mock.calls.filter(([url])=>url.includes('/change-preview'));expect(JSON.parse(String(previews[1][1]?.body))).toMatchObject({revision:2,changes:{members:['existing','alice']}});expect(calls.mock.calls.some(([,o])=>o?.method==='PATCH')).toBe(false);
},20000);
test('canceling recovered account draft cannot leak changes into another account adoption',async()=>{
 const managed={...alice,uid:1001,gid:1001,revision:3,groups:[],public_keys:[],shell:'/bin/bash',notes:'original'};
 const unmanaged={...managed,id:'b',username:'bob',managed:false};
 const calls=vi.fn(async(url:string,options?:RequestInit)=>{
   if(url==='/api/health')return Response.json({mutations:true});
   if(url.endsWith('/change-preview'))return Response.json({detail:{code:'revision_conflict',message:'changed'}},{status:409});
   if(url==='/api/system-users/a')return Response.json({...managed,revision:4});
   if(url.startsWith('/api/system-users'))return Response.json([managed,unmanaged]);
   if(url.startsWith('/api/system-groups'))return Response.json([]);
   return Response.json({});
 });vi.stubGlobal('fetch',calls);mount(<Accounts/>);
 const link=await screen.findByRole('link',{name:'alice'});const edit=within(link.closest('tr')!).getByRole('button',{name:/编\s*辑/});await waitFor(()=>expect(edit).toBeEnabled());await userEvent.click(edit);await userEvent.clear(screen.getByLabelText('备注'));await userEvent.type(screen.getByLabelText('备注'),'alice private draft');await userEvent.click(screen.getByRole('button',{name:/保\s*存/}));
 await screen.findByText('账号或配置版本已改变，请刷新后重新预览。');await userEvent.click(screen.getByRole('button',{name:'返回编辑并核对'}));await screen.findByRole('dialog',{name:'编辑 alice'});expect(screen.getByLabelText('备注')).toHaveValue('alice private draft');await userEvent.click(screen.getByRole('button',{name:/取\s*消/}));
 await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument());await userEvent.click(screen.getByRole('button',{name:'启用管理'}));
 await waitFor(()=>expect(calls.mock.calls.some(([url])=>url==='/api/system-users/b/change-preview')).toBe(true));
 const preview=calls.mock.calls.find(([url])=>url==='/api/system-users/b/change-preview')!;expect(JSON.parse(String(preview[1]?.body))).toEqual({action:'update',revision:3,changes:{managed:true}});
},20000);
