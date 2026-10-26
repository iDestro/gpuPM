import {useState} from 'react';
import {Alert,Button,Radio,Select,Space,Table,Tag,Typography} from 'antd';
import {translate,useI18n} from './i18n';
import {statusLabel,type Row} from './components';
export type ShareMember={username:string;permission:'read'|'write'};
export function canGrantShareAccess(account?:Row) {
 return !!account && account.managed && account.is_human && !account.protected && account.status==='active' && !account.disabled && !account.deleted_at && !account.recovery_required && !account.identity_conflict && !account.rename_recovery_required;
}
export function ShareMemberEditor({value=[],onChange,accounts=[]}:{value?:ShareMember[];onChange?:(value:ShareMember[])=>void;accounts?:Row[]}) {
 useI18n();
 const [selected,setSelected]=useState<string[]>([]);
 const eligible=accounts.filter(canGrantShareAccess);
 const invalid=value.filter(m=>!eligible.some(a=>a.username===m.username)).map(m=>m.username);
 return <>
  <Space.Compact block><Select virtual={false} mode="multiple" showSearch optionFilterProp="label" aria-label={translate('选择共享成员')} placeholder={translate('搜索并选择成员')} value={selected} onChange={setSelected} style={{width:'100%'}} options={eligible.filter(a=>!value.some(m=>m.username===a.username)).map(a=>({label:a.username,value:a.username}))}/><Button disabled={!selected.length} onClick={()=>{onChange?.([...value,...selected.filter(username=>!value.some(m=>m.username===username)).map(username=>({username,permission:'read' as const}))]);setSelected([]);}}>{translate('添加成员')}</Button></Space.Compact>
  <Typography.Paragraph type="secondary">{translate('新成员默认只读；读写允许新建、修改和删除文件。')}</Typography.Paragraph>
  {invalid.length ? <Alert type="warning" showIcon message={translate('以下成员不可授权：{names}。请移除这些成员后再保存。',{names:invalid.join(', ')})}/> : null}
  <Table<ShareMember> size="small" rowKey="username" pagination={false} dataSource={value} scroll={{x:380,y:280}} columns={[
   {title:translate('用户'),dataIndex:'username',ellipsis:true,render:(name:string)=>{const account=accounts.find(a=>a.username===name);return <Space direction="vertical" size={0}><span>{name}</span>{!canGrantShareAccess(account)?<Tag color="orange">{account?.status && account.status!=='active' ? statusLabel(account.status) : translate('不可授权')}</Tag>:null}</Space>;}},
   {title:translate('权限'),width:165,render:(_,r)=><Radio.Group size="small" optionType="button" buttonStyle="solid" aria-label={translate('{name} 的权限',{name:r.username})} value={r.permission} disabled={!eligible.some(a=>a.username===r.username)} onChange={e=>onChange?.(value.map(m=>m.username===r.username?{...m,permission:e.target.value}:m))} options={[{value:'read',label:translate('只读')},{value:'write',label:translate('读写')}]} style={{width:'100%'}}/>},
   {title:translate('操作'),width:80,render:(_,r)=><Button type="text" danger aria-label={translate('移除 {name}',{name:r.username})} onClick={()=>onChange?.(value.filter(m=>m.username!==r.username))}>{translate('移除')}</Button>},
  ]}/>
 </>;
}
