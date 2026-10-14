# Ubuntu 部署与运维

## 模式和权限

默认 `host` 模式，agent 未连接时显示不可用，不回退到演示。`demo` 模式明确标记并仅操作自己的数据库。Web 管理员密码通过 `gpupm admin-add` 交互创建，不能使用 SSH 密码或预置生产密码。

API 使用普通系统账号 gpupm。agent 必须为 Linux root，代码、venv、配置与 systemd unit 由 root 拥有，普通账号不得写入。agent 仅监听 Unix socket，权限 0660 并检查 SO_PEERCRED；其父目录允许 API 遍历。HTTP 初始绑定 127.0.0.1:8000。

## 安装步骤

1. 在开发机执行后端全部测试、React 测试/类型检查/构建及 E2E。记录 Git 版本。
2. 在 Ubuntu 安装 Python 3.12、venv、uv（或使用锁定依赖导出），以及实际功能所需的 quota、xfsprogs、acl、libpwquality。安装过程不修改用户训练 Conda 环境。
3. 使用系统账号工具创建 gpupm 服务账号（无普通登录、无 sudo），不通过 Web 授予敏感组。
4. 发布到 `/opt/gpupm/releases/<版本>`，root 拥有并禁止组/其他用户写入；建立该发布专属 `.venv`，安装锁定依赖。`/opt/gpupm/current` 由 root 指向发布版本。
5. 创建 `/var/lib/gpupm/api`（gpupm 拥有，0700）、`/var/lib/gpupm/agent`（root 拥有，0700）、`/etc/gpupm`（root 拥有）、`/run/gpupm`。
6. 明确 `/home` 与数据卷实际位置。私人目录直接 `<data_base>/<用户名>`；共享为 `<data_base>/shared/<项目>`。不能把未挂载的数据盘路径当作可用数据卷。先确保 home/data/shared 根已存在、root 拥有且普通用户不可修改目录项。
7. 以 root 生成配置（下列用户名、UID 和目录必须替换为实机核验值）：

```bash
/opt/gpupm/current/backend/.venv/bin/gpupm init-config \
  --path /etc/gpupm/agent.json \
  --api-uid <gpupm-UID> \
  --data-base <数据卷实际根> \
  --maintenance-user <维护SSH账号>
```

配置默认 `allow_mutations:false`。初始化自动记录 home_dev_id/data_dev_id，创建账号时核对目录设备是否变化；也可额外指定 home_device/data_device 的设备路径，不得把维护账号遗漏。服务启动不自动创建用户或改变文件系统。

8. 在 API 账号下运行 Alembic 迁移与管理员初始化：

```bash
cd /opt/gpupm/current/backend
sudo -u gpupm env GPUPM_DATABASE=/var/lib/gpupm/api/app.db .venv/bin/alembic upgrade head
sudo -u gpupm env GPUPM_DATABASE=/var/lib/gpupm/api/app.db .venv/bin/gpupm admin-add --username admin
```

API 使用自定义目录时，在 `/etc/gpupm/api.env` 设置与 agent 相同的 `GPUPM_HOME_BASE`、`GPUPM_DATA_BASE`，保证界面显示的初始化目录一致。

9. 安装 `deploy/systemd/` 中两个 unit，daemon-reload，先启动 agent 再启动 API。只读检查设备、进程、账号、日志、存储能力，确认与 nvidia-smi/系统事实一致。
10. 写操作先在专用测试账号/测试进程及隔离配额文件系统中验收。完成后才将 root 配置 `allow_mutations` 改为 true 并重启 agent。生产用户软删除保留账号及文件，不调用 userdel；结束 GPU 任务另走预览流程。

## 访问

```bash
ssh -L 8000:127.0.0.1:8000 wzx-ubuntu
```

浏览器访问 `http://127.0.0.1:8000`。内网多人使用时部署 HTTPS 反向代理，并在 `/etc/gpupm/api.env` 设置 `GPUPM_SECURE_COOKIE=1`。参考 `deploy/nginx/gpupm.conf.example`。API 后端端口不直接公开，代理保留 Host，cookie 和 Origin 校验保持同源。

## 登录和账号状态

密码与 SSH 公钥同时支持，但有效 SSH/PAM 配置可能限制其中一种。初始化报告必须实测两条路径，不能只验证 passwd/shadow 字段。首次改密默认开启；公钥交互登录、非交互 SSH、SFTP 可能受密码过期/PAM 状态限制，改密前需明确提示。

停用、账号到期、软删除分别保存。启用仅撤销停用，恢复仅撤销软删除，不能解除其他限制或外部管理员限制。软删除不自动停止进程、会话、crontab、用户服务，文件原位置/内容/属主/权限保持不变。

## 改名失败恢复

账号改名要求无活动进程、会话和已发现的计划任务；改名过程中先暂停新登录。若暂停后出现失败，账号标记 recovery_required，Web 禁止继续修改，后台不会自动解除登录限制。

由服务器 root 管理员处理：停止 agent 并备份两库，核对审计、getent 账号名/UID/GID/主目录、旧新目录的实际位置/属主、~/data 链接及登录限制。保留所有文件，依据已完成步骤修复到一个一致状态，核对账号生命周期和目录锚点后才清除 agent 状态中的 rename_recovery_required。重新启动只读核验，再恢复写能力；不能只清标记或以删除重建账号代替恢复。

## 配额、私人目录和共享

目录扫描用量与 UID/文件系统 quota 用量口径不同，同一个文件系统上的 home/data 不能当成两份独立用户 quota。0 限额为不限额，容量/inode 超限可能导致写入失败。变更先核对实际用量与预览，不能自动删文件解决超限。

宽限期留空保留已有期限；填写仅调整当前已经超软限额的用户期限。将来首次超限采用文件系统的原生统一宽限期，软件不修改全卷默认值。

quota 的启用取决于 ext4/XFS 功能与挂载状态。不支持时只显示统计和明确错误；软件不自动格式化、重挂载或重启生产卷。使用隔离 VM/测试 loopback 文件系统验证硬限额、inode、宽限和读回，不把生产分区填满。

私人目录默认0700、umask077；用户可主动改变自己文件权限，这不是容器隔离。共享 root 根下的 reader/writer 组与 default ACL 必须实测有效 mask、新文件继承及0600创建限制。撤销成员不撤销旧进程的组凭据或已打开句柄，需重新登录/检查活动；不会自动结束用户会话。

## 备份和升级

使用 SQLite Backup API，不能仅复制活跃 WAL 的主 `.db` 文件：

```bash
python scripts/backup.py /var/lib/gpupm/api/app.db /安全备份目录/app-时间.db
sudo python scripts/backup.py /var/lib/gpupm/agent/agent.db /安全备份目录/agent-时间.db
```

目的地必须是新文件，备份权限0600。两库一致性恢复应先暂停新操作/服务并备份，两份备份与版本一并记录。

升级先备份、暂停新的自动操作、安装新 release、迁移、重启、只读核验和策略对账，最后恢复写能力。旧代码不直接读取新 schema；需要回滚时使用迁移前数据库与匹配代码。服务停机不结束训练，恢复自动终止前需要新鲜采集和 API 策略心跳确认。

## 运维检查

```bash
systemctl status gpupm-api gpupm-agent --no-pager
journalctl -u gpupm-agent -u gpupm-api --since today
curl -fsS http://127.0.0.1:8000/api/health
```

检查 agent 心跳、采样时间、策略 applied/pending/failed、数据库可写性、数据卷身份与 quota/ACL 能力、SSH日志覆盖。异常时禁止报告操作成功；不自动 reset GPU，也不按低利用率杀任务。
