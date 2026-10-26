# wzx-ubuntu 试用部署

> 当前验收结论见 [ACCEPTANCE_STATUS.md](ACCEPTANCE_STATUS.md)。本文件保留历史记录；早期待办和失败应结合后续结果阅读。

2026-10-14 已启用，后端功能基于 f3ce9bd，前端为当前 dashboard 整改版本。三个 systemd 服务已设为开机启动：gpupm-trial-agent、gpupm-trial-api、gpupm-trial-demo。普通 Web 服务使用独立无登录系统账号 gpupm-trial；root agent 配置 allow_mutations=false。

- 真实服务器：127.0.0.1:18000，显示 host 来源；读取真实 GPU、任务及账号。原生账号/文件/配额/任务终止操作被禁止。业务备注、优先级等 Web 元数据可以保存。
- 演示环境：127.0.0.1:18001，显示 demo 来源；修改仅作用于独立演示数据库。
- 服务代码与 venv：/opt/gpupm-qa；状态库和配置：/var/lib/gpupm-trial；socket：/run/gpupm-trial/agent.sock。
- 受控 home 根为 /var/lib/gpupm-qa/home，data 根为 /var/lib/gpupm-qa/data；仍读取所有真实本地账号，尚未初始化生产 /data。
- Web 管理员为 admin，随机密码单独交付，不写入仓库，不复用 SSH 密码。

本机已建立 SSH 隧道。断开后重新建立：

```bash
ssh -N -L 127.0.0.1:18000:127.0.0.1:18000 -L 127.0.0.1:18001:127.0.0.1:18001 wzx-ubuntu
```

打开 http://127.0.0.1:18000 或 http://127.0.0.1:18001。端口不直接对外开放，传输通过 SSH 加密。

验收：两个入口 HTTP 健康检查、匿名阻断、管理员登录、来源与新鲜任务快照、账号列表、存储接口及 SPA 页面均通过；三服务 active。已有 GPU PID 4938、2374928 保持运行。

运维：

```bash
ssh wzx-ubuntu 'systemctl status gpupm-trial-agent gpupm-trial-api gpupm-trial-demo --no-pager'
ssh wzx-ubuntu 'journalctl -u gpupm-trial-api -u gpupm-trial-agent --since today'
```

停止试用保留数据库和文件：sudo systemctl disable --now gpupm-trial-demo gpupm-trial-api gpupm-trial-agent。正式部署另按 DEPLOYMENT.md 核对数据卷和生产权限。


human 分类更新：真实账号 wuzhaoxiang、luwangxing、dingpeixuan 以及原有14个 gpupmqa_ QA 账号加入 human（GID1025）。未变更其他组、账号登录限制、文件权限或已有进程凭据。Web 默认展示 human；其他账号/任务仅供查看。维护账号和系统进程原有保护保留。


本轮已更新后端与前端并重启三个试用服务。更新前一致备份位于 /var/lib/gpupm-trial/backup-human-1791956706079320318。最新浏览器包 index-DaLEnkAM.js；账号和密码保持不变。新增 QA 改名验收账号也自动加入 human，因此本轮 HTTP 验证共18个 human 账号。scope human/other/all、root 业务修改403、host/demo 来源与新鲜任务快照均通过。实际当前 GPU 占用账号均为 human，其他任务列表为空属于正常结果。

任务页默认“人员账号＋运行中”，可切换已结束/超时/异常或清除状态筛选。分类文案改为“人员账号／其他账号”，底层 human 组及权限边界保持一致。最新前端27项、Chrome4条流程和构建通过，两个试用入口均已提供新包。


## QA 管理记录迁移修复

用户截图暴露试用部署遗漏迁移：15个由QA agent创建且已软删除的账号，在试用库中被误显示为未管理/1970到期。已核对用户名、UID、主/数据目录锚点、原/目标身份观察、human成员、属主/0700权限、数据链接后，将这些账号管理元数据及同源私人组标记导入试用agent库；保留目标生命周期ID及API业务策略，不重建Linux账号。

15个软删除状态和1个独立停用状态全部保留；真实passwd/shadow及目录属性前后完全一致。配置home根同步为QA home，写能力仍关闭。操作前备份：/var/lib/gpupm-trial/backup-account-import-1791957944791821304。

HTTP验收：默认人员列表仅原有3人；已软删除筛选15人全部managed=true。截图账号gpupmqa_rod366be、gpupmqa_otherd366be均managed=true/status=deleted/有效期为空，不再出现1970日期。三个试用服务active。查看这些QA账号请选择“已软删除”或“全部状态”。


## 浅色 dashboard 整改

按用户选择改为浅色简洁布局。桌面侧栏/顶栏固定，主内容独立滚动，短屏菜单独立滚动；手机导航改为抽屉。表格固定列宽、长值省略且悬停/聚焦可查看完整内容，审计展开保留原始字段，登录覆盖默认折叠。账号UID/GID作为副标题，登录策略进入详情；有效期展示实际生效日期。审计成功筛选匹配后端succeeded，普通界面采用“启用管理”。

已发布两个入口：JS index-DaLEnkAM.js，CSS index-BMV94eZ9.css。账号密码和root只读配置保持原设置。实机Chrome核对审计长列表滚动、账号页和375px手机导航；15个QA账号仍已管理/已软删除，未执行原生账号变更。

当前实机截图位于本机 .runtime/preview/dashboard-audit-native.png、dashboard-audit-scrolled-native.png、dashboard-accounts-native.png 和 dashboard-tasks-mobile-native.png（本地检查产物，不入版本库）。

## 编辑弹窗关闭修复

两个试用入口已发布修复：当前JS为index-D5esl8As.js，CSS仍为index-BMV94eZ9.css。共享编辑弹窗的未保存确认改用Modal.useModal，取消和右上角关闭均恢复；未修改直接关闭，已修改可继续编辑或放弃草稿。

35项前端测试和7条Chrome E2E通过。真实入口浏览器验证关闭流程成功，未发送任务PATCH，任务备注前后相同。仅更新静态文件，账号密码和服务配置保持原设置。

## 任务别名与原始名称

两个入口已更新后端及静态包：JS index-DFSSjdoH.js，CSS index-BMV94eZ9.css。列表悬停/聚焦显示原始名称，详情展示任务别名和原始名称，编辑只改变别名；既有别名保留。旧host记录依保留的进程信息恢复原名，无可恢复信息的历史记录显示未知。

更新前一致数据库备份：/var/lib/gpupm-trial/backup-alias-1791961557331455549。三个试用服务重启后active，root配置allow_mutations=false保持。Ubuntu120项后端测试、36项前端测试和7条Chrome E2E通过；两个入口实机浏览器hover/详情/编辑字段验证通过，未保存任务配置或修改原生进程。

## 最大运行时间输入优化

两入口已发布JS index-Bikwy7RG.js，CSS仍index-BMV94eZ9.css。任务及全局默认最大时长可按时/分/秒填写或快捷设置，留空/不限时仍发送null；后台计时、到期动作和原生只读配置保持。编辑弹窗限制高度并内部滚动，小屏幕标题/关闭按钮可见。

43项前端测试、7条Chrome E2E和构建通过。两个实机入口核验新包、快捷/校验和手机可视布局，全程未发送PATCH，现有任务时限未改变。只更新静态文件，无后端重启或配置迁移。

## 任务仅设置最大运行时间

两入口已发布JS index-BAh3lI_X.js，CSS仍index-BMV94eZ9.css。编辑任务仅保留最大运行时间；详情显示只读预计结束时间。新版任务保存会清除旧expires_at，不自动修改未保存的历史任务，后端兼容字段保留。

44项前端测试、7条Chrome E2E和构建通过；两个入口实机无指定到期时间输入，任务时限字段前后保持，PATCH请求0。仅更新静态包，无服务重启或数据库迁移。

## 全平台中英文国际化

两入口已发布JS index-BEG-WmO3.js、CSS index-B4IT83SE.css。登录及右上角可切换中文/English，浏览器记忆选择。全平台固定界面、AntD、弹窗、状态/已知错误和显示日期随语言切换，时间保持Asia/Shanghai。中文策略/必要技术字段悬停展示专业英文，支持聚焦；配置页字段与只读目录说明可读化，竖向布局避免英文长路径挤压说明。

57项前端测试、10条Chrome E2E和类型/构建通过，最终设置布局2项专项回归通过。两个入口实机语言记忆、术语、英文弹窗/保留草稿、任务原名和375px导航验证通过；策略值前后相同，未保存任务或策略，原生只读配置保持。只更新静态文件，无后端重启、数据库或账号迁移。账号/任务名称、命令、路径及原始日志/诊断不做自动翻译。

## 新任务默认策略

两个入口已更新后端及静态包：JS index-DPvPCK8m.js，CSS index-B4IT83SE.css。策略配置提供新任务默认最大运行时间30分钟、人工保护关闭、优先级50、到期仅提醒、残留worker清理关闭，可自行调整。时限从进程启动计算；修改模板不回写已有任务，系统/服务/维护保护保持。

更新前一致SQLite备份：/var/lib/gpupm-trial/backup-task-defaults-1791967060465582027。三服务重启后active，allow_mutations=false保持。旧配置补缺保留原值；部署后仅通过全局设置API设定新模板，真实10个/演示2个既有任务逐项核对策略及身份保持，扫描/存储阈值和只读初始化配置未变。

Ubuntu171项后端测试、60项前端测试、11条Chrome E2E与构建通过；两入口实机中英文、术语、30分钟与开关/优先级回显、取消及375px弹窗验证通过，界面检查无配置或任务写入。未新增或终止真实GPU任务，账号密码保持。

## 收尾状态、残留提醒与手动清理

两入口已发布后端及静态包：JS index-CGFTJAhN.js，CSS index-B4IT83SE.css。任务新增收尾中/待清理/清理中，正常退出直接结束；默认列表为全部未结束的人员任务。任务/新任务模板提供残留提醒与等待时间，默认开启、5分钟；仅管理员预览并填写原因确认后清理，旧自动残留分支已移除，收尾worker不因超时自动终止。旧字段兼容保留，界面不再暴露自动残留清理开关。

一致SQLite备份：/var/lib/gpupm-trial/backup-manual-residual-1791969744993300585。三个服务active，allow_mutations=false保持；只通过设置API启用default_orphan_reminder=true/default_orphan_wait_seconds=300。已有任务名称/启动信息/优先级/保护/时限/到期策略/旧清理字段保持，缺少的新提醒字段补齐；部署后新发现任务按默认模板采集。演示环境仍为原2任务，浏览器测试独立fixture未进入试用数据库。

Ubuntu197项后端测试、68项前端测试、最终13条Chrome E2E及构建/类型检查通过。两入口实机中英/术语/5分钟与开关/取消/active筛选/375px检查通过，全程无任务终止或任务配置写入。账号密码、目录与存储阈值保持。范围变化导致部分清理时需重新预览；不对真实GPU训练进行终止验收。

## 任务监控程序白名单

两入口已发布后端与JS index-C13Kd90C.js，CSS index-B4IT83SE.css保持。新增任务监控白名单，初始/usr/lib/xorg/Xorg、/usr/bin/Xorg；通过策略配置编辑精确完整程序路径，[]取消排除。已有可核验Xorg记录退出任务监控；账号活动及GPU总占用继续统计，程序不会被停止。其余任务的名称/时限/优先级/保护/提醒策略保持。

一致SQLite备份：/var/lib/gpupm-trial/backup-executable-allowlist-1791973089903583844。三服务active，allow_mutations=false保持，无原生账号/进程写操作。实机Xorg PID4938、boot_id及start_ticks保持，真实任务API隐藏1记录，其余11任务保持；演示2任务保持。既有设置值不变，仅补缺省白名单；隐藏元数据、TaskConfig与审计保留。

Ubuntu228项后端、70项前端、14条Chrome E2E及构建/类型检查通过。两入口中英文、术语、375px标签编辑/放弃/取消验证通过，界面检查不保存测试草稿、不发送任务终止。已结束且无exe证据的旧记录保留，不根据别名误判；后续其他桌面程序可追加完整路径，不自动猜测ML/DL类别。

## 桌面侧栏折叠

两入口已发布JS index-DHb95AYv.js、CSS index-U2CkS405.css。左上角按钮切换224px/64px侧栏，图标模式悬停展示菜单名称，中英及键盘操作支持，浏览器记忆状态。手机继续完整导航抽屉，菜单/内容独立滚动与路由选择保持。

类型/构建及完整16条Chrome E2E通过；独立审查与两入口中英文、刷新、短屏/手机及无配置写入实机检查通过。只复制静态包，无服务重启或数据库/任务/账号/策略修改；既有原生只读配置保持。浏览器禁用存储时不保证刷新记忆。

## 侧栏图标语义整理

两入口已发布JS index-BCDfTyLE.js，CSS index-U2CkS405.css保持。更新6处图标，全部11项唯一：业务优先级排序、用户策略人物文档、存储硬盘、团队共享连接、SSH历史时钟、审计文档检索；其余5项保留。桌面展开/折叠和手机抽屉同步，原名称、路由、状态记忆及中英提示保持。

构建/类型检查与16条Chrome E2E通过，两入口实机菜单图标唯一性及桌面/短屏/手机显示核验通过。只更新静态包，无服务重启或任务/策略/账号数据修改。

## Linux 权限组管理

两入口已更新后端和静态包：JS index-DKygmK-L.js，CSS index-U2CkS405.css。侧栏及页面统一为 Linux 权限组，默认显示受管普通项目权限组；其他组只读查询，符合条件的已有普通组可经预览启用管理。账号私有主组在详情展示，human 保留只读人员分类用途。账号/共享目录授权只允许新选受管权限组；主组、成员及共享引用阻止删除。

一致 SQLite 备份：/var/lib/gpupm-trial/backup-permission-groups-1791990675779365912。三个服务 active，allow_mutations=false 保持。真实 109 个组按 3 个受管权限组和 106 个其他组展示；其中 15 个私有组保持只读。演示账号旧数据按实际同名/GID 补充私有主组字段，其余策略和成员保持。

Ubuntu 269 项后端通过；前端全量 77 项及补充后的 8 项权限组专项、17 条 Chrome 全流程、增强的权限组编辑及操作列可视回归、构建和 Ruff 通过。两入口实机中英文、搜索、默认/其他视图和 375px 检查通过，写请求为 0、全局设置未变；真实 passwd/group 文件校验值与升级前相同。账号密码及端口保持原设置。

本机截图：.runtime/preview/permission-groups-managed-18000.png、permission-groups-other-18000.png、permission-groups-en-18000.png、permission-groups-mobile-18000.png；演示环境对应端口 18001。截图及检查脚本不入版本库。

### 2026-10-15 管理写权限已开启

按用户明确授权，将 `/var/lib/gpupm-trial/agent.json` 中 `allow_mutations` 改为 `true`，重启 `gpupm-trial-agent`。本节取代前文关于当前只读状态的说明；历史验证记录不变。维护保护名单仍为 `wuzhaoxiang`。配置备份：`/var/lib/gpupm-trial/agent.before-enable-writes-1791995726342960154.json`（root 0600）。

开启前只读核验：无待协调的受管账号登录限制，无运行中的未保护自动终止任务策略。开启后三服务 active，Web health 正常；未执行账号变更或任务终止，passwd/group 哈希不变。

已知接管条件：`luwangxing` 的实际主目录 `/home/luwangxing` 与当前 `home_base=/var/lib/gpupm-qa/home` 不匹配，且预期数据目录 `/var/lib/gpupm-qa/data/luwangxing` 不存在，因此该账号仍不能直接接管。尚未迁移文件、改变目录配置或创建其数据目录；正式目录规划需另行处理。

### 2026-10-15 手动验证账号

按用户授权通过 `/api/system-users` 创建 `gpu_trial`，UID 1018 / GID 1028，私有主组 `gpu_trial`、附属组 `human`，managed=true、is_human=true、protected=false，Shell `/bin/bash`。主目录 `/var/lib/gpupm-qa/home/gpu_trial`，数据目录 `/var/lib/gpupm-qa/data/gpu_trial`，均核验为 UID 1018 所有及 0700。临时密码通过平台专用密码接口设置，首次登录需改密；凭据不写入仓库。

实机创建暴露了初始化顺序错误：通用 Shell 更新提前解除 nologin，随后 apply_login 将其误判为外部策略修改。修复为 agent_restricted 时由 apply_login 在完整校验后统一恢复 Shell 与有效期；保留所有外部限制检查。新增创建全流程回归先复现错误再通过，Ubuntu 后端 270 项测试通过，Ruff 通过。已部署 accounts.py。

首次部分创建保持密码锁定和账号过期；停 agent 后校验该新账号的 UID、目录、基线密码匹配、过期值，恢复仅由本次流程提前改变的临时 Shell，再由 agent 自身恢复登录策略。之后通过平台预览及密码接口完成初始化，状态 active / login_policy_status=applied。备份 `/var/lib/gpupm-trial/backup-account-create-fix-1791996291703229197`。未修改既有用户，未代用户完成首次 SSH 改密登录。

## 2026-10-15 当前完善版本（存储卷方案待确认）

- 已更新真实版 18000 和演示版 18001；agent/API/demo 均 active，服务仍 enabled。保持 `allow_mutations=true` 和维护账号保护不变。
- 程序与四份数据库的一致性备份：`/var/lib/gpupm-trial/backup-readiness-1791998569834681088`。其中 `release-acceptance.json` 记录旧版→新版→旧版、备份恢复的隔离数据库验证，结果通过；本次并未回退实际 Linux 账号。
- Ubuntu 最终后端测试 319 项通过。最终前端静态资源 `index-CtDFA_t5.js` / `index-CDh1to1P.css`，构建通过。
- 真实/演示网页均通过详情链接、刷新、中英文、375px 手机布局检查；浏览器无 pageerror，检查阶段无业务写入。
- 本实例 ACL 验收通过 13 项：`/var/lib/gpupm-trial/native-acl-readiness-1791998569.json`。测试账号已软删除，文件和明确命名的 QA 共享项目保留；原有 `gpu_trial` 未修改。
- **存储仍未完成切换**：服务器只有一块系统盘，当前 `/` ext4 约 470GiB 可用，尚无 `/data`，用户配额未开启。正在等待专用文件卷、系统目录或新增磁盘的方案选择；未格式化、重新分区、重挂载根分区或迁移老账号目录。
- SSH 首次改密实机矩阵仍在排查验收脚本交互，不能根据早期失败报告宣称通过。

### 同轮 SSH 验收结论

SSH/PAM 最终 **24/24** 通过，报告 `/var/lib/gpupm-trial/native-ssh-readiness-v4-1791998569.json`；此前超时为验收脚本未识别服务器中文 PAM 提示，已经修正。当前剩余阻塞仅为数据卷方案选择与之后的实际配额配置/验收，不能把 ACL/SSH 通过视为数据卷已完成。

### 单实例启动顺序收尾

agent 现在在获得独占锁后才初始化数据库，避免重复启动先运行恢复逻辑。备份 `/var/lib/gpupm-trial/backup-singleton-1791999380667280977`，Ubuntu 相关3项测试和真实持锁检查通过。已部署并重启 agent，三项服务均 active。冻结前端源码后完整94项测试通过。存储方案仍待选择，目录与挂载未变更。

## 2026-10-15 09:18（Asia/Shanghai）系统盘数据目录已配置

用户确认直接使用系统盘 /data，配额需要根文件系统修改或重启时留待维护窗口。

- 当前新账号路径：`/home/<用户名>`、`/data/<用户名>`；共享根 `/data/shared`。根目录 root:root 0755，账号私有目录0700。API设置读取与agent配置一致。
- 稳定设备锚点 `/dev/disk/by-uuid/78832381-a1a2-47f1-aac0-de8a98a78a52`；agent 的systemd drop-in增加RequiresMountsFor，API drop-in同步目录环境变量。
- 备份 `/var/lib/gpupm-trial/backup-storage-roots-1792027081593693188`。已有账号信息与48个记录目录身份/权限保持原位；gpu_trial仍沿用原QA目录，不做迁移。
- 重启agent/API后健康检查通过；新根目录实际ACL13项、SSH/PAM/隔离24项通过。测试账号已软删除，文件保留。
- 未修改根文件系统特性、挂载参数或fstab，未分配文件卷，未重启整机。配额尚未启用且维护窗口尚未预约，详见 STORAGE_SETUP_PENDING.md 的现行配置和维护说明。

## 2026-10-15: remove disk quotas

Deployed user-requested removal of quota controls and enforcement APIs while retaining usage, capacity alerts and shared ACLs. Backup: `/var/lib/gpupm-trial/backup-remove-quotas-1792029699698874711`. Configuration, passwd/group and shared ACLs unchanged. Three services active; host/demo UI verified in both languages and mobile layout. No server reboot or filesystem adjustment. The previous quota maintenance window is cancelled; see [current acceptance](ACCEPTANCE_STATUS.md).

## 2026-10-15 存储/共享专项体验部署

新版存储与共享页面、严格ACL读回及失败处理已部署。主备份 `backup-storage-experience-1792031368302101701`，前端布局备份 `backup-storage-layout-1792031579317565714`，均在 `/var/lib/gpupm-trial/`。实际ACL13项和双入口桌面/手机宽度/中英文验证通过；未重启主机。详情见 [当前验收](ACCEPTANCE_STATUS.md)。

### 目录统计按需刷新（2026-10-15）

自动存储采集仅读取文件系统容量与 inode；页面 GET 不再发起目录遍历。管理员通过 POST /api/storage/refresh 手动刷新目录用量，沿用登录、CSRF 和操作审计。无需服务器重启或修改挂载配置。文件数展示与目录条目计数已移除。手动刷新仍有磁盘 I/O 成本。

### 共享目录按成员授权（2026-10-15）

已部署成员列表、只读/读写及移除授权；不再要求管理员选择 Linux 组。每个项目由后台维护专用组，组名/GID/所有权记录受保护。普通权限组及账号编辑不会改变这些内部授权。

最终备份 `/var/lib/gpupm-trial/backup-share-members-1792043343619963582`（此前备份 `backup-share-members-1792042755500700375`）。系统配置保持不变，原账号及共享 ACL 在部署期间不改动。原生验收报告 `/var/lib/gpupm-trial/native-share-members-20261015.json`：18 项通过、fixture 清理无错误，新增测试账号已软删除且保留文件。

旧共享目录只展示当前成员，不自动迁移；实际修改成员时经预览切换专用授权并保留旧组/子文件 ACL。旧存储路径的目录先核对路径，避免修改当前根下同名目录。

旧共享目录原位置管理已修复并部署：备份 `/var/lib/gpupm-trial/backup-legacy-share-path-1792047713238652439`。此前“旧存储路径需核对后修改授权”的一般性拦截已替换为安全父路径/root 所有权/无符号链接/device+inode 校验，符合检查的已登记旧目录可直接预览与授权。真实旧路径的 gpu_trial 预览已通过，未代用户确认执行。

### 2026-10-15 预览成功后误报修复

备份 `/var/lib/gpupm-trial/backup-preview-lifecycle-1792050164249694445`。修复前端成功后重放旧预览、完成后倒计时继续报过期；真实过期可在对话框重新预览并保留原因。演示共享预览增加与原生一致的 revision 校验。

真实服务器完整 UI 验收通过，超过原30秒有效期不再误报，QA 备注已恢复；原 gpu_trial 读写授权保持不变。前端104/后端345/Chrome20项通过。

2026-10-15 已部署共享目录只读成员弹窗，备份 `/var/lib/gpupm-trial/backup-members-modal-1792052118955065117`。项目名及查看按钮打开同一弹窗，关闭图标/按钮/Esc和真实服务中英文/手机宽度验证通过。仅更新前端静态资源，无需服务或服务器重启，无业务权限变更。

2026-10-15 GPU筛选修复已部署，完整源代码/静态资源/四个SQLite数据库备份 `/var/lib/gpupm-trial/backup-task-filters-1792055678417087879`，兼容演练及真实/演示健康检查通过。服务更新无需服务器重启。真实gpu_trial的30秒CUDA测试结束后按设备筛选仍可查看，旧记录无设备历史时保留未知。账号、权限组及共享ACL不变。

最终前端补充详情页已结束任务禁用终止，静态资源备份 `/var/lib/gpupm-trial/backup-task-filters-final-1792056267051042639`。

2026-10-15 已部署结束计时冻结及systemd已确认服务leader到期终止修复。完整备份`/var/lib/gpupm-trial/backup-task-deadline-1792064341965209486`；兼容演练通过，无服务器重启。真实30秒策略测试在约33秒由平台SIGTERM正常退出，早于120秒systemd兜底，平台policy审计确认同PID signal/exited。结束后计时稳定，缺少结束记录的旧任务显示未知；到期检查仍有当前5秒采集周期及退出宽限的延迟。

2026-10-16 显示名称去掉Linux前缀：本地账号/权限组（Local accounts/Permission groups），同步侧栏、页头和创建账号弹窗。仅更新静态资源，无需重启；备份`/var/lib/gpupm-trial/backup-navigation-names-1792113891444689651`。

## 2026-10-16 用户组策略整合部署

- wzx-ubuntu / 10.30.75.43，真实应用通过本机隧道 `http://127.0.0.1:18000` 访问；新入口 `/groups`，账号详情配置个人任务策略。
- 部署备份：`/var/lib/gpupm-trial/backup-user-task-groups-1792159662506603011`。包含 API/agent/demo 四个数据库、应用源代码、静态资源、root配置和发布验收结果。
- 新旧版本隔离数据库检查通过后更新 `/opt/gpupm-qa/backend/src` 和 `frontend/dist`；startup 幂等添加策略字段及内置组。三个 trial 服务均 active；宿主机 API health 为 agent=ok、mutations=true、root_readiness.ready=true。
- `/etc/passwd`、`/etc/group`、root agent.json 与 `/data/shared` 递归 ACL 前后逐字比较一致。未重启操作系统、未迁移任何目录。
- 旧 `/users` 重定向账号列表，旧 `/system-groups` 重定向统一用户组；原生系统权限高级页 `/advanced/system-groups` 从账号详情进入。
- 服务器浏览器只读验收中英文、组页面、gpu_trial配置弹窗、维护账号保护、窄屏布局、取消与旧链接通过。25个人员任务快照核验通过；未修改真实用户策略作为验收数据。
- 回滚需停三服务后同时恢复上述备份的代码和四个数据库，再按原UID/GID恢复文件权限并启动；旧版本虽能读取新增列，但无法解释新的用户组继承语义，禁止仅回滚代码。

## 2026-10-17 组管理入口与批量任务分组

- 已更新 wzx-ubuntu 的 API/root agent/demo 与前端，三服务 active，agent health ok；无需服务器重启，无新增数据库 schema。
- 备份：`/var/lib/gpupm-trial/backup-group-management-1792202362516741153`（代码、前端、四个数据库、配置与发布演练结果）。沿用备份演练和失败自动回滚脚本；回滚保持代码和数据库成对恢复。
- 前后 `/etc/passwd`、`/etc/group`、root 配置和 `/data/shared` ACL 完全一致。
- `/groups` 为任务策略组；`/system-groups` 为系统用户组；旧 `/advanced/system-groups` 跳转后者。
- 新接口 `POST /api/groups/{id}/members`：`members: [{uid, group_id}]`，其中 group_id 为预期原分组；管理员认证和 CSRF 沿用现有机制，最多 200 个不重复成员，一次事务审计提交。
- 实机浏览器中文/英文/窄屏验收通过。保持原 SSH 转发入口 `http://127.0.0.1:18000`。

### 2026-10-17 系统用户组成员体验更新

仅部署前端 assets 与入口 HTML；先复制资产，再原子替换 index，未重启任何服务。
备份：`/var/lib/gpupm-trial/backup-system-group-members-1792203594097505534/dist`。
已验证 HTTP 入口与新构建一致、实机成员弹窗及中英文/手机布局正常。回滚可恢复备份 index.html（旧 hash 资产保留），无需数据库回滚。

## 2026-10-17 Reliability fixes

- Full backup: `/var/lib/gpupm-trial/backup-reliability-1792205502893041187` (code, frontend, four databases, root config and release rehearsal report). Three application services restarted after successful isolated new/old-code rehearsal; no OS restart or new schema.
- Six fixes: large snapshot transfer, failed task-policy reconciliation, pending-write modal guards, conflict draft recovery, legacy account-policy eligibility, allocated directory usage. No new product features.
- All services active; API agent=ok, mutations=true, root_readiness.ready=true. `/etc/passwd`, `/etc/group`, root config and recursive `/data/shared` ACL unchanged.
- Installed transport verified with 4,000 long-name tasks over a private temporary socket. Live zh/en, 375px, account policy, system-group members and storage text checks passed. URL remains `http://127.0.0.1:18000`.
- Cached directory measurements require manual refresh to adopt allocated-block accounting. Snapshot assembly retains a 64 MiB cap; larger deployments require incremental synchronization.
- Rollback: stop application services, restore this backup's code AND four databases together, restore original UID/GID/modes, then start services. No live GPU termination or native permission mutation tests.
