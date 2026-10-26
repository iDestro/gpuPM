import { Alert, Descriptions, Table, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { api } from './api';
import { translate, useI18n } from './i18n';
type Row = Record<string, any>;
export function useHostMutations() {
 const health=useQuery({queryKey:['/health'],queryFn:()=>api('/health'),refetchInterval:5000,retry:false});
 return {health:health.data, writable: !health.error && health.data?.mutations === true, reason:translate(health.error ? '服务器连接不可用，已禁止系统写入。' : health.data?.mutations === true ? '系统写入已启用' : '系统只读：等待服务器确认或管理员启用写入。')};
}
export function MutationStatus(){useI18n();const state=useHostMutations();return <Tag color={state.writable?'green':'orange'} title={state.reason}>{translate(state.writable?'系统写入已启用':'系统只读')}</Tag>;}
const creationStages: Record<string,string> = {"native_account": "创建原生账号", "directories": "准备私有目录", "files": "准备账号文件", "credentials": "设置登录凭据", "policy": "应用账号策略", "login_pending": "待应用登录策略", "initialized": "初始化完成"};
export const creationStageLabel = (stage:string) => translate(creationStages[stage] || stage);
const reasons:Record<string,string>={protected_account:"受保护账号",account_deleted:'已软删除',system_account:'系统账号',api_account:'API 服务账号',maintenance_account:'维护账号',reserved_account:'保留账号',invalid_username:'用户名不符合管理规则',non_human_readonly:'非人员账号',unmanaged_account:'未启用管理',identity_conflict:'原生身份冲突',rename_recovery_required:'改名未完成，需管理员恢复',creation_incomplete:'创建未完成，请继续创建',mutations_disabled:'系统写入未启用'};
export function readonlyReason(account:Row){return (account.readonly_reasons || []).map((code:string)=>translate(reasons[code] || code)).join(' · ');}
export const errorGuidance:Record<string,string>={
 share_path_legacy:'此共享目录位于旧存储路径，请由管理员核对目录位置后再修改授权；平台不会移动已有文件。',
 invalid_share_member:'只能授权给正常启用的纳管人员账号，请移除不可授权成员后重试。',
 share_members_unavailable:'共享成员信息无法核验，请检查服务器权限配置后重试。',
 share_members_unverified:'共享成员权限回读失败，请检查权限并重新预览。',

 share_creation_incomplete:'共享创建未完成，已保留目录和文件。请管理员检查残留目录及权限后再重试。',
 acl_readback_mismatch:'共享权限回读不一致，请检查目录权限后重新预览。',
"creation_not_pending":"账号已完成创建，请刷新账号信息后选择需要的操作。",
"invalid_profile":"保存的业务配置无效，请管理员核对创建记录后重试。",
"external_policy_changed":"系统登录策略已在平台外变更，请管理员核对后重试，平台不会覆盖外部限制。",
"login_policy_unverified":"登录策略尚未通过系统回读核验，请刷新状态；持续失败时请管理员检查。",
"credentials_in_preview":"凭据不能进入预览，请重新打开专用密码或继续创建流程。",
"capability_unavailable":"服务器尚未确认此能力，请检查连接和版本后重试。",
"device_mismatch":"目录所在设备与记录不一致，已停止操作。请管理员核对挂载和设备配置。",
"device_unavailable":"配置的存储设备不可用，请管理员检查设备和挂载后重试。",
"unsafe_path":"目录缺失、包含符号链接或权限不安全，请管理员核对受控目录。",
"uid_lifecycle_conflict":"系统分配了曾使用的 UID，账号保持受限。请管理员核对身份记录后再恢复。",
"rename_recovery_required":"账号改名尚未完成，请管理员核对原生账号和目录后恢复管理。",
"revision_conflict":"账号或配置版本已改变，请刷新后重新预览。",
 secret_in_preview:"凭据不能进入预览，请重新打开专用密码或继续创建流程。",

 scope_changed:'预览范围或版本已改变，请关闭并重新预览。', invalid_preview:'请重新预览操作范围后再提交。', reason_required:'请填写操作原因后提交。',
 weak_password:'密码不符合强度要求，请使用更长且不包含用户名的密码。', invalid_keys:'SSH 公钥格式无效，请提供完整的受支持公钥。',
 creation_identity_conflict:'原生身份冲突，请由管理员核对 UID 和目录所有者。',creation_path_conflict:'目录检查未通过，请按预览中的检查项修复后重试。',credentials_required:'请重新提供密码或 SSH 公钥以继续创建。',
 host_command_failed:'系统命令执行失败，请展开诊断并由管理员检查后重试。',account_active:'账号仍有活动，请等待进程、会话和定时任务结束后重试。',account_scheduled:'账号仍有活动，请等待进程、会话和定时任务结束后重试。',
initialization_unverified:'存储根目录尚未核验，请管理员完成初始化后再创建账号或共享目录。',adoption_path_conflict:'目录检查未通过，请按预览中的检查项修复后重试。',mutations_disabled:'系统只读：等待服务器确认或管理员启用写入。',agent_unavailable:'服务器连接不可用，已禁止系统写入。',identity_conflict:'原生身份冲突，请由管理员核对 UID 和目录所有者。',creation_incomplete:'账号创建未完成，请使用继续创建并重新提供凭据。',recovery_credentials_required:'请重新提供密码或 SSH 公钥以继续创建。',preview_expired:'预览已过期，请重新预览后再确认。',activity_unknown:'活动扫描不完整，请修复扫描错误后重试。',account_busy:'账号仍有活动，请等待进程、会话和定时任务结束后重试。'};
const fields:Record<string,string>={permission:"权限",group_id:"业务组 ID",priority:"优先级 (0–100)",disabled:'停用限制',deleted_at:'软删除时间',status:'状态',login_policy_status:'登录策略生效状态',creation_status:'创建状态',username:'用户名',name:'名称',uid:'UID',gid:'GID',shell:'登录 Shell',groups:'附属组',primary_group:'主组',members:'成员',managed:'受管',home:'主目录',data_dir:'数据目录',path:'路径',reader_group:'只读组',writer_group:'读写组',soft_bytes:'空间软限额',hard_bytes:'空间硬限额',soft_inodes:'inode 软限额',hard_inodes:'inode 硬限额',grace_seconds:'当前超限宽限期（秒）',expires_on:'有效期',require_password_change:'首次登录改密',public_keys:'SSH 公钥',notes:'备注',filesystem_id:'文件系统',below_usage:'新限额低于当前用量'};
function value(v:any):string{return v==null?'—':Array.isArray(v)?v.map(value).join(', '):typeof v==='object'?Object.entries(v).map(([k,x])=>`${translate(fields[k]||k)}: ${value(x)}`).join(' · '):typeof v==='boolean'?translate(v?'是':'否'):v==='on_confirmation'?translate('确认时生效'):v==='read'?translate('只读'):v==='write'?translate('读写'):String(v);}
const previewMessages:Record<string,string> = {"Root must inspect the existing home and data paths and prepare account-owned private directories.":"管理员需检查已有主目录和数据目录，并准备由该账号所有的私有目录。","Existing home paths outside configured roots require a separately approved migration; this operation never moves data.":"已有主目录位于配置根目录之外时，必须另行批准迁移；本操作不会移动数据。","Repeat the preview after resolving every failed check.":"修复全部未通过的检查项后，请重新预览。","Existing processes, sessions, scheduled activity and files are retained. Disabling/soft-deleting blocks new logins only; restore/enable preserve other restriction causes.": "保留现有进程、会话、定时任务和文件。停用或软删除只阻止新登录；恢复或启用不会解除其他限制。", "Rename requires no processes, sessions or known scheduled activity, pauses new logins, and changes only controlled home/data paths; UID and files are retained.": "改名前必须没有进程、会话和已知定时任务。期间暂停新登录，只修改受控主目录和数据目录路径，保留 UID 和文件。", "Primary group changes apply to new logins; native usermod may update old-GID files under home. Data directory and other paths remain unchanged; no directory migration.": "主组变更对新登录生效；系统可能更新主目录内旧 GID 文件的组。数据目录和其他路径不变，不迁移目录。", "root directory access and default ACL for new descendants; existing nested ACLs retained": "修改共享根目录访问权限及新建内容的默认 ACL，保留现有子目录和文件的 ACL。"};
export function ChangePreview({data}:{data:Row}){
 useI18n();const before=data.before || data.current || data.host_scope || {}; const changes={...data.changes,...(data.after || data.proposed || {})};
 return <>
 <Typography.Paragraph>{translate('操作')}：{translate(({disable:'停用',enable:'启用',delete:'软删除',restore:'恢复',resume:'继续创建',update:'修改',create:'创建'} as Record<string,string>)[data.action] || data.action || '修改')} · {data.id || '—'}</Typography.Paragraph>
 <Descriptions size="small" column={{xs:1,sm:2}} items={Object.entries({...Object.fromEntries(['username','name','uid','gid'].filter(k=>before[k]!=null).map(k=>[k,before[k]])),...(data.path ? {path:data.path}:{}),...data.paths}).map(([k,v])=>({key:k,label:translate(fields[k]||k),children:value(v)}))}/>
 <Table size="small" pagination={false} rowKey="field" scroll={{x:480}} dataSource={Object.entries(changes).filter(([k,v])=>k!=='password' && (JSON.stringify(before[k])!==JSON.stringify(v) || Object.hasOwn(data.changes || {},k))).map(([field,after])=>({field,before:before[field],after}))} columns={[{title:translate('变更项'),dataIndex:'field',render:k=>translate(fields[k]||k)},{title:translate('变更前'),dataIndex:'before',render:value},{title:translate('变更后'),dataIndex:'after',render:value}]}/>
 {data.migration?<Alert type="warning" showIcon message={translate("首次成员授权会启用目录专用权限，保留原授权组和已有文件的单独权限。请核对成员变化；新增成员访问旧文件可能仍需文件所有者授权。")}/>:null}
 {data.impact?<Alert type="info" showIcon message={typeof data.impact === "string" ? translate(previewMessages[data.impact] || data.impact) : value(data.impact)}/>:null}
 {data.adoption?<><Typography.Title level={5}>{translate('启用管理检查')}</Typography.Title><Table size="small" pagination={false} rowKey="code" scroll={{x:500}} dataSource={data.adoption.checks} columns={[{title:translate('路径'),dataIndex:'path'},{title:translate('状态'),dataIndex:'ok',render:v=>translate(v?'通过':'需修复')},{title:translate('当前'),dataIndex:'actual',render:value},{title:translate('要求'),dataIndex:'expected',render:value}]}/>{data.adoption.manual_steps?.map((step:string)=><Typography.Paragraph key={step}>{translate(previewMessages[step] || step)}</Typography.Paragraph>)}</>:null}
 </>;
}
