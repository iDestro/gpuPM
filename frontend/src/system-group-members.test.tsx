import {afterEach,expect,test,vi} from 'vitest';
import {cleanup,render,screen,within,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {MemoryRouter} from 'react-router-dom';
import {SystemGroupMembers} from './system-group-members';
const group={id:'project',name:'project',revision:3,assignable:true,members:['existing'],primary_users:['primary']};
const accounts=[{id:'alice',username:'alice',uid:1001,managed:true,is_human:true,status:'active'}, {id:'root',username:'root',uid:0,managed:true,is_human:true,status:'active',protected:true}];
afterEach(cleanup);
test('adding members preserves existing membership and revision before preview',async()=>{
 const change=vi.fn();render(<MemoryRouter><SystemGroupMembers group={group} accounts={accounts} writable onClose={()=>{}} onChange={change}/></MemoryRouter>);
 await waitFor(()=>expect(screen.getByText('primary',{exact:true})).toBeVisible());
 expect(within(screen.getByText('primary',{exact:true}).closest('tr')!).queryByRole('button',{name:'移除成员'})).toBeNull();
 await userEvent.click(screen.getByRole('button',{name:'添加成员'}));
 await userEvent.type(screen.getByRole('combobox',{name:'选择成员'}),'alice');
 expect(screen.queryByText('root · UID 0')).toBeNull();
 await userEvent.click(await screen.findByText('alice · UID 1001'));
 await userEvent.click(screen.getByRole('button',{name:/保\s*存/}));
 expect(change).toHaveBeenCalledWith(expect.objectContaining({revision:3,changes:{members:['existing','alice']}}));
},15000);
test('readonly group only displays members; removal preserves other memberships',async()=>{
 const change=vi.fn();const view=render(<MemoryRouter><SystemGroupMembers group={group} accounts={accounts} writable onClose={()=>{}} onChange={change}/></MemoryRouter>);
 await userEvent.click(screen.getByRole('button',{name:'移除成员'}));
 expect(change).toHaveBeenCalledWith(expect.objectContaining({revision:3,changes:{members:[]}}));
 view.rerender(<MemoryRouter><SystemGroupMembers group={{...group,assignable:false}} accounts={accounts} writable onClose={()=>{}} onChange={change}/></MemoryRouter>);
 expect(screen.queryByRole('button',{name:'添加成员'})).toBeNull();
 expect(screen.queryByRole('button',{name:'移除成员'})).toBeNull();
});
test('cancel add returns to member list without proposing a change',async()=>{
 const change=vi.fn();render(<MemoryRouter><SystemGroupMembers group={group} accounts={accounts} writable onClose={()=>{}} onChange={change}/></MemoryRouter>);
 await userEvent.click(screen.getByRole('button',{name:'添加成员'}));
 await userEvent.click(screen.getByRole('button',{name:/取\s*消/}));
 await waitFor(()=>expect(screen.getByText('existing',{exact:true})).toBeVisible());
 expect(change).not.toHaveBeenCalled();
});
