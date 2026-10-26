import {afterEach,expect,test,vi} from 'vitest';
import {act,cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClientProvider} from '@tanstack/react-query';
import {queryClient} from './api';
import {PreviewDialog,useData} from './components';
function List(){const q=useData('/shares');return <span>revision {q.data?.revision}</span>;}
function setup(expiresAt=new Date(Date.now()+30000).toISOString()){
 let saved=false, previews=0;
 const request=vi.fn(async(url:string,options?:RequestInit)=>{
  if(url==='/api/health')return Response.json({mutations:true});
  if(url==='/api/shares')return Response.json({revision:saved?2:1});
  if(url.endsWith('/change-preview')){
   previews++;
   if(saved)return Response.json({detail:{code:'revision_conflict',message:'configuration or membership changed'}},{status:409});
   return Response.json({token:`token-${previews}`,kind:'share',revision:1,expires_at:previews===1?expiresAt:new Date(Date.now()+30000).toISOString(),proposed:{members:[]}});
  }
  if(options?.method==='PATCH'){saved=true;return Response.json({id:'s',revision:2,status:'active'});}
  return Response.json({});
 });
 vi.stubGlobal('fetch',request);
 render(<QueryClientProvider client={queryClient}><List/><PreviewDialog title="授权" previewPath="/shares/s/change-preview" previewBody={{revision:1,changes:{members:[]}}} executePath="/shares/s" executeBody={{revision:1,members:[]}} method="PATCH" onClose={()=>{}}/></QueryClientProvider>);
 return request;
}
afterEach(()=>{cleanup();queryClient.clear();vi.unstubAllGlobals();vi.restoreAllMocks();});
async function submit(){await screen.findByText(/范围由服务器核验/);await userEvent.type(screen.getByLabelText('操作原因'),'adjust access');await userEvent.click(screen.getByRole('button',{name:'确认执行'}));await screen.findByText('请求已提交，以下为服务器返回结果');}
test('successful execution refreshes current data without replaying the frozen preview',async()=>{const request=setup();await submit();await screen.findByText('revision 2');expect(request.mock.calls.filter(([url])=>url.endsWith('/change-preview'))).toHaveLength(1);expect(screen.queryByText('账号或配置版本已改变，请刷新后重新预览。')).not.toBeInTheDocument();expect(request.mock.calls.filter(([,options])=>options?.method==='PATCH')).toHaveLength(1);});
test('completed operation cannot later become an expired preview',async()=>{setup();await submit();vi.spyOn(Date,'now').mockReturnValue(Date.now()+31000);await act(async()=>{await new Promise(resolve=>setTimeout(resolve,1100));});expect(screen.queryByText('预览已过期，请重新预览后再确认。')).not.toBeInTheDocument();expect(screen.getByRole('button',{name:/关\s*闭/})).toBeInTheDocument();});
test('expired preview can be explicitly renewed without losing the reason',async()=>{const request=setup(new Date(Date.now()-1000).toISOString());await screen.findByText('预览已过期，请重新预览后再确认。');await userEvent.type(screen.getByLabelText('操作原因'),'keep my reason');expect(screen.getByRole('button',{name:'确认执行'})).toBeDisabled();await userEvent.click(screen.getByRole('button',{name:'重新预览'}));await waitFor(()=>expect(screen.queryByText('预览已过期，请重新预览后再确认。')).not.toBeInTheDocument());await userEvent.click(screen.getByRole('button',{name:'确认执行'}));await screen.findByText('请求已提交，以下为服务器返回结果');const patch=request.mock.calls.find(([,options])=>options?.method==='PATCH');expect(JSON.parse(String(patch?.[1]?.body))).toMatchObject({token:'token-2',reason:'keep my reason'});});
test('genuine preview conflicts remain visible and cannot be executed',async()=>{vi.stubGlobal('fetch',vi.fn(async(url:string)=>url==='/api/health'?Response.json({mutations:true}):Response.json({detail:{code:'revision_conflict',message:'configuration or membership changed'}},{status:409})));render(<QueryClientProvider client={queryClient}><PreviewDialog title="授权" previewPath="/shares/s/change-preview" executePath="/shares/s" onClose={()=>{}}/></QueryClientProvider>);await screen.findByText('账号或配置版本已改变，请刷新后重新预览。');await userEvent.type(screen.getByLabelText('操作原因'),'do not bypass');expect(screen.getByRole('button',{name:'确认执行'})).toBeDisabled();expect(screen.queryByText('请求已提交，以下为服务器返回结果')).not.toBeInTheDocument();});
test('pending execution cannot be cancelled or closed and shows its result',async()=>{
 let finish!:(value:Response)=>void;const close=vi.fn();
 vi.stubGlobal('fetch',vi.fn(async(url:string,options?:RequestInit)=>url==='/api/health'?Response.json({mutations:true}):options?.method==='PATCH'?new Promise<Response>(resolve=>{finish=resolve;}):Response.json({token:'t',kind:'share',expires_at:new Date(Date.now()+30000).toISOString(),proposed:{members:[]}})));
 render(<QueryClientProvider client={queryClient}><PreviewDialog title="授权" previewPath="/shares/s/change-preview" executePath="/shares/s" method="PATCH" onClose={close}/></QueryClientProvider>);
 await screen.findByText(/范围由服务器核验/);await userEvent.type(screen.getByLabelText('操作原因'),'update');await userEvent.click(screen.getByRole('button',{name:'确认执行'}));
 expect(screen.getByRole('button',{name:/取\s*消/})).toBeDisabled();expect(screen.queryByRole('button',{name:'Close'})).not.toBeInTheDocument();await userEvent.keyboard('{Escape}');expect(close).not.toHaveBeenCalled();
 await act(async()=>finish(Response.json({status:'active'})));await screen.findByText('请求已提交，以下为服务器返回结果');expect(close).not.toHaveBeenCalled();
});
test('execution conflict requires review, and failed refresh leaves the draft available',async()=>{
 const edit=vi.fn().mockRejectedValueOnce(new Error('refresh unavailable')).mockResolvedValueOnce(undefined);
 vi.stubGlobal('fetch',vi.fn(async(url:string,options?:RequestInit)=>url==='/api/health'?Response.json({mutations:true}):options?.method==='PATCH'?Response.json({detail:{code:'revision_conflict',message:'changed'}},{status:409}):Response.json({token:'t',kind:'share',expires_at:new Date(Date.now()+30000).toISOString(),proposed:{members:[]}})));
 render(<QueryClientProvider client={queryClient}><PreviewDialog title="授权" previewPath="/shares/s/change-preview" executePath="/shares/s" method="PATCH" onClose={()=>{}} onEdit={edit}/></QueryClientProvider>);
 await screen.findByText(/范围由服务器核验/);await userEvent.type(screen.getByLabelText('操作原因'),'keep reason');await userEvent.click(screen.getByRole('button',{name:'确认执行'}));await screen.findByText('账号或配置版本已改变，请刷新后重新预览。');expect(screen.getByRole('button',{name:'确认执行'})).toBeDisabled();
 await userEvent.click(screen.getByRole('button',{name:'返回编辑并核对'}));await screen.findByText('refresh unavailable');expect(screen.getByLabelText('操作原因')).toHaveValue('keep reason');await userEvent.click(screen.getByRole('button',{name:'返回编辑并核对'}));await waitFor(()=>expect(edit).toHaveBeenCalledTimes(2));
});
