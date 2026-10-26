import {useState} from 'react';
import {Alert,Button,Form,Input,Modal,Select,Space,Table,Tag,Typography} from 'antd';
import {Link} from 'react-router-dom';
import {CompactText,EditDialog,Row} from './components';
import {translate as t,useI18n} from './i18n';

export function SystemGroupMembers({group,accounts,writable,onClose,onChange}:{group:Row;accounts:Row[];writable:boolean;onClose:()=>void;onChange:(value:Row)=>void}) {
  useI18n();
  const [search,setSearch]=useState('');
  const [adding,setAdding]=useState<{group:Row;accounts:Row[]} | null>(null);
  const editable=writable && group.assignable === true && !group.recovery_required && !group.readonly_reasons?.length;
  const primary=new Set<string>(group.primary_users || []);
  const names=[...new Set<string>([...primary,...(group.members || [])])];
  const propose=(snapshot:Row,members:string[])=>onChange({...snapshot,action:'update',changes:{members}});
  const candidates=accounts.filter(a=>a.managed && a.is_human && !a.protected && a.status === 'active' && !a.resume_required && !a.recovery_required && !a.readonly_reasons?.length && !names.includes(a.username));
  if(adding) return <EditDialog title={t('向 {name} 添加成员',{name:adding.group.name})} initial={{members:[]}} fields={[]} disabledReason={!editable?t('当前组只读，无法修改成员。'):undefined} onClose={()=>setAdding(null)} onSave={async values=>propose(adding.group,[...new Set([...(adding.group.members || []),...values.members])])}>
    <Alert showIcon type="info" message={t('仅向此系统组添加成员，保留已有成员及其他系统组；不改变主组或任务策略。')} style={{marginBottom:16}}/>
    <Form.Item name="members" label={t('选择成员')} rules={[{required:true,type:'array',min:1}]}><Select mode="multiple" showSearch optionFilterProp="label" aria-label={t('选择成员')} options={adding.accounts.map(a=>({value:a.username,label:`${a.username} · UID ${a.uid}`}))}/></Form.Item>
    <Typography.Paragraph type="secondary">{t('保存后进入变更预览，填写原因并确认后才会执行。组权限变更通常需要重新登录。')}</Typography.Paragraph>
  </EditDialog>;
  return <Modal open title={t('{name} 的成员',{name:group.name})} onCancel={onClose} footer={<Button onClick={onClose}>{t('关闭')}</Button>} width={680} centered styles={{body:{maxHeight:'65dvh',overflowY:'auto'}}}>
    <Alert showIcon type="info" message={t('主组成员由账号主组决定，请在账号详情修改；这里只管理附加成员。')} style={{marginBottom:16}}/>
    <Space wrap style={{marginBottom:16}}><Input placeholder={t('搜索成员')} aria-label={t('搜索成员')} value={search} onChange={e=>setSearch(e.target.value)} allowClear/>{editable?<Button type="primary" disabled={!candidates.length} onClick={()=>setAdding({group:{...group,members:[...(group.members || [])]},accounts:candidates})}>{t('添加成员')}</Button>:<Tag>{t('只读')}</Tag>}</Space>
    <Table<Row> size="small" rowKey="username" tableLayout="fixed" scroll={{x:460}} dataSource={names.filter(name=>name.toLowerCase().includes(search.toLowerCase())).map(username=>({username,account:accounts.find(a=>a.username===username)}))} columns={[
      {title:t('用户'),width:210,render:(_,r)=>r.account?<Link to={`/accounts/${encodeURIComponent(r.account.id)}`}><CompactText value={r.username}/></Link>:<CompactText value={r.username}/>},
      {title:t('成员类型'),width:110,render:(_,r)=><Tag>{t(primary.has(r.username)?'主组成员':'附加成员')}</Tag>},
      {title:t('操作'),width:140,render:(_,r)=>editable&&!primary.has(r.username)?<Button size="small" danger onClick={()=>propose(group,(group.members || []).filter((name:string)=>name!==r.username))}>{t('移除成员')}</Button>:null},
    ]}/>
  </Modal>;
}
