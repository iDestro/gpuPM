# server201 部署

2026-10-26（Asia/Shanghai），用户更正目标后，将本轮同一工作区发布部署到 server201（10.52.52.201）。server204 实例暂保留，未停止或删除。

- SSH 管理员：sc5tadm；维护保护包含 root 与 sc5tadm。
- Rocky Linux 10.1，系统 Python 3.12.12，独立应用 venv；8 张 NVIDIA H800。
- 发布目录：`/opt/gpupm/releases/20261026-workspace`，入口 `/opt/gpupm/current`。
- systemd：`gpupm-agent`、`gpupm-api`，active/enabled。API 使用独立无登录账号 gpupm。
- 仅监听 `127.0.0.1:8000`；本机隧道入口 http://127.0.0.1:18201 。
- 重建隧道：`ssh -N -L 127.0.0.1:18201:127.0.0.1:8000 sc5tadm@10.52.52.201`。
- Web 用户 admin，独立随机密码存于服务器 `/root/gpupm-admin-credentials.txt`，0600；通过 SSH 执行 `sudo cat /root/gpupm-admin-credentials.txt` 获取。
- 配置：`/etc/gpupm/agent.json`、`/etc/gpupm/api.env`。原生写操作关闭，allow_mutations=false。
- `/var/lib` 是服务器已有软链接；使用真实路径 `/opt/data/varlib/gpupm` 保存 API/agent 数据库，数据根暂设其下 `data`；home 根 `/home`。没有迁移用户数据或更改服务器软链接。
- 安装 acl（包管理器同时升级 libacl）；未修改现有账号组、挂载或训练环境，未重启服务器。

## 验证

健康检查 host/agent ok，root_readiness ready，mutations false。匿名 GPU 接口 401；管理员登录、首页、GPU、全部任务、全部账号、存储和系统组接口 200。GPU 快照包含 8 张卡且 stale=false。实机浏览器登录与总览显示真实服务器、系统只读、8 张 H800。

复用本轮已构建和测试的同一发布包；未重复全量测试。此前后端 391 passed / 2 skipped、ruff 和前端构建通过；前端 119 passed / 8 timeout、E2E 22 passed / 3 failed，详见 SERVER204_DEPLOYMENT.md。此次未修改应用代码。

Rocky Linux 原生账号写入、SSH/PAM、共享授权、任务终止未验收，保持禁用；没有 human 组，现有账号和任务应从其他/全部范围查看。

## 运维

`sudo systemctl status gpupm-agent gpupm-api --no-pager`

`sudo journalctl -u gpupm-agent -u gpupm-api -n 80 --no-pager`

停止并取消开机启动（保留数据）：`sudo systemctl disable --now gpupm-api gpupm-agent`。

## 2026-10-26 用户授权开启写权限与不限时

已按用户要求将 root agent `allow_mutations` 设为 true。全局 `default_max_runtime_seconds=null`，当时 7 个未结束任务的运行时长与绝对截止时间均清空；已结束任务历史不改。无个人/组时长覆盖，无 API 任务覆盖，无待执行终止作业，无纳管账号自动限制待执行。

停 API/agent 后通过 SQLite Backup API 保存两库及配置：`/opt/data/varlib/gpupm/backup-unlimited-20261026T054325Z`，另含 changes.json。更新 API/agent 两侧策略并清除过期预览后启动服务，没有终止训练或重启服务器。API 审计记录 settings.unlimited-runtime。

验证 health mutations=true、agent=ok、root_readiness.ready=true；登录后 settings 默认时长为空；agent 当前全部 7 个未结束任务不限时且 overdue=false，jobs=0。仅修改此实例配置，代码中的新安装默认值未改变。维护账号与 human 管理范围保护继续有效。未执行账号创建/停用或任务终止等破坏性验收。
