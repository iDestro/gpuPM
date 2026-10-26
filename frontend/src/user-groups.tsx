import { useState } from "react";
import { Alert, Button, Card, Descriptions, Empty, Form, InputNumber, Modal, Select, Space, Switch, Table, Tag, Typography } from "antd";
import { Link } from "react-router-dom";
import { CompactText, EditDialog, ErrorAlert, Row, RuntimeInput, runtimeSeconds, TermLabel, useData, useSave } from "./components";
import { translate as t, useI18n } from "./i18n";
import { PageHead } from "./pages";

const policyFields = [
  { key: "priority", label: "优先级 (0–100)", setting: "default_task_priority" },
  { key: "max_runtime_seconds", label: "最大运行时间", setting: "default_max_runtime_seconds" },
  { key: "protected", label: "任务保护", setting: "default_task_protected" },
  { key: "deadline_action", label: "到期动作", setting: "default_deadline_action" },
  { key: "orphan_reminder", label: "残留提醒", setting: "default_orphan_reminder" },
  { key: "orphan_wait_seconds", label: "残留等待时间", setting: "default_orphan_wait_seconds" },
];
const sourceLabels: Row = { global: "继承策略配置", group: "任务策略组配置", personal: "个人自定义", task: "任务单独设置", legacy: "迁移保留" };
const changeNotice = "仅影响新任务；已有任务保留当前策略，可在任务详情单独修改。";
export const groupLabel = (group: Row) => group.is_default ? t("默认组") : group.is_custom ? t("自定义组") : ["默认组", "自定义组"].includes(group.name) ? t("{name}（普通组）", {name:group.name}) : group.name;
export function policyValue(key: string, value: any) {
  if (value === undefined) return "—";
  if (key.endsWith("seconds")) return value == null ? t("不限时") : t("{hours}时 {minutes}分 {seconds}秒", { hours: Math.floor(value / 3600), minutes: Math.floor(value % 3600 / 60), seconds: value % 60 });
  if (typeof value === "boolean") return t(value ? "开启" : "已关闭");
  if (key === "deadline_action") return t(value === "terminate" ? "自动终止" : "仅提醒");
  return String(value);
}
export function PolicySummary({ policy = {}, sources = {} }: { policy?: Row; sources?: Row }) {
  return <Descriptions size="small" column={1} items={policyFields.map(({key,label}) => ({ key, label: <TermLabel label={label}/>, children: <Space wrap><span>{policyValue(key, policy[key])}</span><Typography.Text type="secondary">{t(sourceLabels[sources[key]] || "继承策略配置")}</Typography.Text></Space> }))} />;
}
function PolicyOverrides({ value = {}, onChange, settings }: { value?: Row; onChange?: (value: Row) => void; settings: Row }) {
  return <div className="policy-overrides">{policyFields.map(({key,label,setting}) => {
    const inherit = !Object.prototype.hasOwnProperty.call(value, key);
    const current = inherit ? settings[setting] : value[key];
    const set = (next: any) => onChange?.({...value, [key]:next});
    return <div className="policy-field" key={key}>
      <div className="policy-field-heading"><Typography.Text strong><TermLabel label={label}/></Typography.Text><Space><Switch size="small" checked={inherit} aria-label={t("{field}：继承策略配置", {field:t(label)})} onChange={checked => {const next = {...value}; if (checked) delete next[key]; else next[key] = settings[setting]; onChange?.(next);}}/><span>{t("继承策略配置")}</span></Space></div>
      {inherit ? <Typography.Text type="secondary">{t("当前值：{value}", {value:policyValue(key,current)})}</Typography.Text>
        : key === "priority" ? <InputNumber aria-label={t(label)} min={0} max={100} precision={0} value={current} onChange={set}/>
        : key === "max_runtime_seconds" || key === "orphan_wait_seconds" ? <RuntimeInput label={label} value={current == null ? {} : {hours:Math.floor(current/3600),minutes:Math.floor(current%3600/60),seconds:current%60}} onChange={next=>set(runtimeSeconds(next))} required={key === "orphan_wait_seconds"} max={key === "orphan_wait_seconds" ? 86400 : 315360000}/>
        : key === "deadline_action" ? <Select aria-label={t(label)} style={{width:180}} value={current} onChange={set} options={[{value:"notify",label:t("仅提醒")},{value:"terminate",label:t("自动终止")}]}/>
        : <Switch aria-label={t(label)} checked={current} onChange={set}/>}
    </div>;
  })}</div>;
}
function validateOverrides(_: unknown, value: Row = {}) {
  for (const [key,v] of Object.entries(value)) {
    if (key === "max_runtime_seconds" && v === null) continue;
    if (key === "priority" || key.endsWith("seconds")) {
      if (!Number.isInteger(v) || v < (key === "priority" ? 0 : 1) || v > (key === "priority" ? 100 : key === "orphan_wait_seconds" ? 86400 : 315360000)) return Promise.reject(new Error(t("请填写有效的优先级或时间；不限时请点击“不限时”。")));
    }
  }
  return Promise.resolve();
}
export function UserGroups() {
  useI18n();
  const groups = useData("/groups"), users = useData("/users"), settings = useData("/settings");
  const save = useSave();
  const [edit,setEdit] = useState<Row | null>(null), [deleting,setDeleting] = useState<Row | null>(null), [detail,setDetail] = useState<Row | null>(null);
  const [assignment,setAssignment] = useState<{target:Row; candidates:Row[]; uids:number[]} | null>(null);
  const openAssignment = (target:Row, members?:Row[]) => setAssignment({target, candidates:(users.data || []).filter((u:Row)=>u.policy_editable && u.group_id !== target.id), uids:members?.map(u=>u.uid) || []});
  const selected = groups.data?.find((g:Row)=>g.id === detail?.id) || detail;
  return <>
    <PageHead title={t("任务策略组")} description={t("按组配置任务优先级、运行时限和保护规则。共享目录授权独立管理。")} action={<Button type="primary" disabled={!settings.data || !!settings.error} onClick={()=>setEdit({name:"",notes:"",policy_overrides:{}})}>{t("新建任务策略组")}</Button>}/>
    <Alert showIcon type="info" message={t(changeNotice)} style={{marginBottom:16}}/>
    <ErrorAlert error={groups.error || users.error || settings.error || save.error}/>
    <Card><Table<Row> size="small" tableLayout="fixed" scroll={{x:800}} rowKey="id" loading={groups.isPending} dataSource={groups.data || []} columns={[
      {title:t("组名"),width:180,render:(_,r)=><Button type="link" className="table-link" onClick={()=>setDetail(r)}><CompactText value={groupLabel(r)}/></Button>},
      {title:t("策略来源"),width:160,render:(_,r)=><Tag>{t(r.is_custom ? "各用户独立配置" : Object.keys(r.policy_overrides || {}).length ? "部分配置已覆盖" : "全部继承策略配置")}</Tag>},
      {title:t("优先级"),width:90,render:(_,r)=>r.is_custom ? "—" : r.effective_policy?.priority ?? "—"},
      {title:t("最大运行时间"),width:180,render:(_,r)=>r.is_custom ? "—" : policyValue("max_runtime_seconds",r.effective_policy?.max_runtime_seconds)},
      {title:t("成员"),width:70,render:(_,r)=>r.member_count ?? (users.data || []).filter((u:Row)=>u.group_id===r.id).length},
      {title:t("操作"),width:180,render:(_,r)=><Space><Button size="small" onClick={()=>setDetail(r)}>{t("详情")}</Button>{!r.is_default && !r.is_custom ? <><Button size="small" disabled={!settings.data || !!settings.error} onClick={()=>setEdit(r)}>{t("编辑")}</Button><Button size="small" danger onClick={()=>setDeleting(r)}>{t("删除")}</Button></> : null}</Space>},
    ]}/></Card>
    {edit ? <EditDialog title={t(edit.id ? "编辑任务策略组" : "新建任务策略组")} initial={edit} fields={[{name:"name",label:t("组名"),required:true},{name:"notes",label:t("备注"),type:"textarea"}]} onClose={()=>setEdit(null)} onSave={v=>save.mutateAsync({path:edit.id?`/groups/${edit.id}`:"/groups",method:edit.id?"PATCH":"POST",body:v})}>
      <Form.Item name="policy_overrides" rules={[{validator:validateOverrides}]}><PolicyOverrides settings={settings.data || {}}/></Form.Item>
    </EditDialog> : null}
    {deleting ? <EditDialog title={t("删除 {name} 并迁移成员",{name:deleting.name})} fields={[]} onClose={()=>setDeleting(null)} onSave={()=>save.mutateAsync({path:`/groups/${deleting.id}?move_to=1`,method:"DELETE"})}><Alert type="warning" showIcon message={t("成员将移回默认组，个人自定义配置保留；已有任务不变。")} style={{marginBottom:16}}/></EditDialog> : null}
    {selected ? <Modal open title={groupLabel(selected)} onCancel={()=>setDetail(null)} footer={<Button onClick={()=>setDetail(null)}>{t("关闭")}</Button>} width={680} centered styles={{body:{maxHeight:"65dvh",overflowY:"auto"}}}>
      {selected.notes ? <Typography.Paragraph>{selected.notes}</Typography.Paragraph> : null}
      {selected.is_custom ? <Alert type="info" showIcon message={t("自定义组没有统一配置。每位用户的个人配置独立生效，未覆盖项继承策略配置。")}/> : <PolicySummary policy={selected.effective_policy} sources={selected.policy_sources}/>}
      {selected.is_default ? <Typography.Paragraph><Link to="/settings">{t("前往策略配置")}</Link></Typography.Paragraph> : null}
      <Space wrap style={{margin:"16px 0"}}><Typography.Text strong>{t("组内成员")}</Typography.Text><Button disabled={!users.data || !!users.error || !!groups.error} onClick={()=>openAssignment(selected)}>{t("添加成员")}</Button></Space>
      <Table<Row> size="small" rowKey="uid" loading={users.isPending} dataSource={(users.data || []).filter((u:Row)=>u.group_id===selected.id)} locale={{emptyText:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("暂无成员")}/>}} columns={[{title:t("用户"),dataIndex:"username",render:(name,r)=><Link to={`/accounts/${encodeURIComponent(r.account_ref || r.uid)}`}>{name}</Link>},{title:t("优先级"),render:(_,r)=>r.effective_policy?.priority ?? "—"},{title:t("最大运行时间"),render:(_,r)=>policyValue("max_runtime_seconds",r.effective_policy?.max_runtime_seconds)},{title:t("操作"),render:(_,r)=>!selected.is_default ? <Button size="small" disabled={!r.policy_editable || !!users.error || !!groups.error} onClick={()=>openAssignment(groups.data.find((g:Row)=>g.is_default),[r])}>{t("移回默认组")}</Button> : null}]}/>
    </Modal> : null}
    {assignment ? <EditDialog title={t("调整成员至 {name}",{name:groupLabel(assignment.target)})} initial={{uids:assignment.uids}} fields={[]} onClose={()=>setAssignment(null)} onSave={values=>save.mutateAsync({path:`/groups/${assignment.target.id}/members`,method:"POST",body:{members:values.uids.map((uid:number)=>({uid,group_id:assignment.candidates.find(u=>u.uid === uid)!.group_id}))}})}>
      <Alert type="info" showIcon message={t(changeNotice)} description={t("选中账号将从原策略组移入目标组，个人配置保留；系统用户组和共享权限不变。每次最多 200 人。")} style={{marginBottom:16}}/>
      <Form.Item name="uids" label={t("选择成员")} rules={[{required:true,type:"array",min:1,max:200}]}><Select mode="multiple" showSearch optionFilterProp="label" aria-label={t("选择成员")} options={assignment.candidates.map(u=>({value:u.uid,label:`${u.username} · ${groupLabel(groups.data.find((g:Row)=>g.id === u.group_id) || {name:"—"})} → ${groupLabel(assignment.target)}`}))}/></Form.Item>
      <Typography.Paragraph type="secondary">{t("仅列出可修改策略且不在目标组的账号。")}</Typography.Paragraph>
    </EditDialog> : null}
  </>;
}
function AssignmentFields({ groups, settings }: { groups:Row[];settings:Row }) {
  const form = Form.useFormInstance();
  const groupId = Form.useWatch("group_id", form);
  const custom = groups.find(g=>g.id === groupId)?.is_custom;
  return <>
    <Form.Item label={t("任务策略组")} name="group_id" rules={[{required:true}]}><Select showSearch optionFilterProp="label" aria-label={t("任务策略组")} options={groups.map(g=>({label:groupLabel(g),value:g.id}))}/></Form.Item>
    {custom ? <><Typography.Paragraph type="secondary">{t("个人配置仅在自定义组生效；切换到其他组后仍会保留。")}</Typography.Paragraph><Form.Item name="personal_policy" rules={[{validator:validateOverrides}]}><PolicyOverrides settings={settings}/></Form.Item></> : <Typography.Paragraph type="secondary">{t("当前采用所选组的配置，个人自定义配置暂不生效。")}</Typography.Paragraph>}
  </>;
}
export function UserTaskPolicy({account}: {account:Row}) {
  useI18n();
  const users = useData("/users"), groups = useData("/groups"), settings = useData("/settings");
  const user = users.data?.find((u:Row)=>u.uid === account.uid);
  const group = groups.data?.find((g:Row)=>g.id === user?.group_id);
  const save = useSave();
  const [editing,setEditing] = useState(false);
  return <Card title={t("任务策略")} extra={<Button title={!user?.policy_editable ? t("仅正常启用的纳管人员账号可修改任务策略") : undefined} disabled={!user?.policy_editable || !groups.data || !settings.data || !!users.error || !!groups.error || !!settings.error} onClick={()=>setEditing(true)}>{t("配置任务策略")}</Button>}>
    <ErrorAlert error={users.error || groups.error || settings.error}/>
    <Typography.Paragraph><Typography.Text type="secondary">{t("任务策略组")}: </Typography.Text>{group ? groupLabel(group) : "—"}</Typography.Paragraph>
    <PolicySummary policy={user?.effective_policy} sources={user?.policy_sources}/>
    <Typography.Paragraph type="secondary" style={{marginTop:12,marginBottom:0}}>{t(changeNotice)}</Typography.Paragraph>
    {editing ? <EditDialog title={t("配置 {name} 的任务策略",{name:account.username})} fields={[]} initial={{group_id:user.group_id,personal_policy:user.personal_policy || {}}} onClose={()=>setEditing(false)} onSave={values=>save.mutateAsync({path:`/users/${account.uid}`,body:{group_id:values.group_id,...(groups.data.find((g:Row)=>g.id === values.group_id)?.is_custom ? {personal_policy:values.personal_policy || user.personal_policy || {}} : {})}})}><AssignmentFields groups={groups.data} settings={settings.data}/></EditDialog> : null}
  </Card>;
}
