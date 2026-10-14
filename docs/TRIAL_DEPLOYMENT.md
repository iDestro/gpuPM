# wzx-ubuntu 试用部署

2026-10-14 已启用，后端功能基于 f3ce9bd，前端基于 edcfd49。三个 systemd 服务已设为开机启动：gpupm-trial-agent、gpupm-trial-api、gpupm-trial-demo。普通 Web 服务使用独立无登录系统账号 gpupm-trial；root agent 配置 allow_mutations=false。

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


本轮已更新后端与前端并重启三个试用服务。更新前一致备份位于 /var/lib/gpupm-trial/backup-human-1791956706079320318。最新浏览器包 index-Du-YVC4A.js；账号和密码保持不变。新增 QA 改名验收账号也自动加入 human，因此本轮 HTTP 验证共18个 human 账号。scope human/other/all、root 业务修改403、host/demo 来源与新鲜任务快照均通过。实际当前 GPU 占用账号均为 human，其他任务列表为空属于正常结果。

任务页默认“人员账号＋运行中”，可切换已结束/超时/异常或清除状态筛选。分类文案改为“人员账号／其他账号”，底层 human 组及权限边界保持一致。最新前端27项、Chrome4条流程和构建通过，两个试用入口均已提供新包。


## QA 管理记录迁移修复

用户截图暴露试用部署遗漏迁移：15个由QA agent创建且已软删除的账号，在试用库中被误显示为未管理/1970到期。已核对用户名、UID、主/数据目录锚点、原/目标身份观察、human成员、属主/0700权限、数据链接后，将这些账号管理元数据及同源私人组标记导入试用agent库；保留目标生命周期ID及API业务策略，不重建Linux账号。

15个软删除状态和1个独立停用状态全部保留；真实passwd/shadow及目录属性前后完全一致。配置home根同步为QA home，写能力仍关闭。操作前备份：/var/lib/gpupm-trial/backup-account-import-1791957944791821304。

HTTP验收：默认人员列表仅原有3人；已软删除筛选15人全部managed=true。截图账号gpupmqa_rod366be、gpupmqa_otherd366be均managed=true/status=deleted/有效期为空，不再出现1970日期。三个试用服务active。查看这些QA账号请选择“已软删除”或“全部状态”。
