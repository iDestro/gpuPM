# 第一版实施记录

日期：2026-10-14。分支：`feat/gpupm-v1`。本文件记录已实现内容；完整原计划仍保留未逐项验收的项目，不能据此宣称所有环境和故障组合已覆盖。

| 阶段 | 已实现结果 | 主要文件 |
|---|---|---|
| 工程与规则 | Python/React 工程、锁文件、UTC 期限、三级字典序优先级、数据库与初始迁移 | backend/src/gpupm/domain、db、migrations；frontend |
| 宿主机采集 | NVML、全用户 procfs、boot ID/PID/start ticks 身份、明确的过期/不可用状态 | backend/src/gpupm/agent/processes.py、host.py |
| 任务归组 | 保守父子关联、辅助成员、祖先上下文、历史身份、人工合并/拆分/排除 | agent/processes.py；api/routes/tasks.py |
| 安全终止 | 版本绑定预览、一次性 token、幂等请求、pidfd、TERM/KILL、逐身份结果、重启后核验 | agent/host.py、protocol.py |
| 期限与异常 | 不限时/绝对日期/实际启动起算、提醒/终止、保护、精确策略确认、残留清理、僵尸及持续 D 状态 | agent/host.py、processes.py |
| Web 管理 | Argon2id、会话、CSRF、并发登录限速、业务组与用户优先级、脱敏审计 | api/auth.py、context.py、routes |
| Linux 账号 | bash、密码/公钥、强制改密、主组/附属组、空闲改名、纳管、停用/启用、有效期、仅软删除/恢复 | agent/accounts.py；api/routes/system.py |
| 私人目录 | 可配置根、直接 data_base/用户名、0700/077、~/data、挂载设备核验、保留所有文件 | cli.py、agent/accounts.py |
| 存储与共享 | 后台目录统计、UID/文件系统空间与 inode 配额、读回核验、容量告警、reader/writer/default ACL | agent/storage.py |
| 登录历史 | OpenSSH 成功/失败、IP/方式/指纹、分页筛选、轮转位置与 journal 游标、覆盖声明 | agent/login.py |
| React 界面 | 总览、GPU、任务树/操作、业务组/用户、Linux 账号/组、存储、共享、策略和日志 | frontend/src/pages.tsx、components.tsx、App.tsx |
| 运维 | CLI 管理员初始化、systemd/Nginx 模板、SQLite 一致备份、安装/升级/回滚说明 | deploy、scripts/backup.py、docs/DEPLOYMENT.md |

实现时修复了并发登录计数、重复审计导入、无人打开页面时的心跳、旧心跳错误确认新策略、存储遍历阻塞控制操作、外部登录限制丢失、原生保护被界面配置遮盖、UID 复用、到期显示被内核锁定标记污染，以及运行参数未实际生效的问题。对应回归在测试中保留。

原计划中的预计工期不作为本次完成时间承诺；部分文件职责合并在上述模块中，原计划示例测试文件名由实际 tests/unit、tests/integration 和 scripts 下的验收脚本代替。

验证证据和未覆盖项见 [测试报告](TEST_REPORT.md)。正式部署需按 [部署说明](DEPLOYMENT.md) 确认数据目录所在的真实存储位置，再初始化生产配置及管理员。测试服务器的 `/data` 尚未作为生产根配置；实机写入仅使用独立 QA 目录和账号。

## Linux 权限组管理范围

已实现默认受管权限组与其他只读组分离、普通组明确启用管理、用户私有主组身份保留、human 分类只读、主组/共享引用删除保护，以及账号和共享目录授权选择范围收窄。复用既有预览、版本、一次性 token 和审计流程；已有组关系及备注编辑不引入额外原生授权。两阶段审查、Ubuntu 回归和两个试用入口只读验收通过，详见 TEST_REPORT.md 和 TRIAL_DEPLOYMENT.md。
