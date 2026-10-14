# 第一版测试报告

日期：2026-10-14。测试代码位于 backend/tests、frontend/src/*test.tsx、frontend/e2e 和 scripts。结果对应当前功能分支；这是实现和核心实机验收记录，不是所有故障组合或生产上线认证。

## 环境与结果

| 检查 | 结果 |
|---|---|
| 本机 Python 3.12 后端 | 100 项通过，2 项 Linux 专用检查跳过 |
| wzx-ubuntu / Ubuntu 24.04 / Python 3.12 | 102 项通过 |
| React/Vitest | 20 项通过 |
| Chrome / Playwright 真实 API | 3 条端到端流程通过 |
| TypeScript 与 Vite 生产构建 | 通过；本机及服务器 Node 22 构建通过，单包约 397–399 KB gzip，有体积提示 |
| npm audit | 0 个已报告漏洞 |
| Ruff | 通过 |
| 1000 进程 / 100 任务模拟 | Ubuntu 归组 P95 12.30ms，缓存 API P95 79.61ms；快照 376091 bytes |

性能数字来自 scripts/load_smoke.py 的短时、单客户端合成验收，不能外推为长期并发负载能力。本机相同样本归组 P95 4.35ms、缓存 API P95 26.42ms。

服务器最初使用内部镜像安装依赖，随后通过 PyPI 按 requirements.lock.txt 的固定版本与哈希安装核验，包含 Starlette 1.8.0。开发检查工具与应用依赖分别安装在独立 venv。

## Ubuntu 原生验收

所有账号以 gpupmqa_ 开头，目录限定在 `/var/lib/gpupm-qa`；root 所有测试代码位于 `/opt/gpupm-qa`。没有修改现有训练环境、PAM/sshd 全局策略，未格式化或重挂载生产卷。测试增加了 quota、xfsprogs 及其依赖工具。

- scripts/host_smoke.py：默认 bash；主/数据目录 0700；密码质量；停用、软删除、恢复与启用；原文件内容/属主/权限保留；恢复仍保留独立停用状态；已有测试进程不被删除动作结束；强制首次改密；NVML 读取。
- scripts/access_smoke.py：真实 SSH 密码和公钥登录；077 umask；同组仍不能读取对方私人数据；停用阻止两种新登录；重置后旧密码失效；移除后旧公钥失效；实际共享 writer 写入、reader 读取、reader 禁止写入、无关用户禁止读取。
- scripts/account_policy_smoke.py：原生主组修改及主目录 GID 变化、数据文件 GID 保留；空闲账号改名、目录/文件保留和生命周期不变；外部锁定、nologin、有效期不被启用或密码重置解除。
- scripts/key_expiry_smoke.py：公钥单独创建及真实 SSH；按 UTC 日期到期阻断登录；取消期限恢复登录；无期限停用不显示内核锁定占位日期。
- scripts/quota_smoke.py：只对新建稀疏文件构成的 ext4/XFS loop 文件系统操作。两种文件系统均验证空间硬限额、inode 硬限额、当前超限宽限期和原生读回，测试后卸载这些 loop 挂载。
- scripts/gpu_smoke.py：真实 CUDA 上下文和 16MiB 分配；未知 CPU supervisor 启动的两个 GPU 任务分别归组、共同祖先只显示上下文且保持存活；GPU 主进程与 TERM 抵抗 helper 归组；整组 TERM/KILL 后核验；另一个同用户 GPU 任务保留；不打开浏览器也自动到期处理；运行时 TERM 宽限设置实际生效；原 GPU 进程身份未变化。原进程 PID 为4938、2374928，均未被测试终止。
- scripts/host_api_smoke.py：普通权限 API 连接 root Unix socket；真实 GPU/用户/存储/登录/审计接口；匿名访问阻断；只读配置拒绝原生写操作。
- scripts/systemd_smoke.py、service_http_smoke.py：临时 root agent/普通权限 API 服务；实际 HTTP 登录、CSRF、退出失效和 SPA 路由；首次启动与服务重启均通过。HTTP 只绑定127.0.0.1:18000；验证后停止并移除临时 unit。

测试账号仅软删除，账号、UID/GID、组、目录及文件保留，符合需求；测试镜像与审计也保留供检查。没有执行 userdel。测试密码只在运行内存中使用，项目不保存服务器 SSH 密码、私钥或生产管理员默认密码。

## 回归重点

保留了 PID 身份变化、保护、预览过期/范围变化、幂等、历史辅助成员、人工归组、旧策略心跳、重启后策略未确认、后台扫描不阻塞心跳、改名失败保持限制且阻止后续变更、外部账号限制、UID 生命周期漂移、挂载变化、quota 读回、链接/权限边界、密码脱敏、并发登录和审计去重等测试。

浏览器三条流程覆盖全部页面导航、任务配置持久化/保护，以及用户停用→软删除→恢复时原目录和独立停用状态的保留。组件测试另覆盖公钥单独创建、空闲改名预览、当前配额保持、密码预览脱敏、日志筛选隔离、ACL 诊断、统计等待状态和账号改名恢复保护。

SQLite 备份回归验证提交的 WAL 数据被包含、未提交数据不被包含、备份完整性和0600权限，以及拒绝覆盖旧备份。

## 未覆盖与明确边界

- 未重启整台服务器，避免影响正在运行的训练；没有做长期压力/磁盘填满或完整故障注入矩阵。服务重启已验证。
- 服务器只有一张 RTX 2080 Max-Q。真实多卡、MIG/MPS、容器和特定训练框架的包装器组合未实测；未知包装器只作上下文，必要时人工归组。
- 相同用户名/UID/主目录的外部删除重建若完全发生在两次观察之间，Linux 没有可直接读取的账号代际标识，不能保证识别。已观察的消失/漂移/复用会拒绝沿用旧管理状态。
- 登录覆盖为已读取的 OpenSSH auth.log/.1 和 journal；压缩历史轮转及其他登录源不作覆盖保证。未知用户名失败不关联到现有 UID。
- 共享更新作用于项目根和新建后代 default ACL；不递归覆盖旧文件权限。0600 文件及旧进程持有的组身份/打开句柄遵循 Linux 原生权限行为。
- 宽限期填写值仅调整当前已超软限额用户的期限；将来首次超限使用文件系统统一默认值。留空保留已有宽限期。
- 软件第一版保持完整执行审计；未进行数月审计增长和长期恢复性能验收。
- 正式部署尚未启用。`/data` 的真实挂载/容量、生产管理员与 HTTPS 访问方式需按部署说明配置；测试通过不代表这些环境已经配置。


## human 管理范围增量验收

- Ubuntu 最终后端117项通过；React27项通过（单 worker），Chrome4条流程通过，生产构建与 Ruff 通过。
- 新增回归覆盖非 human 列表默认过滤及 other/all、业务/任务修改拒绝、账号/配额/系统组/共享成员限制、human 分类组禁止共享授权、组移除后的后台策略/排队信号撤销、默认组创建及 primary-group-only 账号改组保留 human、演示旧库迁移保留既有数据。
- 真实服务器 human 组GID1025；指定三个真实账号与项目 QA 账号加入，服务账号留在组外。原有维护账号保护保留。真实试用 allow_mutations=false；演示可修改。
- 更新前两类应用库/agent库一致备份，三个服务重启后 HTTP 登录、默认 human 分类、其他账号查看及 root 元数据修改403通过。
- 实机重新执行 account_policy_smoke.py 与 gpu_smoke.py：新建账号默认 human；改组/改名仍保留 human（后续变更成功即验证 native writable 的 human 校验）；QA GPU 归组、TERM/KILL、兄弟任务与 CPU supervisor 保留、自动到期通过。测试仅操作 QA 账号/进程。当前可见原 GPU PID4938身份保留；本轮 CUDA 验收开始时2374928已不在NVML列表，测试没有向它发送信号。
- 当前实机没有非 human GPU 占用任务；该类禁止修改及撤销信号路径由自动化回归覆盖。未为此启动系统账号的GPU负载。

界面默认状态增量回归：27项前端测试及4条Chrome流程通过，覆盖默认 scope=human/status=running、切换已结束后隐藏运行任务、切回运行中及人员/其他账号文案。生产构建通过，服务器两个入口的新包 index-Du-YVC4A.js 已核验。


## 新建账号自动管理专项核验

新增完整 API 回归：不提交 groups/managed 字段创建账号，响应即 managed=true/is_human=true，human 附属组、同名私人主组、bash 和 home/data 路径均正确；默认人员列表可见，直接预览修改备注并执行成功，无需额外接管。专项 API 1项通过，现有创建/human相关13项回归通过。

服务器以只读方式核对原 QA agent 实例中的12个创建账号：managed=true、human成员、同名私人主组、主/数据目录0700且属主正确、~/data链接正确、.bashrc包含umask077。未新增/修改任何真实账号。

管理标记归属于创建该账号的 agent 管理库。QA验收实例 /var/lib/gpupm-qa/state.sqlite 与试用实例 /var/lib/gpupm-trial/agent/agent.db 独立，试用部署当时遗漏了已管理QA记录迁移。用户截图后已对账导入15个QA管理记录，保留原软删除/停用状态和目标生命周期ID；human成员身份仍仅划定人员范围，不会自动接管其他服务器既有账号。

迁移后真实HTTP专项验收通过：15个QA账号全部已管理/已软删除；默认人员列表3人；截图2账号有效期为空，1970锁定占位日期消失。passwd/shadow和目录属性前后相同，写能力未开启。备份与详情见TRIAL_DEPLOYMENT.md“QA管理记录迁移修复”。


## Dashboard 排版整改验收

32项Vitest、7条Chrome E2E全部通过；类型和生产构建通过，包约403KB gzip，仍有原有体积提示。本轮仅前端，无新增依赖或后端权限变化。

新增浏览器验证：1440×900长审计列表滚到底侧栏/顶栏仍在原位置，默认行高<90px，完整长原因可展开；1280×600菜单独立滚动且内容滚动不影响菜单；375×812导航抽屉、所有六类页面宽表格可横向访问、账号名称不被固定操作列遮挡，页面无横向溢出。组件验证已知状态/审计动作中文化、未知值保留、完整文本焦点/悬停访问、覆盖信息折叠、有效日期与软删除/独立停用并列状态，以及审计成功筛选参数succeeded。E2E命令现在自动构建，避免回归旧静态包。

实机真实host模式浏览器登录、审计/账号/手机视图和滚动截屏通过；静态包在18000/18001均核验。15个QA已管理/软删除状态保持，未执行原生写操作。未实测Safari/Firefox或全部手机机型。

参考：[shadcn-admin](https://github.com/satnaing/shadcn-admin)、[Tabler](https://github.com/tabler/tabler)。借鉴布局和信息层级，继续使用项目原AntD组件，无框架迁移。

## 编辑弹窗关闭修复

复现修改任务后点击取消或右上角关闭没有确认弹窗：共享EditDialog使用的AntD静态Modal.confirm在React19下失效，改为现有Modal.useModal并渲染contextHolder，无新增依赖。兼容性说明见[AntD官方文档](https://5x-ant-design.antgroup.com/docs/react/v5-for-19)。

35项Vitest、7条Chrome E2E及类型/生产构建通过。新增覆盖未修改时取消/关闭立即退出，已修改时继续编辑保留草稿、放弃修改退出且不保存。真实18000入口浏览器重复验证取消、右上角关闭、继续/放弃及再次打开后的取消，任务PATCH请求为0，原备注保持不变。

## 任务别名与原始名称

列表显示任务别名，悬停/聚焦显示只读原始名称；编辑字段改为“任务别名”，详情同时展示两者。agent在发现任务时保存original_name，名称配置仍使用既有name字段。旧host记录从保留的GPU成员命令恢复；已结束且无成员的旧记录无法可靠恢复，显示未知。完整命令仍在进程详情中保留。

后端本地118项通过、2项Linux专用跳过；Ubuntu120项通过；Ruff通过。新增回归覆盖两次别名编辑、agent重启、host采样/结束保留原名、旧记录回填和无法恢复的情况，进程成员不变。36项Vitest和7条Chrome E2E通过，类型/生产构建通过；别名保存后列表hover显示原名、详情两者可见，保护和未保存取消继续通过。

两个实机试用入口分别验证HTTP原名字段、列表hover、详情原名和任务别名编辑字段；未保存任何任务配置。截图为本地.runtime/preview/task-original-hover-18000.png、task-original-hover-18001.png。未测试Safari/Firefox。
