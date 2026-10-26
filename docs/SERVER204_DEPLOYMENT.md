# server204 部署

2026-10-26（Asia/Shanghai），部署当前工作区（基础提交 4471c2fe，含未提交改动）。

- SSH：server204，10.52.52.204，root；使用现有 SSH 密钥。
- CentOS 8，独立 Python 3.12.15：`/opt/gpupm/python`；未修改系统 Python 或训练环境。
- 发布：`/opt/gpupm/releases/20261026-workspace`，入口 `/opt/gpupm/current`。
- systemd：`gpupm-agent`、`gpupm-api`，已启用开机自启。API 使用无登录账号 gpupm，agent 使用 root。
- API 仅监听 `127.0.0.1:8000`。本机隧道：`ssh -N -L 127.0.0.1:18204:127.0.0.1:8000 server204`，访问 http://127.0.0.1:18204 。
- Web 用户：admin；随机独立密码保存在服务器 `/root/gpupm-admin-credentials.txt`（0600），不入仓库。
- 配置 `/etc/gpupm/agent.json`、`/etc/gpupm/api.env`；状态 `/var/lib/gpupm/api/app.db`、`/var/lib/gpupm/agent/agent.db`。
- 原生写操作关闭（allow_mutations=false）；维护账号 root。目录暂设 `/home` 与 `/var/lib/gpupm/data`，后者只为只读部署建立独立空目录，未迁移现有用户数据。
- 未创建 human 组或改变现有账号所属组；现有用户/任务在其他或全部范围查看。

## 验证与限制

两个服务 active/enabled，health 为 host/agent ok、root_readiness ready、mutations false。匿名访问 GPU 接口被拒绝；管理员登录、首页、4 张 H100 实时数据、全部任务、账号、存储和系统组读取返回 200。

本地后端 391 passed / 2 skipped，ruff 通过，前端类型检查与构建通过。前端降低并发重测 119 passed / 8 timeout；浏览器 E2E 22 passed / 3 failed（系统组成员选择、任务组策略修改及成员移动）。未在此次部署中修改应用代码修复这些失败。

CentOS 原生账号写入、SSH/PAM、共享授权及任务终止尚未验收，保持禁用。未重启服务器、修改挂载或终止训练。后续开放写操作前应完成 CentOS 专项验收和人员组/数据目录配置。

## 运维

```sh
ssh server204 'systemctl status gpupm-agent gpupm-api --no-pager'
ssh server204 'journalctl -u gpupm-agent -u gpupm-api -n 80 --no-pager'
ssh server204 'cat /root/gpupm-admin-credentials.txt'
```

停用应用保留数据：`systemctl disable --now gpupm-api gpupm-agent`。备份遵循 DEPLOYMENT.md 的 SQLite Backup API 流程。

实机浏览器登录及总览已验证，页面显示真实服务器、系统只读及四张 H100 的显存/利用率。已按 verification-before-completion 流程检查运行结果。
