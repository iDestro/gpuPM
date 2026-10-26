import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import App from './App';
import { queryClient } from './api';
import { setLocale } from './i18n';
const account = {id:'alice',username:'alice',uid:1001,gid:1001,home:'/home/alice',data_dir:'/data/alice',groups:['human'],primary_group:'alice',private_group:'alice',private_gid:1001,shell:'/bin/bash',status:'active',managed:true,is_human:true,revision:5};
function setup(path='/accounts', protectedAccount=false, missing=false) {
 const row={...account,protected:protectedAccount};
 const fetch=vi.fn(async(url:string)=>new Response(JSON.stringify(url === '/api/health' ? {mutations:true,mode:'demo'} : url.endsWith('/health') ? {mode:'demo',mutations:true} : url.endsWith('/auth/me') ? {username:'admin',csrf_token:'test'} :
  url.endsWith('/activity') ? {processes:[],sessions:[],scheduled:[]} :  url.endsWith('/storage') ? {filesystems:[]} :
  url==='/api/system-users/alice' ? missing ? {detail:'Account not found'} : row : url.startsWith('/api/system-users?') ? [row] : []
 ),{status:missing && url==='/api/system-users/alice'?404:200}));
 vi.stubGlobal('fetch',fetch);
 render(<MemoryRouter initialEntries={[path]}><QueryClientProvider client={queryClient}><App/></QueryClientProvider></MemoryRouter>);
 return fetch;
}
afterEach(()=>{cleanup();vi.unstubAllGlobals();queryClient.clear();setLocale('zh-CN');});
test('username navigates to standalone management page and returns to list',async()=>{
 setup();
 const link=await screen.findByRole('link',{name:'alice'});
 expect(link).toHaveAttribute('href','/accounts/alice');
 await userEvent.click(link);
 expect(await screen.findByRole('heading',{name:'alice'})).toBeVisible();
 expect(screen.queryByRole('button',{name:'创建账号'})).not.toBeInTheDocument();
 expect(screen.getByText('/home/alice')).toBeVisible();
 await waitFor(()=>expect(screen.getByRole('button',{name:/编\s*辑/})).toBeEnabled());
 await userEvent.click(screen.getByRole('button',{name:/编\s*辑/}));
 expect(await screen.findByLabelText('普通附属系统组')).toBeInTheDocument();
 await userEvent.click(screen.getByRole('button',{name:/取\s*消/}));
 await userEvent.click(screen.getByRole('link',{name:'返回账号列表'}));
 expect(await screen.findByRole('button',{name:'创建账号'})).toBeVisible();
},15000);
test('direct detail link keeps navigation selected and protected account readonly',async()=>{
 setup('/accounts/alice',true);
 expect(await screen.findByRole('heading',{name:'alice'})).toBeVisible();
 expect(screen.getByRole('menuitem',{name:'本地账号'})).toHaveClass('ant-menu-item-selected');
 expect(screen.getByRole('button',{name:/编\s*辑/})).toBeDisabled();
 expect(screen.getByRole('button',{name:'重置密码'})).toBeDisabled();
});
test('missing detail has return link and no account mutation controls',async()=>{
 setup('/accounts/alice',false,true);
 expect(await screen.findByRole('link',{name:'返回账号列表'}, {timeout:5000})).toBeVisible();
 await waitFor(()=>expect(screen.getByRole('alert')).toBeVisible(),{timeout:5000});
 expect(screen.queryByRole('button',{name:'重置密码'})).not.toBeInTheDocument();
});
