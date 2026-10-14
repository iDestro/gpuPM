# Implementation interface contract

All APIs are under `/api`, JSON, same-origin. Errors use `{detail: {code, message}}`. Dates are timezone-aware ISO UTC; UI renders Asia/Shanghai. Empty/missing metrics are null, never inferred zero.

`GET /health` is anonymous, returns `{status, mode, agent}`. All other reads require an administrator session. Login POST `{username,password}` returns `{username,csrf_token}` and sets HttpOnly `gpupm_session`. GET `/auth/me` returns same shape. POST `/auth/logout` ends the session. Mutations require `X-CSRF-Token`; termination mutations never auto-retry.

List endpoints return arrays unless specified. `/tasks` returns `{items,total,collected_at,stale,source}` with `gpu`, `uid`, `group_id`, `status`, `sort` (priority/runtime/memory), `page`, `page_size`. `/tasks/{id}` returns task with `members` and `context` process nodes. `/gpus` returns `{items,collected_at,stale,source}`. `/overview` returns `{gpus,task_count,overdue_count,anomaly_count,source,collected_at,stale,agent_error}`.

GPU fields: `uuid,index,name,memory_total,memory_used,utilization,error` (bytes and percent). Process fields: `identity:{boot_id,pid,start_ticks}`, `pid,ppid,uid,username,command,create_time,status,gpu_memory:{uuid:bytes|null},evidence`. Task fields: `id,name,uid,username,group_id,priority,priority_tuple:[group,user,task],notes,protected,started_at,expires_at,max_runtime_seconds,deadline_action,deadline_at,overdue,remaining_seconds,status,memory_used,runtime_seconds,revision,policy_status,members,context,anomalies`.

PATCH `/tasks/{id}` accepts `revision` plus name/notes/priority/protected/expires_at/max_runtime_seconds/deadline_action/cleanup_orphans. POST `/tasks/merge` accepts `task_ids` and `revisions` map. POST `/tasks/{id}/split` accepts `revision,identities`. PATCH `/tasks/{id}/members` accepts `revision,excluded_identities`. POST `/tasks/{id}/termination-preview` accepts optional `identity` (single process), returns `{token,expires_at,task_id,revision,targets,excluded}`. POST `/tasks/{id}/terminate` accepts `{token,reason,idempotency_key}` returns operation. GET `/operations/{id}` returns `{id,status,reason,results,created_at,source}`. Only root agent determines signal scope.

GET/POST `/groups`, PATCH/DELETE `/groups/{id}` use `{id,name,priority,notes,is_default}`; delete requires `move_to`. GET `/users`, PATCH `/users/{uid}` use `{uid,username,group_id,priority,notes}`. These are business groups, not Linux groups.

GET/PATCH `/settings`: `scan_interval_seconds,term_grace_seconds,default_max_runtime_seconds,default_deadline_action,storage_scan_interval_seconds,warning_percent,critical_percent,home_base,data_base,share_base,mode` (root paths/mode readonly).

GET `/system-users?state=all|active|disabled|expired|deleted`: account array with `id,lifecycle_id,identity_conflict,username,uid,gid,primary_group,group_id,priority,groups,shell,home,data_dir,status,managed,protected,disabled,deleted_at,expires_on,expires_effective_at,require_password_change,notes,revision,public_keys,login_policy_status,last_success_login,login_coverage`. POST accepts `username,password?,public_keys,notes,groups,group_id,priority,require_password_change,expires_on`; at least one credential is required. PATCH `/{id}` accepts revision, token, reason, primary_group and editable fields. POST `/{id}/change-preview` accepts `{action,revision,changes}` (disable/enable/delete/restore/update). DELETE `/{id}` and POST `/{id}/disable|enable|restore` accept `{token,revision,reason}`. PATCH `/{id}/expiry|password-policy` requires revision/token/reason plus fields. POST `/{id}/password` requires revision/token/reason/password/require_password_change. GET `/{id}/activity` returns `{processes,sessions,scheduled,coverage}`.

GET/POST `/system-groups`, PATCH/DELETE `/{id}` use `{name,gid,members,protected,managed,revision}`. Destructive edits require change preview token. No sensitive group grants, UID/GID edits, user hard deletion, arbitrary path reads or shell execution.

GET `/storage`: `{filesystems:[{id,path,fstype,total,available,quota_supported,quota_enabled,error}],users:[{account_id,username,home_bytes,data_bytes,files,collected_at,status}],shares:[],alerts:[],collected_at}`. GET/PATCH `/system-users/{id}/quotas` array/config `{filesystem_id,soft_bytes,hard_bytes,soft_inodes,hard_inodes,grace_seconds,status,error}`; unsupported updates fail explicitly. GET `/login-events` returns `{items,total,coverage}` filtering username,ip,result,since,until,page,page_size; event fields id,username,account_id,time,ip,method,result,fingerprint.

GET/POST `/shares`, PATCH `/{id}`: `{id,name,path,reader_group,writer_group,notes,status,revision,usage_bytes}`; POST `/{id}/change-preview` returns scope token; updates require token and revision. Shared files never automatically deleted.

GET `/audit-logs` returns `{items,total}` with fields `id,time,actor,action,target,before,after,result,reason`, filters action,actor,result,since,until,page,page_size.

Agent wire protocol: 4-byte network-order length then UTF-8 JSON (max 1 MiB); request `{version:1,method,params}`; reply `{version:1,result}` or `{version:1,error:{code,message}}`. Sync `AgentClient.call(method,params)` interface; Unix SO_PEERCRED restricted to configured API UID/root. `snapshot` returns `{gpus:[],tasks:[],accounts:[],system_groups:[],collected_at,source,stale,capabilities,errors}`; host mode `source=host`, demo `source=demo`. Stateful demo explicitly changes only its own SQLite state. Production mutations disabled until root config `allow_mutations=true` and methods validated.

Agent task RPC: apply_task_policy(task_id,policy,revision), apply_membership(action,...), preview_termination(task_id,identity?), execute_termination(token,reason,idempotency_key,actor), job_status(id), audit_since(cursor). Account RPC: list_accounts, list_system_groups, preview_account_change(action,id,revision,changes), execute_account_change(action,id,token,revision,changes,actor), preview_group_change/execute_group_change. Other RPC: account_activity(id), storage_snapshot, login_events_since(filters), preview_quota(id,policy), apply_quota(id,policy,token,reason,actor), preview_share_change/execute_share_change, list_shares, configure(settings). Agent implementation exposes `AgentService.call(method,params)` and CLI `python -m gpupm.agent.main --config PATH`. API uses demo AgentService in-process only for explicit demo mode, Unix client in host mode.

Scope not yet implemented must return a named error or unavailable state; never pretend a host operation succeeded. Frontend must not invent successful operations.

## Confirmed operation extensions

Account PATCH accepts validated reason, token and managed:true for explicit adoption. All account updates use action:update preview with the same nonsecret changes; group_id/priority are validated by API before host changes and excluded from host scope. POST /system-users/{id}/password requires {revision,token,reason,password,require_password_change}; its preview contains only require_password_change, never password. Invalid request responses omit all raw inputs and follow the detail code/message envelope.

POST /system-users/{id}/quotas/preview accepts the desired QuotaInput and returns token, expires_at, actual current UID/filesystem usage, proposed limits and impact. PATCH quotas requires the same policy plus token/reason. GET quotas includes used_bytes/used_inodes if readback succeeds; an error or incomplete row must disable editing, not default old limits to zero.

POST /shares/change-preview {action:create,changes:{name,reader_group,writer_group,notes}} precedes initial POST /shares {same fields,token,reason}. Registered share updates use their change-preview and validated revision/token/reason; unchanged name may be included but online project/path rename is rejected.

Agent heartbeat {policy_versions,settings} confirms exact persisted policy revisions; API emits it independently of browser activity. audit_since {cursor,limit} returns {items,cursor,has_more}; imported events retain original execution time. storage_snapshot includes capabilities.acl {status,message}, distinguishing missing tools from an actually unverified or verified filesystem state. Task final status is finished, not terminated.


Account RPC routing id remains UID; lifecycle_id is the generation key for business profiles. Observed absence or username/home drift archives the previous management state, marks identity_conflict and refuses re-adoption until root reconciliation. Authorized rename retains the generation UUID. Identical native delete/recreate entirely between observed scans cannot be distinguished.

Storage RPC serves cache or status:pending with collected_at:null; recursive collection runs outside the process authority lock. GUI polls while collecting. Alerts carry scope/target/metric/severity/percent/used/limit/basis/message and emit severity/resolution transitions. Quota grace_seconds is optional: omission preserves existing timestamps; explicit values update current overage only, future overages use filesystem defaults.

apply_task_policy returns awaiting_sync with no confirmed revision. Only the exact revision heartbeat after API persistence enables automatic handling; a previous heartbeat cannot authorize a new policy. Native protection always remains visible even if requested Web policy clears it. Runtime settings affect the process/storage cycle and future termination jobs; policy freshness is max(root limit, 3 × configured scan interval), default 30 seconds.

Process context contains observed ancestors up to32 levels, never signal targets. D-state members expose uninterruptible_since/uninterruptible_seconds; a30-second sustained condition is informational only. Account previews include current activity, paths and native-operation impact. Primary-group changes use native usermod rules, which may update old-group-owned home files; other data paths retain ownership.


## human 范围

GET /api/tasks、/api/system-users、/api/users 支持 scope=human|other|all，默认 human；独立账号/任务详情仍可查看 other。账号、任务与业务用户响应包含 is_human。GPU/总览统计仍包括全部任务。非 human 修改返回403/non_human_readonly；human 组自身只读，普通账号编辑保留 human 附属组。成员资格由 agent 读取原生 Linux 组，操作与后台执行时重新核验，不相信客户端字段。

界面任务列表默认附加 status=running，只展示运行中的人员账号任务；管理员可切换状态或清除状态筛选。API 未提供 status 时仍返回全部状态，GPU 总量与历史查询口径不变。界面分类名称为“人员账号／其他账号”，底层 human 组和 scope 参数不变。
