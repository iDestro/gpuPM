# wzx-ubuntu 试用部署

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
