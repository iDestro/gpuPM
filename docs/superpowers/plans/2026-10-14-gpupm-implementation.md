# gpuPM 第一版技术方案与实施计划

> 实施方式：按本计划逐项在当前会话执行；开始写业务代码前复核设计，使用 `superpowers:executing-plans` 执行检查点。任务清单使用复选框跟踪。本文件是待评审方案，本轮未开始实现、安装或部署。

**Goal:** 在 Ubuntu NVIDIA GPU 宿主机上部署管理员 Web 工具，管理已有 SSH/nohup/训练脚本启动的任务，并管理本地账号、系统组和隔离的个人目录，完整实现扩展后的 PRD 第一版。

**Architecture:** React 管理界面通过同源 FastAPI 接口访问数据；普通账号运行 Web API，root agent 通过本地 Unix socket 提供全用户采集、有限的进程管理及受控本地账号管理能力。SQLite 保存业务配置；agent 独立保存进程身份、关联证据、已应用策略和执行记录，确保重启后不会误用旧 PID。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、SQLAlchemy 2、Alembic、SQLite WAL、NVIDIA `nvidia-ml-py`、psutil、Linux pidfd、shadow-utils、libpwquality/PAM、quota-tools、XFS quota、POSIX ACL、journald/auth 日志；React、TypeScript、Vite、Ant Design、React Router、TanStack Query；pytest、Vitest、React Testing Library、Playwright；systemd，按访问方式选择 Nginx。

依据：[PRD](../../PRD.md)。计划日期：2026-10-14。

## 1. 已核验的项目与测试环境

### 1.1 项目现状

- 仓库当前只有 `docs/PRD.md`，没有应用代码，没有已有 Git 提交。
- 未发现适用于本项目的 `AGENTS.md`。
- 使用本机 SSH 配置中的 `wzx-ubuntu`；用户已确认别名。无需把 SSH 密码写入任何项目文件。

### 1.2 服务器只读探测结果

| 项目 | 实测结果 |
|---|---|
| SSH 账号 | `wuzhaoxiang`，已有 SSH 密钥可登录 |
| 系统 | Ubuntu 24.04.4 LTS |
| 内核 | 6.17.0-29-generic |
| Python | 3.12.3 |
| Node.js | 22.22.2 |
| systemd | 255 |
| 主目录所在文件系统 | `/home` 位于 `/dev/nvme0n1p2` 的 ext4 根文件系统，未从 mount options 观察到配额选项；需进一步核验实际配额状态 |
| 数据路径 | `/data` 尚不存在；初始化必须确认实际存储位置 |
| 配额/ACL 工具 | quota/setquota/repquota/xfs_quota/pwscore 未找到；getfacl/setfacl/chage/last/loginctl 已存在 |
| GPU | 1 张 NVIDIA GeForce RTX 2080 with Max-Q Design |
| 显存 | 8192 MiB |
| NVIDIA 驱动 | 535.309.01 |
| pidfd | Python 的 `os.pidfd_open`、`signal.pidfd_send_signal` 均可用 |
| 当前负载 | GPU 有在运行的计算进程；系统存在多个用户的进程和僵尸 |
| 系统 Python 依赖 | 未发现 psutil、pynvml、FastAPI、torch；不代表其他 Conda 环境没有 |
| sudo | 账号属于 sudo 组；`sudo -n true` 要求密码，尚未验证提权 |

此次探测没有安装软件、调整系统配置、读取进程环境变量或终止进程。现有训练与现有僵尸仅用于只读观察，不作为破坏性测试对象。

单卡服务器可以验证多数功能；跨卡合并只能在这里做模拟验收，真实多卡、MIG/MPS 和容器任务另列边界。

## 2. 技术路线选择

| 路线 | 好处 | 代价 | 结论 |
|---|---|---|---|
| **普通权限 API + root agent + React** | Web 与宿主机权限分开；独立重启和测试；支持全用户管理 | 增加一个本地 socket 协议及执行状态存储 | **推荐** |
| root FastAPI 单进程 + React | 初期文件和部署最少 | 网络服务直接拥有全用户终止权限；采集、期限和 HTTP 生命周期耦合 | 不作为正式版本 |
| Slurm/Kubernetes/DCGM 平台 | 适合统一提交任务、调度或大规模运维 | 改变用户运行方式；超出当前单机管理需求 | 不采用 |

### 2.1 推荐技术栈与职责

| 部分 | 选择 | 使用方式 |
|---|---|---|
| 服务语言 | Python 3.12 | 与已核验服务器一致；独立 venv，不改动用户 Conda 环境 |
| HTTP API | FastAPI + Pydantic | 参数校验、管理员鉴权、OpenAPI、业务接口 |
| 持久化 | SQLite + SQLAlchemy 2 + Alembic | 业务表、迁移；数据库放本地磁盘，开启 WAL、外键和 busy timeout |
| GPU 采集 | NVIDIA `nvidia-ml-py`，导入模块为 `pynvml` | 使用 NVML API，不依赖解析 `nvidia-smi` 表格；兼容驱动缺少可选接口 |
| 进程采集 | psutil + `/proc` | 用户、父子树、状态、启动时间；必要时读 start ticks/boot ID |
| 系统账号 | Ubuntu shadow-utils + Python 文件系统接口 | 固定工具路径、参数数组、禁止 shell 拼接；用户目录采用受限目录边界与不跟随链接的文件操作 |
| 账号生命周期 | shadow-utils + PAM/SSH 核验 | 独立停用、账号有效期、首次改密和软删除，组合限制不得互相覆盖 |
| 存储与共享 | quota-tools / XFS quota + getfacl/setfacl | 受支持本地文件系统的用户配额、后台统计、只读/读写共享目录 |
| 登录日志 | journald 或 Ubuntu auth 日志适配 | 受限读取、结构化事件、游标/轮转/重启去重；不承诺安装前历史完整 |
| 信号发送 | Linux pidfd | 绑定进程实例后发送 TERM/KILL，避免检查与发信号之间的 PID 复用 |
| 权限通信 | Python 标准库 Unix socket + JSON 帧 | 有限 RPC、超时、消息长度上限、协议版本、对端 UID 校验 |
| 前端 | React + TypeScript + Vite + Ant Design | 中文后台、表格、树、表单、弹窗；React Router 声明式路由管理页面 |
| 服务端数据状态 | TanStack Query + 原生 fetch | 请求去重、缓存、轮询和 mutation 成功后失效刷新；表单草稿独立于查询缓存 |
| 页面更新 | TanStack Query HTTP 轮询，默认 5 秒 | 隐藏标签页停止轮询；查询失败标注过期；终止 mutation 不自动重试 |
| 登录 | Argon2id 密码哈希 + 服务端会话 | HttpOnly Cookie、CSRF、过期和退出、登录限速；不提供注册 |
| 服务托管 | 两个 systemd unit | 独立启停 API 和 agent；agent 无公网 HTTP 端口 |
| 测试 | pytest + Vitest + React Testing Library + Playwright | 规则/接口/组件测试，以及 Ubuntu 真实进程与浏览器验收 |
| 开发检查 | Ruff、TypeScript 类型检查 | 锁文件固定实现时通过兼容测试的依赖版本 |

前端无需 SSR，第一版不引入 Redis、Celery、PostgreSQL、消息队列或 Prometheus。GPU 状态采用当前快照，不建设长期监控时序库。

Node 22 已存在，是否满足实现时所选 Vite 版本的具体要求，脚手架阶段再次确认。NVML 绑定也要在驱动 535 上做兼容实测，不能只依据最新版本号选依赖。

## 3. 系统边界与数据流

```text
浏览器
  │ 同源 HTTP；管理员会话；JSON API；5 秒轮询
  ▼
FastAPI（gpupm 普通系统账号，单 worker）
  ├── 静态前端 / web API / 登录 / 业务规则 / 审计查询
  ├── app.db：用户组、用户、任务配置、管理员、会话、业务审计
  └── Unix socket：/run/gpupm/agent.sock
        ▼
      agent（宿主机 root；无 TCP 监听）
        ├── NVML + psutil + /proc 采集
        ├── 任务关联证据 / 身份校验 / 期限扫描 / 信号执行 / 账号和目录操作
        └── agent.db：关系历史、策略版本、终止作业、账号作业、执行审计
```

两份 SQLite 的职责不同：API 是业务配置的唯一写入者；agent 是进程证据与执行状态的唯一写入者。API 不直接写 agent.db；agent 不执行来自可写业务数据库的 SQL、Python 或 shell。这样保留 root 执行结果而不让 Web 服务写 root 存储。

1. agent 每 5 秒采集一次 GPU 与全机轻量进程索引；只对相关进程补充命令、路径等较贵字段。
2. GPU 活跃 PID 是任务发现入口，父子进程索引用于找到 launcher 与辅助 worker。
3. API 从 agent 读取带 `snapshot_version`、`collected_at` 的快照，再附加管理组、优先级、备注。
4. 期限/保护/归组配置用版本化 RPC 应用到 agent；API 展示 `pending/applied/failed`，收到确认后才显示“已生效”。
5. agent 独立运行期限检查，执行操作前读取最新已应用版本。启动时先同 API 对账，完成新鲜采集与身份核验后才恢复自动终止。
6. agent 与 API 失联、策略尚未同步或采集过期时暂停新的自动终止并告警；进行中的已确认 TERM→KILL 作业继续按已记录的范围完成，除非收到取消/保护变更。
7. API 使用异步等待或线程池读取 socket；不让 NVML/procfs 调用阻塞 HTTP 请求。终止请求返回作业 ID，由界面轮询结果。

agent RPC 只允许 `health`、`snapshot`、`preview_termination`、`apply_task_policy`、`apply_membership`、`execute_termination`、`job_status`、`audit_since`。新增账号 RPC：`list_accounts`、`list_system_groups`、`preview_account_change`、`execute_account_change`、`preview_group_change`、`execute_group_change`；修改请求只接受类型化账号/组操作，不接受程序名、自由命令或用户任意指定的系统路径。生命周期操作沿用账号 RPC；新增只读 RPC `login_events_since`、`account_activity`、`storage_snapshot`，以及类型化 `apply_quota`、`preview_share_change`、`execute_share_change`。不提供任意命令执行、任意路径读取、任意信号或任意 PID 批量杀进程接口。

## 4. 核心行为约定

### 4.1 进程身份与 GPU 数据

进程内部身份定义为 `(boot_id, pid, start_ticks)`；同时保存用于展示的 `create_time`。boot ID 防止服务器重启后将同 PID/启动 tick 误识别为旧任务，原始 start ticks 避免浮点时间误差。

发信号步骤：打开 pidfd → 再读取 `/proc` 并核对预期身份 → 只向该 pidfd 发送信号。打开后目标已退出或 `/proc` 已出现新实例时跳过并记录，不能转而向数字 PID 盲发信号。TERM 和 KILL 均使用同样原则。平台不支持 pidfd 时第一版关闭终止能力并显示原因，保留只读与配置功能。

GPU 以 UUID 为稳定主键，index 只用于展示；同一 PID 在多个 GPU 上只有一个进程实例和多条显存关联。查询 compute 与 graphics 进程列表并去重；显示桌面图形进程但默认保护、禁用自动终止。

设备利用率与设备显存来自 NVML；进程级利用率仅在接口支持时显示，返回不支持/不可用时显示“不可用”，不能填 0。任务显存为各 GPU 上成员显存关联的汇总，UI 标注为报告值汇总，不保证共享显存场景等于独占占用。

`NoSuchProcess`、`AccessDenied`、僵尸字段缺失和单卡查询失败均单独处理。不能把 NVML 采集失败视为任务已结束。GPU 进程暂时不在活跃列表但同一身份仍存活时继续跟踪，显示“当前未报告 GPU 活动”。

### 4.2 任务发现、归组与人工调整

1. 从 GPU 进程向上找同 UID 的启动祖先；遇到 shell、sshd、systemd、登录会话或跨 UID 边界停止，边界节点可展示但不纳入终止范围。
2. 自定义 wrapper 无法确定是否同时负责多项训练时，不自动提升为共同任务根；默认拆成任务并显示可合并候选。
3. 能明确确认的 launcher（例如独立 torchrun 启动树）可聚合其 GPU worker；同一 UID、相同命令、共同 shell、相同 PGID/SID 单独出现均不足以合并。
4. 将确定的任务根向下的同 UID 后代纳入辅助成员，包括 DataLoader；显示每个成员的关联证据和自动/人工来源。
5. 一个进程身份同时只能是一个任务的可操作成员。共同祖先仅作为树的上下文，不随多个任务重复成为终止目标。
6. 管理员可确认、合并、拆分、排除成员。合并要求同 UID，并检查冲突；更改形成新的 membership revision，旧终止预览失效。
7. 保存已观察到的父子身份边，主进程退出后仍按历史证据关联存活 worker；没有历史证据、仅有 PPID=1 的进程标为“归属不明”，不自动清理。
8. 默认不自动清理残留；仅管理员确认归属并为该任务明确开启残留清理后允许执行，仍受保护和身份校验约束。

任务 `task_id` 使用独立 UUID，不直接使用 PID。根进程退出不新建任务、不丢失备注和期限；成员变化保持身份校验。任务开始时间取已确认任务根的实际启动时间；未知根取首次确认 GPU 成员的最早启动时间并标注依据。人工合并时开始时间取最早值，重新展示期限影响。

纯轮询无法可靠恢复“系统安装前已经消失的父进程”或“两个扫描之间发生且结束的父子关系”。此时采取保守归组与人工确认，不声称完全自动识别。

### 4.3 三级优先级

- 各层为整数 0～100，默认 50。
- 排序键是 `(group_priority, user_priority, task_priority)`，按字典序降序；不求和。
- 示例：`(80, 0, 0)` 高于 `(79, 100, 100)`；`(80, 60, 0)` 高于 `(80, 59, 100)`。
- 清理候选按同样三元组升序，仅排序展示，不触发资源紧张自动清理。
- 每个 UID 只有一个管理组；首次发现放入默认“未分组”。用户名用于展示，UID 用于身份；账号名变更不丢配置。
- 组/用户更新后下一次 API 读取即计算新优先级，不批量改写历史任务。
- 删除组前要求迁移成员；组、用户优先级不影响 Linux nice、期限或保护。

### 4.4 期限、提醒与保护

- 支持 `unlimited`、`max_runtime`、`expires_at`；同时设置两种限时时取较早时刻，并在表单明确展示。
- 最大运行时长从实际任务启动时间计算，不从添加管理配置时计算。
- 数据库存 UTC、API 使用带时区 ISO 8601、前端按 Asia/Shanghai 展示。使用单调时钟等待 TERM 宽限期，避免改系统时间改变等待长度。
- 动作为 `notify` 或 `terminate`；第一版提醒是页面标记、总览数量与事件日志，不接入邮件/短信/钉钉。
- 全局默认为不限时、仅提醒；默认期限只在新任务首次纳管时复制，修改默认不追溯影响现有任务。
- 保护任务仍显示超时。自动期限终止和自动残留清理均跳过保护任务；手动终止保护任务要求明确解除保护后重新预览。
- 期限检查默认 5 秒；验收目标是健康运行时不超过两个扫描周期发现到期，不承诺硬实时。
- 修改期限、保护、动作、成员集会增加版本；agent 按任务串行处理变更与发信号，并在 TERM/KILL 前核验最新版本。
- 延期/保护若发生于 TERM 之后，可以阻止后续 KILL，但不能撤销已发送的 TERM；界面与日志明确显示执行阶段。
- 超时提醒每个“任务 + 策略版本”只创建一次事件，避免每次扫描刷日志。重启后重新检查身份与期限，不重复创建同一作业。

### 4.5 手动终止与执行结果

流程：选择进程/任务 → 服务端生成预览 → 界面展示受影响成员 → 管理员确认与填写原因 → 创建作业 → TERM → 等待默认 10 秒 → KILL → 核验残留 → 记录逐进程结果。

预览包含：任务版本、进程身份列表、用户名、命令、GPU 关联、非 GPU 辅助成员、排除节点、保护状态、有效期（默认 30 秒）、随机一次性 token。执行使用幂等键；重复点击返回同一作业。

成员或策略变更导致 token 失效，返回 409 并要求重新预览。单进程终止默认只影响所选身份；整任务终止只对已确认成员操作，不向上杀 shell，不使用 `killpg` 扩大范围，不接受负 PID。

TERM 先通知任务根，使其有机会正常回收 worker；经过短暂观察后通知仍存活成员。操作期间新生后代只在当前明确已确认根的同 UID 后代范围内纳入，记录新增身份和依据；无法确认的新增进程展示为残留，不自动扩大到别的任务。执行必须有整体时限，持续 fork/重启的任务返回部分完成和残留，不无限追杀。

逐进程结果包括 `exited_before_signal`、`term_exited`、`kill_exited`、`identity_changed`、`protected`、`permission_denied`、`zombie`、`still_alive`；作业状态包括 pending、running、succeeded、partial、failed、cancelled。D 状态进程可能无法立即响应 KILL，必须如实显示存活/待退出，不报告成功。

执行意图在发信号前持久化。agent 崩溃后恢复作业，逐一重新核验，宽限截止保存为 UTC 时间；不向 PID 的新实例重放信号。磁盘满或执行日志无法写入时拒绝新的破坏性操作。

### 4.6 异常处理

| 类型 | 第一版行为 | 自动动作 |
|---|---|---|
| Z 状态僵尸 | 关联父进程、展示当前父进程身份与任务证据；主进程树检查涵盖非 GPU 节点 | 不杀僵尸，不默认杀父进程 |
| 确认的孤儿 worker | 历史根身份已退出、成员身份仍存活，显示依据 | 默认手动；显式策略开启后才自动清理 |
| 归属不明的孤儿 | 无历史身份链，展示候选 | 不自动清理 |
| 疑似卡住 | 初版仅显示持续 D 状态等可解释信号及持续时间；作为异常线索 | 不自动终止，不仅凭低利用率判卡死 |
| 到期 | 标记超时并按任务策略执行 | notify 或 terminate，保护优先 |
| GPU/agent 采集异常 | 标记快照过期，保留最后成功数据和错误原因 | 暂停新的自动终止 |

第一版不重置 GPU，不按显存不足自动杀低优先级任务。

### 4.7 本地账号、系统组与受管目录

**账号范围与身份：** 查询服务器本地账号、UID/GID、主组与附属组、shell、shadow 账号状态（不返回哈希）、受管目录、进程与会话。root、系统 UID、gpuPM 账号、当前维护 SSH 账号及 root 配置中的保护名单不可修改或删除。已有普通账号先只读，管理员明确纳管；LDAP/NIS 等非本地来源只能查询。用户名重名检查使用 NSS，禁止选项注入、非法字符、重复 UID/GID 和指定 UID 0。

账号使用生命周期 UUID 关联业务配置和历史任务。软删除及恢复保留同一生命周期、Linux 账号、UID/GID 和业务配置，禁止在已有软删除账号之上新建同名或同 UID 账号。若检测到管理员在平台外实际删除并重建账号或复用 UID，标记身份漂移，核验后使用新生命周期，不自动复用旧配置和目录。软删除、恢复与改名预览必须绑定当时的账号状态、用户名、UID、主 GID、目录注册记录和版本。

**初始化目录：** 安装时必须明确 `home_base`（建议 `/home`）与 `data_base`（例如挂载数据盘上的 `/data`），保存在 root 所有的配置中。验证绝对路径、互不重叠、不在系统关键目录、无不受控可写祖先/软链接跳转；记录数据卷的预期设备/挂载点，创建前复核，不能只检查路径存在。用户建立后不能在网页直接切换全局根路径或自动搬迁已有数据。

为 alice 创建 `/home/alice` 和 `<data_base>/alice`，属主为 alice UID/主 GID，模式 0700；初始化默认 umask 077，复制受控 skeleton 中的 bash 配置并设置 `DATA_DIR`。主目录提供 `~/data` 链接，已有同名文件时报告冲突。系统只提供入口，不修改用户训练脚本，不保证用户之后不主动调整自己的权限。

受管根由 root 所有，允许到达自己的子目录但不允许普通用户创建/替换兄弟目录。创建与改名采用受控父目录 fd、禁止跟随链接的操作和身份/设备校验，避免检查后路径替换；不对任意现有目录递归 chown，不接管同名现有路径。若支持 ACL 的存储存在继承规则，必须验证实际互访拒绝，不能只看权限数字。初版以支持 POSIX 权限且可由宿主机 root 管理的存储为前提；root-squash 等不满足条件时拒绝操作并报原因。

**Linux 用户组：** 默认每用户同名私有主组，可设置允许的普通主组和附属组，支持受管普通组创建/查询/改名/备注/成员维护/删除。业务优先级组独立。`sudo`、`docker`、`root`、`adm`、gpupm agent 访问组及 root 配置的其他敏感组不能通过页面赋权；用户不能自行提交高权限组名绕过。主组/附属组变更不自动递归改所有历史文件，也不更新已运行进程的组凭据；界面提醒重新登录，已脱离纳管目录的文件由管理员另行处理。

**修改：** 说明、allowlist 中的 shell（默认 `/bin/bash`，可包括 `/usr/sbin/nologin`）、登录配置、普通组和业务字段可修改。用户名/受管目录改名在无该 UID 活动进程或会话时才能执行；先展示受影响路径，暂停账号新登录，再重核验。第一版仅支持受管根内同文件系统的离线目录移动，不支持跨卷复制、全局根迁移或任意 UID/GID 变更。权限服务恢复状态记录必须覆盖改名造成的目录/业务配置变化。

**登录凭据：** Web 管理员和 Linux 账号独立。用户已确定同时支持 SSH 公钥和密码。界面提供初始密码/密码重置以及多个公钥的增删；公钥可在创建时添加或之后补充，系统不生成或保存私钥。公钥验证格式及类型，不接受 authorized_keys 自由选项；`.ssh` 为 0700、`authorized_keys` 为 0600，写入不跟随用户链接。密码如启用通过受控标准输入交给系统工具，不出现在 argv、日志、数据库或重试作业载荷；密码操作中断后需重新提供。不能假定锁定密码就禁止 SSH 公钥登录；如需暂停登录，采用适用于已核验 PAM/SSH 配置的账号到期/禁用策略，并实测公钥与密码两条路径。初始化检查有效 SSH/PAM 配置；如果现有配置禁止密码登录，明确报告限制，使用只覆盖受管账号的 SSH 配置方案并经配置校验与实际双路径登录测试后才宣告可用，不盲目放宽全机或 root 登录策略，不因此结束现有会话。

**软删除与恢复：** 删除预览列出账号、全部 UID 进程（不限 GPU）、登录会话、主/数据目录以及“保留全部文件、不终止已有进程”的结果。第一版删除只做软删除：停用后续登录，保留 passwd/shadow 中的账号、UID/GID、系统组关系、业务配置、全部目录和文件；绝不调用 `userdel`，不移动目录、不递归 chown/chmod、不清空文件。用户名和 UID 继续保留，不允许被新账号复用。

业务记录包含 `deleted_at`、`deleted_by`、`delete_reason`、`login_disable_status` 和停用前可恢复的非敏感状态。作业先记录意图，再应用并核验密码与公钥两条登录路径的停用，最后确认软删除已生效；失败标为 pending/failed 并允许幂等重试，不能把数据库标记当作系统停用成功。活动进程和会话不阻止软删除，也不自动终止；任务扫描仍覆盖该 UID，原优先级、期限和保护继续生效，不因账号从正常列表隐藏而忽略 GPU 任务。

普通账号列表默认排除软删除记录，提供正常/停用/到期/已删除/全部筛选与恢复入口。软删除后阻止普通账号改名/组/凭据编辑，先恢复再操作。恢复使用同一账号和配置，仅撤销本平台的软删除限制，保留独立停用、到期和外部限制；验证身份、目录、状态未漂移后执行，恢复失败显示具体原因。保留审计；不提供永久删除账号或文件的接口，不删除该用户的系统主组或附属组关系。

**独立停用与有效期：** 独立保存临时停用、软删除和账号有效期，合并计算有效限制。展示优先级为 deleted > disabled > expired > active，详情显示全部原因和系统应用状态。enable 只撤销临时停用；restore 只撤销软删除；延期/取消只改变期限，不覆盖其他原因或外部限制。统一登录状态协调器串行应用这些原因，避免一次 unlock 恢复所有权限。

账号有效期采用系统支持的日期粒度，表单与详情显示实际生效时刻（Asia/Shanghai），不同于 GPU 任务的秒级期限。用 native shadow/PAM 账号有效期约束到期登录，并在 agent 对账时核验；恢复不得把旧到期字段覆盖为不限时。到期默认禁止新登录并告警，不结束现有训练。

**密码策略：** 新账号与管理员重置密码默认 `require_password_change=true`，可按账号取消；周期换密默认关闭，展示最后修改、需改密、锁定与系统密码有效期。密码只经标准输入暂存。平台调用 libpwquality 校验质量，默认至少 12 字符、拒绝用户名/常见弱口令，初始化确认依赖与实际策略，不强迫固定字符类别组合。用户自行 passwd 的质量策略由 PAM 决定，展示“平台校验已启用/系统强制已验证”两个状态，未验证不能宣称全机强制。首次改密涉及 PAM account/password 栈，必须实测密码与公钥交互登录、非交互 SSH/SFTP，并提示改密前的非交互限制。不自动覆盖全局 PAM 文件或维护账号。

**登录与活动：** 从 journald 或 Ubuntu SSH auth 日志采集 successful/failed/disconnected 事件，记录源时间、用户名、源 IP/端口、已知认证方式、公钥指纹（日志提供时）、来源和唯一事件 ID；未知用户失败记录不绑定错误 account_id。展示当前 logind/SSH 会话、可发现 UID 进程、用户 crontab、用户服务/timer/linger 状态；不可访问、日志缺失和覆盖时段明确显示。只读取固定日志源和受限接口，不读取任意用户路径或私钥，不把 crontab 命令全文写入诊断日志。

增量游标支持 journal cursor、文件 inode/offset、轮转与 boot ID，重复事件不重复写入。安装前历史按实际日志回溯，缺失不填造。当前会话、历史记录与 GPU 任务分开统计；软删除/停用后显示“仍有活动”，不自动清除 cron、停止用户服务、断开会话或终止进程。结束 GPU 任务仍走已有流程，不新增无预览的整用户 kill。

**存储用量与配额：** 展示受管 home/data/shared 目录已分配空间与文件数、所属文件系统总量/可用量，以及 UID 在各文件系统上的内核配额用量，两种口径分开标注。目录统计默认 15 分钟后台执行，带采样时间和超时/过期状态；不跟随链接、不越过未授权挂载，硬链接按 inode 在单次统计去重，shared 不重复算进每个成员个人目录。失败保留部分/旧结果并标注，不能填零。

第一版实现本地 ext4/XFS 的 user quota 适配，API 单位统一 bytes/inode，adapter 显式换算。quota key 为 `(account_id, uid, filesystem_id)`，不是目录路径；同文件系统的 home/data 合并计入该 UID 配额，用户在其他目录拥有的文件也可能计入，界面解释口径。只设置明确受管挂载的 user quota，不使用 all-filesystems 参数。支持空间/inode soft/hard、宽限、读回核验和默认模板（默认不限额）；降低至已有用量以下先预览影响，不清理文件。文件系统仅支持全局宽限或无法设置个别字段时如实显示，不假装独立生效。

初始化探测工具、文件系统与实际配额状态。未支持/未启用仍可查用量和告警，但拒绝配额提交并提供启用步骤；交付 ext4/XFS 适配与隔离测试，不因测试机缺工具跳过实现。生产卷不自动格式化、重挂载或重启。用量默认 80% warning/90% critical，可配置；hard limit 为 0 表示不限额，不除零。配额/空间不足不自动终止训练；软删除不清零配额或统计。

**共享目录：** `share_base=<data_base>/shared`，root 所有；shared 为保留用户名。项目路径为 `<share_base>/<项目名>`，禁止任意路径与链接跳转，不添加私人目录 ACL。共享根禁止普通用户创建项目；项目由 root 拥有、writer 组为 owning group，目录 setgid，reader/writer 为独立普通系统组，设置 access/default ACL。reader 可读/遍历不可写，writer 可读写，其他用户不可进入；校验 ACL mask 与新文件有效权限。继承受创建 mode 限制，应用创建 0600 或用户主动 chmod 可收紧文件权限，不能保证所有输出自动共享。

授权变更先预览范围和有效权限，按路径身份版本应用，记录 ACL 前后值。只操作注册根及明确授权的既有内容，不默认递归扩大到私人目录、链接目标或其他挂载；停用项目保留全部文件，不提供永久删数据。移除组成员后旧进程可能持有旧组凭据，打开的句柄不会自动撤销，页面提示重新登录与检查活动，不能报告即时完全撤权。关联组有引用时禁止删除。shared 单独统计；user quota 按文件 UID 计费，不宣称是团队 project/group 硬配额。

**执行和恢复：** shadow-utils 使用绝对程序路径和参数数组，禁止 `shell=True`，成功后重新查询系统事实，不只依赖退出码。全局账号操作锁串行化平台内更改；同时识别外部管理工具产生的冲突。OS 账号与文件系统不能和 SQLite 做一个原子事务；每步保存意图/结果，账号与目录未全部就绪时保持未启用，失败报告具体阶段，重试通过作业 ID 幂等对账。补偿仅针对本作业创建且当前身份匹配的空资源，绝不自动清理冲突路径或已有数据。

审计包括操作者、账号生命周期、用户名/UID/GID、动作、目录、组/配置的前后值、结果；密码、公钥敏感载荷和 shadow 哈希不进入审计。

## 5. 数据模型与 API

### 5.1 API 业务库 `app.db`

| 表 | 关键内容 |
|---|---|
| `admins` | 管理员 ID、用户名、Argon2id 哈希、启用状态 |
| `sessions` | 会话 token 哈希、管理员、过期时间、CSRF 信息 |
| `management_groups` | 名称、优先级、备注、默认组标记 |
| `managed_users` | 账号生命周期 UUID、UID、当前用户名、唯一管理组、优先级、备注；软删除及恢复保持关联，外部 UID 复用不得继承旧配置 |
| `system_accounts` | 纳管来源、UID/GID、用户名、shell、目录、版本、disabled_at/reason、account_expire_date、deleted_at/by/reason、require_password_change、系统应用状态和平台修改前基线；不保存密码明文/哈希 |
| `system_group_records` | 受管系统组、GID、敏感/保护标记、成员快照、版本 |
| `account_operation_requests` | 创建/修改/停用/启用/软删除/恢复/有效期/密码策略预览、幂等键、操作者、阶段、结果、脱敏前后值 |
| `login_events` | 来源唯一 ID、account_id（可空）、用户名、时间、源 IP/端口、方式、结果、指纹（可空）、覆盖信息 |
| `storage_samples` | 目录/文件系统/UID、allocated bytes/inode、可用空间、采样时间、状态与口径 |
| `quota_policies` | account_id/UID/filesystem ID、空间/inode 限额、宽限期、版本与读回状态 |
| `shared_directories` | 项目 ID、受管路径/设备身份、reader/writer 组、ACL 模板、状态、版本 |
| `tasks` | UUID、boot ID、根身份、开始时间、名称、备注、纳管状态 |
| `task_policies` | 任务优先级、保护、期限、动作、残留策略、版本、应用状态 |
| `task_overrides` | 人工合并/拆分/排除结果和成员版本 |
| `settings` | 扫描周期、TERM 等待、默认期限、展示时区 |
| `operation_requests` | 作业 ID、幂等键、操作者、原因、预览版本、执行状态 |
| `audit_logs` | 配置/登录/手动/自动操作、前后值、目标身份、结果、agent 事件 ID |

### 5.2 agent 执行库 `agent.db`

`process_instances`、`relationship_edges`、`task_memberships`、`applied_policies`、`termination_jobs`、`termination_targets`、`execution_events`、`account_jobs`、`account_job_steps`、`managed_directory_registry`、`login_ingestion_cursors`、`applied_login_states`、`applied_quotas`、`share_operations`。记录完整身份、来源、版本、首次/末次观察和终止阶段。执行事件按唯一 ID 同步到 API；API 暂时不可用时不丢失事件。

不把每次 GPU 快照都写入长期历史；只保存必要当前状态、关系变化与审计。使用 SQLite Backup API 导出一致性备份，不能只复制正在使用 WAL 的 `.db` 文件。历史保留与归档参数在部署文档中说明，首版不提供前端删审计功能。

### 5.3 API 分组

| 接口 | 主要内容 |
|---|---|
| `POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/auth/me` | 登录、退出、当前管理员 |
| `GET /api/overview`、`GET /api/gpus` | GPU 状态、任务与异常计数、采集健康 |
| `GET /api/tasks`、`GET /api/tasks/{id}` | 筛选、排序、分页、成员树、关联依据 |
| `PATCH /api/tasks/{id}` | 名称、备注、优先级、期限、保护 |
| `POST /api/tasks/merge`、`POST /api/tasks/{id}/split` | 人工调整归组，使用成员版本防冲突 |
| `PATCH /api/tasks/{id}/members` | 确认或排除已有候选成员 |
| `POST /api/tasks/{id}/termination-preview` | 单进程/整任务预览，不发送信号 |
| `POST /api/tasks/{id}/terminate`、`GET /api/operations/{id}` | 确认终止、查询异步结果 |
| `/api/groups`、`/api/users` | 业务优先级管理组与用户业务配置 |
| `GET /api/system-users`、`GET /api/system-users/{account_id}` | 本地账号查询、纳管/保护状态、目录和活动进程/会话；支持 active/disabled/expired/deleted/all 筛选 |
| `POST /api/system-users`、`PATCH /api/system-users/{account_id}` | 创建或修改普通账号，返回异步作业；离线改名/受管目录调整必须预览 |
| `POST /api/system-users/{account_id}/change-preview`、`DELETE /api/system-users/{account_id}` | 修改/软删除预览与确认；停用新登录，账号和文件原地保留，不结束现有进程/会话 |
| `POST /api/system-users/{account_id}/restore` | 按预览和版本恢复同一软删除账号，不新建用户、不搬迁文件 |
| `POST /api/system-users/{id}/disable`、`POST /api/system-users/{id}/enable` | 临时停用/启用，核验所有有效限制，不结束已有活动 |
| `PATCH /api/system-users/{id}/expiry`、`PATCH /api/system-users/{id}/password-policy` | 有效期、首次改密与密码状态；密码重置不保留密码载荷 |
| `GET /api/system-users/{id}/activity`、`GET /api/login-events` | 当前进程/会话/可发现定时任务与服务，登录历史及覆盖信息 |
| `GET /api/storage`、`GET/PATCH /api/system-users/{id}/quotas` | 目录用量、挂载容量与 user quota 配置/生效状态 |
| `/api/shares`、`POST /api/shares/{id}/change-preview` | 共享项目 reader/writer 权限维护，保留所有文件 |
| `/api/system-groups`、`POST /api/system-groups/{id}/change-preview` | 受管普通 Linux 组 CRUD 与成员维护；修改/删除先预览 |
| `GET/PATCH /api/settings` | 系统策略 |
| `GET /api/audit-logs` | 时间、操作人、类型、任务、结果筛选 |
| `GET /api/health` | 最小健康状态，不向匿名用户泄露进程信息 |

所有进程/配置接口要求管理员会话；修改接口还校验 CSRF。统一错误码区分身份改变、范围改变、受保护、策略未应用、agent 不可用。后台重新核验 UI 提供的 PID 和 task_id，不能把浏览器数据当成执行事实。

## 6. 前端页面与交互

| 页面 | 第一版交付内容 |
|---|---|
| 登录 | 账号密码、错误提示、会话失效处理 |
| 总览 | GPU 卡片、显存/利用率、运行任务数、超时/异常数、agent 健康 |
| 任务列表 | GPU/用户组/用户/状态筛选，三级优先级/运行时间/显存排序，分页 |
| 任务详情 | 任务配置、GPU 关联、父子树、身份、归组依据、历史根、异常与执行结果 |
| 用户组 | 业务优先级组与 Linux 系统组分标签；主组/附属组、成员、受保护组、删除限制 |
| 用户 | Linux 账号 CRUD/软删除恢复、停用启用、有效期、密码策略、公钥、主/附属组、目录用量/配额、登录历史及活动；业务优先级与备注 |
| 存储与共享 | 私人/共享目录用量、文件系统空闲空间、配额支持/生效状态、容量告警；共享 reader/writer 权限 |
| 策略 | 扫描周期、TERM 等待、默认期限与动作、应用状态；初始化主目录根和数据目录根的只读展示 |
| 操作日志 | 修改前后值、操作者、自动动作来源、逐进程结果、失败原因 |

终止弹窗必须列出非 GPU 辅助进程及被排除的 shell；保护任务明确显示解除保护入口。提交期间禁用重复操作，结果通过作业状态显示。快照过期时展示最后采集时间与连接状态；颜色之外还提供文字状态；表单有标签、键盘可操作。

## 7. 建议目录与文件职责

```text
backend/
  pyproject.toml
  migrations/                   # API 数据库迁移
  src/gpupm/
    api/main.py                 # 应用工厂、路由、静态文件
    api/auth.py                 # 密码、会话、CSRF
    api/routes/                 # tasks/groups/users/system_users/system_groups/settings/audit/overview
    api/agent_client.py         # 受限 socket 客户端
    db/models.py                # 业务模型
    db/session.py               # SQLite 连接配置
    domain/priority.py          # 三元组比较
    domain/deadlines.py         # 到期语义与默认配置
    domain/schemas.py           # 明确的数据契约
    agent/main.py               # 生命周期、扫描与期限循环
    agent/server.py             # RPC 和 SO_PEERCRED 校验
    agent/gpu.py                # NVML 适配
    agent/processes.py          # /proc、psutil、身份与边界
    agent/grouping.py           # 归组、证据、人工覆盖
    agent/termination.py        # 预览、pidfd、TERM/KILL、恢复
    agent/store.py              # root 状态、策略、执行事件
    agent/accounts.py           # shadow-utils 适配、账号/组操作
    agent/directories.py        # 受管目录创建、默认隔离及离线改名；软删除不操作文件
    agent/account_jobs.py       # 预览、幂等、分步骤执行与恢复
    agent/login_states.py       # 停用/到期/软删除限制协调
    agent/login_events.py       # 受限 SSH 日志增量采集
    agent/activity.py           # 会话/UID 进程/定时任务和用户服务查询
    agent/storage.py            # 后台目录统计与容量告警
    agent/quotas.py             # user quota 契约与 ext4/XFS 适配
    agent/shares.py             # 共享 ACL 和普通组授权
    cli.py                     # 管理员/用户目录根初始化、健康检查
  tests/unit/                  # 规则和假设备/假进程测试
  tests/integration/           # API、RPC、数据库和 Linux 进程测试
frontend/
  src/api/                     # 带会话/CSRF 的 API 请求
  src/queries/                 # TanStack Query 的 query keys、轮询和 mutations
  src/router/                  # React Router 登录守卫和页面路由
  src/pages/                   # 登录、原管理页面及存储/共享视图
  src/components/              # ProcessTree/TerminationDialog/DeadlineForm
  tests/                       # 组件和表单行为
tests/e2e/                     # 管理员完整操作链
tests/fixtures/                # 人工训练树、僵尸、TERM 忽略器
deploy/systemd/                # gpupm-api.service / gpupm-agent.service
deploy/nginx/                  # 可选同源 HTTPS 反向代理
scripts/                       # build/deploy/health/backup
docs/                          # API、归组规则、测试报告、部署与恢复
```

目录以职责拆分；实施时仅创建当前任务需要的模块。NVML 和进程接口要可替换成测试实现，使 macOS 本机能够开发，Linux 特有信号测试在 Ubuntu 执行。

## 8. 分阶段实施清单

当前完整范围按单人实现与验证粗估约 **23～35 个工作日**，不是承诺。GPU 管理部分约 12～18 天，账号/目录基础部分约 5～8 天，生命周期/密码策略/配额/登录历史/共享部分约 6～9 天；任务识别、存储配置和实机验证是主要变量。每阶段完成一条可演示路径；本次不直接提交 Git 或开始实现。

### 阶段 A：工程基础与契约（1～2 天）

**文件：** `backend/pyproject.toml`、`frontend/package.json`、`backend/src/gpupm/domain/schemas.py`、`backend/src/gpupm/db/*`、`backend/migrations/*`、`README.md`。

- [ ] 初始化 Python/React 工程及锁文件，配置本地模拟模式与 Ubuntu 实际模式。
- [ ] 定义完整进程身份、GPU 关联、任务版本、策略应用状态、错误码和作业状态。
- [ ] 建立 API SQLite 模型、初始 Alembic 迁移、默认“未分组”和初始策略。
- [ ] API 应用工厂、健康检查、前端路由与基本布局能够启动。
- [ ] 先写优先级/期限规则测试，验证失败，再实现纯规则函数。
- [ ] 写 README 中的开发启动命令；没有 GPU 时明确显示模拟数据来源。

**检查：** `cd backend && python -m pytest tests/unit/test_priority.py tests/unit/test_deadlines.py -q`；`cd frontend && npm run build`。

**验收：** 三元组严格比较、0/100 边界、非法值拒绝、UTC 转换、最大时长从实际启动计算测试通过；浏览器可打开基础界面。

### 阶段 B：权限服务与 GPU/进程采集（2～3 天）

**文件：** `agent/main.py`、`agent/server.py`、`agent/gpu.py`、`agent/processes.py`、`api/agent_client.py`；测试 `test_agent_protocol.py`、`test_gpu_collector.py`、`test_process_identity.py`。

- [ ] 实现长度受限的 Unix socket RPC、协议版本、对端 UID 认证与超时。
- [ ] 实现 NVML 初始化、设备 UUID、compute/graphics 去重、可选指标降级和重连。
- [ ] 实现 boot ID、start ticks、UID、PPID、状态、命令、启动时间与父子索引。
- [ ] 加入退出竞争、AccessDenied、NVML 不支持/单卡失败的测试。
- [ ] 扫描定时循环只启动一次；API 重启或页面刷新不额外启动扫描器。
- [ ] 在服务器独立 venv 中只读比对采集快照和 `nvidia-smi`，不先开启终止能力。

**检查：** `cd backend && python -m pytest tests/unit/test_gpu_collector.py tests/unit/test_process_identity.py tests/integration/test_agent_protocol.py -q`。

**验收：** 能显示全用户 GPU 进程及关联树；失去 GPU/agent 时展示不可用或过期，现有任务不因采集失败被标记结束。

### 阶段 C：归组、辅助进程与身份历史（2～3 天）

**文件：** `agent/grouping.py`、`agent/store.py`、`api/routes/tasks.py`、`tests/unit/test_grouping.py`、`tests/fixtures/process_trees.json`。

- [ ] 先构造同 shell 两项训练、torchrun 多 worker、DataLoader、跨 UID、重复 PID 和未知 wrapper 样本。
- [ ] 实现保守归组、上下文祖先、辅助成员、稳定 task_id 和关联证据。
- [ ] 持久化父子身份历史；NVML 列表消失后继续检查已知成员身份。
- [ ] 合并/拆分/排除使用版本；禁止跨用户合并及操作成员重复归属。
- [ ] 人工调整在重启后恢复；已退出根仍展示历史身份，不能链接到复用 PID 的新进程。
- [ ] 提供任务列表/详情 API，返回快照时间与版本。

**检查：** `cd backend && python -m pytest tests/unit/test_grouping.py tests/integration/test_task_recovery.py -q`。

**验收：** 同 shell 不同训练保持分离；worker/辅助进程正确归属；父退出后可查已观察残留；不确定关系不自动扩大终止范围。

### 阶段 D：登录、用户组、优先级与配置审计（1～2 天）

**文件：** `api/auth.py`、`api/routes/groups.py`、`users.py`、`settings.py`、`audit.py`、`cli.py`；对应接口测试。

- [ ] 管理员初始化 CLI；密码不写默认明文、不复用 SSH 密码。
- [ ] 实现 Argon2id、服务端会话、登录限速、CSRF 和退出失效。
- [ ] 管理组/用户配置、默认组迁移、优先级校验与字典序排序。
- [ ] 配置修改与审计在同一事务写入，保存前后值、操作人和时间。
- [ ] Linux 用户显示 UID 和账号生命周期；业务管理组不修改系统组，Linux 系统组走独立操作接口。

**检查：** `cd backend && python -m pytest tests/integration/test_auth.py tests/integration/test_management.py tests/integration/test_audit.py -q`。

**验收：** 未登录无法读任务或执行管理；错误 CSRF 被拒；组/用户优先级修改立即影响现有任务排序；会话退出后失效。

### 阶段 D2：本地账号、系统组与隔离目录（5～8 天，含新增实机与页面测试）

**依赖：** 阶段 B 的权限 RPC、阶段 D 的管理员鉴权与审计。完整行为见第 4.7 节；这一阶段增加账号和系统组标签页，阶段 G 验证它们与任务页面的联动。

**文件：** `backend/src/gpupm/agent/accounts.py`、`directories.py`、`account_jobs.py`、`api/routes/system_users.py`、`system_groups.py`、`cli.py`、`db/models.py`；`frontend/src/pages/SystemUsers.tsx`、`SystemGroups.tsx`、`frontend/src/components/AccountForm.tsx`、`AccountChangeDialog.tsx`；`tests/unit/test_accounts.py`、`test_directory_boundaries.py`、`tests/integration/test_account_jobs.py`、`test_linux_accounts.py`。

- [ ] 初始化 CLI 要求明确目录根与预期挂载；验证绝对路径、不重叠、受控 root 所有父目录和实际存储位置，将结果写入 root 配置。
- [ ] 查询本地 passwd/group 并用 NSS 检查重名冲突；系统/维护账号只读，普通现有账号需显式纳管；不提供 LDAP/NIS 账号修改。
- [ ] 建立账号生命周期 ID、账号/组快照版本、目录注册表与作业状态机。
- [ ] 先写用户名/组名、敏感组、目录穿越、链接替换、冲突目录和重复请求拒绝测试，再实现固定 argv 的账号工具调用。
- [ ] 创建默认 `/bin/bash`、私有主组、受管主目录和数据目录；0700、077、`~/data`、`DATA_DIR`，配置登录凭据后才标记可用。
- [ ] 实现初始密码、密码重置、多公钥维护；使用受控标准输入处理密码，验证 `.ssh`/`authorized_keys` 权限；实测公钥与密码登录、重置后旧密码失效、移除后旧公钥失效、账号暂停登录阻断两条路径。
- [ ] 实现说明、允许 shell、主组/附属组、登录配置、业务配置更新；离线改名和受管目录调整需要预览、版本重核验与新目录冲突检查。
- [ ] 实现普通系统组 CRUD；敏感组禁止赋权，删除前核验所有主组引用和成员；成员变更提示旧进程仍持有旧组凭据。
- [ ] 软删除前展示账号、进程/会话和原路径；阻止新的密码/公钥登录，保留账号/UID/组和所有文件，活动会话继续，不调用 userdel 或修改目录。
- [ ] 实现已删除/全部筛选和同一账号恢复，保留原业务配置和凭据；恢复不覆盖外部限制，重复请求幂等，失败不误报停用/恢复成功。
- [ ] OS 修改与数据库无法整体事务化：步骤前后写执行日志，失败停止、核对实际状态、可幂等恢复；补偿仅涉及本次新建且仍匹配身份的资源。
- [ ] 两个专用测试用户验证 bash 登录、私有主/数据目录、同组仍隔离、已存在路径不接管、无 sudo/docker 权限、软删除后名字/UID 仍占用、同名新建被拒、旧文件原位置/内容/属主/权限均不变、恢复后可访问原文件。
- [ ] 验证改名期间的版本冲突、外部 usermod/groupmod 引起的漂移、agent 崩溃恢复、数据卷未挂载时拒绝创建。
- [ ] React 表单、变更预览、保留目录提示、作业部分失败和脱敏审计完成组件/E2E 验证。

**检查：** `cd backend && python -m pytest tests/unit/test_accounts.py tests/unit/test_directory_boundaries.py tests/integration/test_account_jobs.py -q`；隔离 Ubuntu 测试环境执行 `python -m pytest tests/integration/test_linux_accounts.py -m destructive -q`；`cd frontend && npm run test -- --run`。

**验收：** 创建/修改/查询/删除普通账号及系统组成功；默认 bash；两个用户实际不能相互访问私人目录；软删除后文件不变、不能新登录但既有进程保留，恢复同一账号和配置；重复/中断操作可恢复；现有系统账号、维护账号和真实训练不受影响。

### 阶段 D3：生命周期、配额、登录历史与共享目录（6～9 天，含测试）

**依赖：** D2 的账号/目录与作业接口。保留 D2 测试，增加限制组合、存储与授权测试。

**文件：** `backend/src/gpupm/agent/login_states.py`、`login_events.py`、`activity.py`、`storage.py`、`quotas.py`、`shares.py`；`backend/src/gpupm/api/routes/login_events.py`、`storage.py`、`shares.py` 和已有 system_users/settings；业务迁移；`frontend/src/pages/Storage.tsx`、`SharedDirectories.tsx`、`frontend/src/components/AccountStatusPanel.tsx`、`QuotaForm.tsx`、`LoginHistory.tsx`。

- [ ] 先写正常/停用/到期/软删除组合、enable/restore 不解除其他限制、外部状态漂移和并发操作测试，再实现统一登录限制协调器。
- [ ] 实现独立停用/启用、账号有效期设置/延期/取消、实际时间展示与重启对账；密码/公钥登录均实测，既有训练和会话保持运行。
- [ ] 实现初始/重置密码默认首次改密、libpwquality 质量校验、系统策略状态；测试弱密码拒绝、改密后可用，以及交互/非交互 SSH 和 SFTP 行为。
- [ ] 写 journal/file 样本的成功/失败/未知用户名/IPv4/IPv6/缺失指纹解析测试，再实现游标、轮转、boot ID、去重与覆盖时段。
- [ ] 实现当前会话、UID 进程和可发现 crontab/用户服务/timer/linger 查询；权限或日志缺失明确降级，不提供任意路径读取或默认终止。
- [ ] 实现后台目录统计、hardlink 去重、链接/挂载边界、超时/部分结果、剩余空间与 80%/90% 告警去重，不阻塞 GPU 扫描。
- [ ] 实现 ext4/XFS user quota 探测/适配、bytes/inode 单位、软/硬限额、宽限、预览、读回与失败恢复；不支持时拒绝提交，不能显示假生效。
- [ ] 在隔离 VM/专用 loopback 文件系统分别测试 ext4/XFS：硬限拒写、inode 限额、软限宽限、降低限额、取消限额、软删除后用量保持；不格式化或重挂载生产卷。
- [ ] 预留 shared 用户名，创建 `/data/shared/<项目>` 的 root 目录和 reader/writer 普通组；实现 setgid/default ACL、有效 mask、权限预览和共享用量。
- [ ] 用 reader/writer/outsider 测试读写矩阵、创建继承、应用 0600 限制、撤组后的旧会话风险、路径替换、私人目录未开放和既有文件保留。
- [ ] React 完成生命周期控件、登录历史/活动、存储/配额和共享页面；组件/E2E 覆盖状态冲突、pending/failed、过期指标和权限预览。
- [ ] 补充 quota/ACL/PAM/SSH 初始化诊断、依赖与宿主机配置步骤；说明日志覆盖、日期粒度、配额口径、停用后的活动与共享撤权边界。

**检查：** `cd backend && python -m pytest tests/unit/test_login_states.py tests/unit/test_login_events.py tests/unit/test_storage.py tests/unit/test_quotas.py tests/unit/test_shares.py -q`；隔离 Ubuntu 执行 `python -m pytest tests/integration/test_account_lifecycle.py tests/integration/test_quota_filesystems.py tests/integration/test_share_access.py -m destructive -q`；前端执行 `npm run test -- --run`、`npm run typecheck` 和 `npm run build`。

**验收：** 六项新增功能有端到端证据；组合限制不能被错误解除；密码/公钥行为符合实际 PAM；quota 真正限制写入；共享读写矩阵正确；日志轮转/重启可恢复；全部私人文件原地保留。

### 阶段 E：安全终止、作业恢复与逐进程日志（2～3 天）

**文件：** `agent/termination.py`、`api/routes/operations.py`、`tests/unit/test_termination.py`、`tests/integration/test_linux_termination.py`、专用进程 fixtures。

- [ ] 先写身份改变、预览过期、成员变更、保护、幂等和 TERM/KILL 阶段测试。
- [ ] 实现 pidfd 打开后身份重核验、预览 token 和任务操作互斥。
- [ ] 实现单身份/整任务 TERM、宽限、KILL、整体时限与残留结果。
- [ ] 已确认的新生后代纳入记录；身份不明确者不追杀。
- [ ] 发信号前记录执行意图；agent 重启恢复时重新核验每个身份。
- [ ] 审计数据库不可写时拒绝新操作；API 按执行事件 ID 去重同步。
- [ ] Ubuntu 上只终止独立测试脚本及其 worker，核验 sibling、shell 和无关用户进程仍存在。

**检查：** `cd backend && python -m pytest tests/unit/test_termination.py -q`；Linux 上执行 `python -m pytest tests/integration/test_linux_termination.py -m destructive -q`，需显式提供 fixture manifest。

**验收：** TERM 正常退出、忽略 TERM 后 KILL、单进程范围、整树辅助成员、PID 复用拒绝、重复点击幂等、部分失败原因均有明确结果；测试 shell 不被终止。

### 阶段 F：期限策略与异常检测（1～2 天）

**文件：** `domain/deadlines.py`、`agent/main.py`、`agent/store.py`、`agent/anomalies.py`、对应策略恢复测试。

- [ ] 实现不限时、指定时刻、最大运行时长、延期和取消。
- [ ] 版本化策略同步；未应用策略显示 pending，不显示已生效。
- [ ] agent 到期循环复用阶段 E 执行器；保护、提醒去重、重启对账。
- [ ] Z 状态与父身份、已知孤儿 worker、持续 D 状态的持续时间标记。
- [ ] 明确归属且主动开启才自动清理残留；低利用率不触发终止。
- [ ] 覆盖保护与到期并发、TERM 后延期、断联、重启、GPU 数据过期。

**检查：** `cd backend && python -m pytest tests/unit/test_deadlines.py tests/unit/test_anomalies.py tests/integration/test_policy_recovery.py -q`。

**验收：** 高优先级仍到期；受保护只告警；新策略确认前不执行；重启不丢配置、不重复作业、不向复用 PID 发信号。

### 阶段 G：完成全部管理员页面（2～3 天，可与后端阶段穿插）

**文件：** `frontend/src/pages/*`、`frontend/src/api/*`、`frontend/src/queries/*`、`frontend/src/components/ProcessTree.tsx`、`frontend/src/components/TerminationDialog.tsx`、`frontend/src/components/DeadlineForm.tsx`、`frontend/tests/*`、`tests/e2e/*`。

- [ ] 总览、筛选排序列表、任务详情树、归组调整。
- [ ] 用户组、用户、策略、日志页面；包含 Linux 账号/系统组标签、目录和变更预览、软删除筛选和恢复入口；备注与期限表单。
- [ ] 预览受影响进程、终止确认、结果轮询、部分失败提示。
- [ ] 快照过期、会话失效、策略应用失败与编辑冲突提示。
- [ ] TanStack Query 的 query key 包含筛选、排序、分页和任务 ID；修改成功后刷新受影响的列表/详情/总览，退出时清理缓存。
- [ ] 表单草稿独立保存，不被轮询覆盖；终止 mutation 禁止自动重试；React Testing Library 验证这些行为及键盘交互。
- [ ] 用模拟后端完成浏览器流程，再接服务器真实只读数据。

**检查：** `cd frontend && npm run test -- --run`、`npm run typecheck`、`npm run build`；项目根运行 `npx playwright test`。

**验收：** PRD 原管理页面、登录页和新增存储/共享及账号生命周期视图全部可用；管理员可从列表定位任务、改期限、预览终止、查看逐进程日志。

### 阶段 H：部署、完整验收与交付（1～2 天）

**文件：** `deploy/systemd/*`、`scripts/deploy.sh`、`scripts/backup.sh`、`docs/DEPLOYMENT.md`、`docs/TEST_REPORT.md`、`README.md`。

- [ ] 构建前端；独立 venv 安装锁定依赖；创建系统账号与受限目录。
- [ ] 安装 root 所有且普通账号不可写的 agent 代码、venv、unit 和配置；不从 Web 可写工作目录加载 Python 代码。
- [ ] API 单 worker 运行，agent 以 systemd singleton + 文件锁保证唯一扫描/执行实例。
- [ ] 默认 API 绑定 `127.0.0.1:8000`，通过 SSH 转发测试；如果需要局域网访问，配置 HTTPS 反向代理与 Secure Cookie。
- [ ] root agent 仅暴露 Unix socket，校验 API UID；部署时按实测收紧 capability、文件读写和设备访问，不盲目启用会阻断 NVML 的限制。
- [ ] 初始化核验主/数据目录根、shared 名称与挂载，诊断 quota/ACL/libpwquality/PAM/SSH/日志源；只对测试账号验收生命周期、互访和共享授权。
- [ ] 初次启动只读，采集稳定且规则测试通过后只对测试任务启用终止/期限验收。
- [ ] 验证服务与整机重启恢复、数据库备份恢复、升级迁移和旧版本回滚。
- [ ] 输出实际测试结果、未覆盖项和已知识别边界；交付管理员账号创建方式和运维说明。

**检查：** `ssh wzx-ubuntu 'systemctl status gpupm-api gpupm-agent --no-pager'`；`ssh wzx-ubuntu 'curl -fsS http://127.0.0.1:8000/api/health'`；全套单元、接口和 E2E 通过。

**验收：** 不改变现有 SSH/nohup 工作方式；管理员可完整执行 PRD 第一版路径；只有专用 fixture 被用于真实终止测试；业务配置与操作日志可恢复。

## 9. 测试策略与服务器操作边界

### 9.1 本机规则与模拟测试

- 三级字典序、边界值、用户唯一管理组、默认组迁移。
- GPU 缺失、不支持的指标、重复 PID/多 GPU、采集失败与进程快速退出。
- 同 shell 多任务、独立 launcher、DataLoader、未知 wrapper、跨 UID、手工覆盖。
- PID/start ticks/boot ID 改变；模拟 pidfd 打开前后复用。
- 期限与时区、超时高优先级、保护、并发延期和策略版本。
- 作业幂等、逐阶段崩溃恢复、日志不可写、API/agent 断联。
- 停用/到期/软删除组合、enable/restore 不解除其他原因、首次改密与平台/系统质量策略状态。
- SSH 日志成功/失败/未知用户名、IPv4/IPv6、游标/轮转/去重与覆盖缺失。
- 目录/UID 配额口径、bytes/inode 换算、软/硬限额和宽限、无支持拒绝提交、统计超时与告警去重。
- shared 保留名称、reader/writer/outsider 权限、ACL mask/default ACL、0600 创建限制、私人目录未开放。

### 9.2 Ubuntu 真实进程测试

构造独立 fixture：普通父子树、两项 sibling 任务、忽略 TERM 的子进程、父先退出 worker、父不 wait 的短时僵尸。每次测试生成 manifest，保存所有进程完整身份；销毁仅以 manifest 核验后的身份为目标。

GPU fixture 使用专用小程序申请少量显存并维持短生命周期，依赖放独立测试环境，限制显存与运行时长，不修改现有训练 Conda 环境。探测 NVML 先只读；GPU fixture 启动前重新检查可用显存，资源不足则跳过并写报告，不抢占现有任务。

跨用户能力用独立测试账号和测试进程验证，需要管理员权限；不把当前其他用户的真实任务用于终止测试。僵尸测试通过 fixture 父进程 wait 回收，避免泄漏。

新增生命周期/密码/共享权限测试使用专用账号，核验停用后不能新登录但已有活动保留、恢复不覆盖其他限制、首次改密的交互/非交互表现及共享读写矩阵。quota 的硬限额/inode/宽限等测试在隔离 VM 或专用测试文件系统完成，不通过生产根分区填满、格式化、重挂载验证。测试文件和账号的清理由隔离测试环境管理，业务软件始终只提供用户软删除。

### 9.3 PRD 验收映射

| PRD 要求 | 实现阶段 | 关键证据 |
|---|---|---|
| 全用户 GPU 扫描、设备信息 | B、H | 真实 NVML 与 nvidia-smi 比对、跨用户 fixture |
| 父子树、多 worker、可调整归组 | C、G | 同 shell 两训练分离、DataLoader、人工覆盖恢复 |
| 三级优先级与备注 | A、D、G | `(80,0,0) > (79,100,100)`、修改即时排序 |
| 最大时长、到期时间、延期、取消 | F、G | 起算时间、UTC 转换和策略版本测试 |
| 超时提醒与自动终止、保护 | E、F | 高优先级不豁免、保护跳过、提醒去重 |
| 单进程与整组终止、TERM→KILL | E、G | 正常退出、忽略 TERM、范围预览、逐进程日志 |
| PID 复用与重启恢复 | C、E、F、H | 身份改变拒绝、boot ID、作业恢复 |
| 真僵尸、残留、异常线索 | C、F | Z 状态父关系、历史 worker、低利用率不误杀 |
| 本地用户 CRUD、系统组、默认 bash、目录隔离 | D2、G、H | 两用户实测互访拒绝、组配置、改名/软删除预览、新登录停用、全部文件原地保留、账号恢复与失败恢复 |
| 停用/启用、账号有效期与密码策略 | D3、G、H | 组合限制不误解除、首次改密、双登录路径、已有活动保留 |
| 用量告警与用户配额 | D3、G、H | 统计口径、软/硬/inode、超限拒绝写入、无支持时拒绝提交、软删除统计保留 |
| 登录历史和当前活动 | D3、G、H | 游标/轮转/去重、源 IP/方式、未知用户和历史缺失降级 |
| 团队共享目录 | D3、G、H | reader/writer/outsider 权限、ACL 继承、撤权边界、私人目录仍隔离 |
| 管理员登录与全部页面 | D、G | 鉴权/CSRF 测试与 E2E |
| 操作日志与失败原因 | D、E、H | 前后值、操作者、系统动作、失败和部分成功 |

### 9.4 性能验证目标

这些是待测目标，不是实测结论：默认 5 秒刷新；模拟 1000 个进程/100 个任务时，优先保证扫描完成且不重入；缓存查询接口局域网 P95 目标低于 500ms；实时变化在两个健康扫描周期内可见。

真实服务器记录扫描时长、agent CPU/RSS、数据库增量和 API 延迟，再决定是否调整周期。若扫描超出周期，显示退化并跳过重叠扫描，不开启并发重复执行。

## 10. 部署布局与恢复

| 路径 | 用途与权限 |
|---|---|
| `/opt/gpupm/releases/<version>/` | root 所有的代码、前端构建和 venv |
| `/opt/gpupm/current` | 当前发布版本链接；只有 root 修改 |
| `/etc/gpupm/` | root 配置；API 只读其必要项 |
| `/var/lib/gpupm/api/app.db` | gpupm 账号拥有；业务与会话数据 |
| `/var/lib/gpupm/agent/agent.db` | root 专属；身份历史与执行记录 |
| `/run/gpupm/agent.sock` | root 和受限 API 组可访问，并校验对端 UID |
| journald | 服务诊断日志，不记录密码、Cookie 或完整敏感环境变量 |

升级：一致性备份 → 暂停新的自动动作 → 安装新 release → 执行迁移 → 重启 → 对账和只读健康检查 → 恢复动作。若迁移不能逆向恢复，回滚必须连同迁移前数据备份一起执行，不直接让旧代码读取新 schema。

服务停机时现有 GPU 任务继续运行；恢复后重新核验期限。重启本身不意味着取消已配置期限，但必须完成新鲜采集与策略对账才恢复自动执行。

## 11. 第一版明确边界

1. 不实现资源紧张时自动清理、多服务器统一管理、用户自助延期或 GPU 调度优先级。
2. 不用低 GPU 利用率判定卡死，不自动杀僵尸父进程、不自动重置 GPU。
3. 初版正式支持 NVIDIA 宿主机进程；AMD/NPU 不在范围。Docker PID 可展示，但容器任务边界/容器主进程识别需要额外验证；归属不明时不自动终止。
4. MPS 可能把多个客户端呈现为代理进程，MIG 指标也可能不完整；界面标明不可用，不能把代理当成一个普通用户任务自动清理。
5. 单卡测试平台不能证明真实多卡正确性；多卡解析与归组有模拟覆盖，真实多卡需补验。
6. 管理员操作审计不等于防 root 篡改审计；第一版不建设外部不可变日志系统。
7. 识别无法证明的关系需要人工确认；部署前不存在的关系历史不能凭空恢复。
8. 用户管理仅支持本地普通账号；不提供 sudo/docker 等敏感组赋权、在线目录迁移、任意 UID/GID 修改、LDAP/NIS 或账号/数据永久清理。
9. 配额覆盖本地 ext4/XFS user quota，不提供 NFS/Btrfs/ZFS 或 shared 的 project/group 硬配额；不支持时显示能力状态。配额启用依赖宿主机配置，不能静默退化成告警。
10. 私人目录和共享 ACL 是文件访问规则，不是容器级隔离；停用不停止已有活动，共享撤权不保证已打开句柄立刻失效。

## 12. 实施前需要核对的默认假设

本方案已采用以下默认值，避免在技术细节上阻塞规划：中文界面；默认组/用户/任务优先级 50；扫描/期限检查 5 秒；TERM 宽限 10 秒；不限时且仅提醒；自动残留清理关闭；内网/SSH 访问；所有破坏性验收仅使用独立 fixture；新用户默认 bash/私有主组/0700 私人目录/077 umask，删除用户仅软删除、停用新登录，账号及所有文件原地保留，支持恢复，不结束现有进程/会话；账号默认不限期、创建/重置默认首次改密、不强制定期换密；quota 默认不限额，容量阈值 80%/90%，目录统计默认 15 分钟。

新用户已确认同时支持 SSH 公钥和密码。仍需在相应实施阶段核对：实际 sudo 权限；管理员需要 SSH 转发还是局域网 HTTPS；是否必须管理容器/MPS/MIG；是否能提供真实多 GPU 测试机；有效 SSH/PAM/password-quality 策略、日志覆盖、数据目录实际存储卷与根路径，以及 quota/ACL 支持与启用方式。这些不会阻止本机工程、模拟测试和服务器只读采集阶段。

## 13. 技术依据

- [NVIDIA NVML 官方介绍](https://developer.nvidia.com/management-library-nvml)：设备和活跃计算进程采集能力。
- [NVML Device Queries](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html)：进程、显存和可选利用率接口。
- [NVIDIA Python 绑定 nvidia-ml-py](https://pypi.org/project/nvidia-ml-py/)：安装包名与 pynvml 导入方式。
- [psutil 官方文档](https://psutil.readthedocs.io/stable/index.html)：父子进程、创建时间、僵尸与权限异常。
- [Linux pidfd_send_signal](https://www.man7.org/linux/man-pages/man2/pidfd_send_signal.2.html)、[Python 3.12 signal](https://docs.python.org/3.12/library/signal.html#signal.pidfd_send_signal)：实例句柄与信号发送。
- [SQLite WAL](https://www.sqlite.org/wal.html)：读写并发、单写者与本地存储约束。
- [FastAPI 多 worker](https://fastapi.tiangolo.com/deployment/server-workers/)：worker 是独立进程，需避免在各 worker 重复启动管理循环。
- [React](https://react.dev/)、[Ant Design](https://ant.design/docs/react/introduce/)、[React Router](https://reactrouter.com/start/modes)、[Vite](https://vite.dev/guide/)：前端组件、管理界面、声明式路由与构建工具。
- [TanStack Query](https://tanstack.com/query/latest/docs/framework/react/overview)：服务端数据缓存、查询与 mutation 管理。

- [useradd](https://man7.org/linux/man-pages/man8/useradd.8.html)、[usermod](https://man7.org/linux/man-pages/man8/usermod.8.html)、[userdel](https://man7.org/linux/man-pages/man8/userdel.8.html)、[groupmod](https://man7.org/linux/man-pages/man8/groupmod.8.html)：本地账号、shell、目录、用户组变更和活动账号限制。

- [chage](https://man7.org/linux/man-pages/man1/chage.1.html)、[libpwquality](https://github.com/libpwquality/libpwquality/blob/master/doc/man/pam_pwquality.8.pod)、[sshd_config](https://man7.org/linux/man-pages/man5/sshd_config.5.html)：有效期、密码质量与 SSH/PAM 行为。
- [setquota](https://man7.org/linux/man-pages/man8/setquota.8.html)、[XFS](https://docs.kernel.org/admin-guide/xfs.html)、[setfacl](https://man7.org/linux/man-pages/man1/setfacl.1.html)：配额单位/限额、文件系统能力与 default ACL。
