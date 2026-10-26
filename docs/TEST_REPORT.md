# 第一版测试报告

> 当前验收结论见 [ACCEPTANCE_STATUS.md](ACCEPTANCE_STATUS.md)。本文件保留历史记录；早期待办和失败应结合后续结果阅读。

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

## 最大运行时间输入优化

任务及全局默认最大运行时间采用时/分/秒输入，提供30秒、1分钟、30分钟、1小时、4小时、24小时和不限时快捷按钮。沿用秒值API；表单初值/提交边界转换，清空传null。显式0、负数、非整数、分秒超范围或总时长超过315360000秒不允许保存。任务帮助说明从启动时刻计算。表单帮助改用extra，避免覆盖校验错误；编辑弹窗居中并限制body高度，在小屏幕内滚动。

43项Vitest、7条Chrome E2E及类型/生产构建通过。新增覆盖3661秒回显、混合时分秒换算、秒/小时快捷、清空/不限时null、0和总时长上限校验；浏览器保存24时2分5秒后API返回86525且重开精确回显，再不限时返回null。默认全局时长控件和未保存取消确认通过；375px编辑弹窗关闭按钮及时间输入位于可视范围。

实机18000/18001分别验证快捷、0秒错误提示及改正后提示清除、手机可视弹窗、全局默认控件。两入口PATCH请求均为0，任务时限前后相同。截图为本地.runtime/preview/runtime-input-18000.png、runtime-mobile-18000.png及对应18001版本。本轮仅前端，未重复后端/原生GPU终止测试；Safari/Firefox未测。

## 任务仅设置最大运行时间

任务编辑移除指定到期时间输入，详情的自动计算deadline_at更名为预计结束时间。保存任务显式发送expires_at=null，旧独立期限随保存清除；未编辑的历史记录仍保留原配置，后端字段兼容性保持，不自动迁移真实任务。

44项Vitest、7条Chrome E2E及类型/生产构建通过。新增组件验证无截止时间输入、只读预计结束时间及保存旧任务时expires_at=null。浏览器先设置旧绝对期限，再用最大运行时间保存，核验旧期限清空、截止时间精确等于启动时间加86525秒；不限时及取消流程仍通过。

实机两个入口核验无datetime-local输入、最大运行时间控件及预计结束时间文案。只操作草稿并放弃，PATCH请求0，原max_runtime_seconds/expires_at保持。无后端或原生配置修改；未重复GPU终止验收，Safari/Firefox未测。

## 全平台中英文国际化

全平台固定界面文案（登录/导航/抽屉、总览、任务与详情、业务策略、账号/系统组、存储/共享、登录记录、设置、审计及共用弹窗）支持zh-CN/en-US。React语言store订阅变化，localStorage记忆并同步跨标签页，AntD locale、document lang/title和显示时间格式同步；时区保持Asia/Shanghai。无新增依赖。中文必要字段提供专业英文术语hover/focus提示，点击聚焦可检查；设置字段可读化，秒值精确显示，不限时与无数据区分，初始化目录/模式只读。账号名、别名、命令、路径、原始审计JSON和服务器诊断保留原文。

规格审查修复浏览器标题、HTTP兜底错误随语言变化、实际quota/Shell术语键遗漏；规格复审及独立质量审查通过。57项Vitest通过，最新10条Chrome E2E、类型/生产构建通过；设置最终竖向布局另2项组件回归通过。覆盖中英全部页面、语言刷新记忆、非法偏好及存储不可用回落、未知/原型键不翻译、凭据/草稿保留、英文继续/放弃、原始错误不修改、精确5秒/3661秒与路径保留、英文375px导航/无横向溢出。E2E共用经过服务端验证的测试会话，避免新增语言流程触发真实登录频率限制，未修改限流实现。

实机18000/18001分别核验英文登录、页面切换、刷新记忆、SIGTERM grace period悬停、英文编辑/取消/草稿、原始任务名称/别名及手机导航。PATCH/PUT/DELETE请求均0，策略配置前后完全相同，任务别名/时限保持。截图发现英文长路径挤压说明后改为标签在上、值/说明在下；最终真实长路径卡片高度366px，两入口重新核验且截屏通过。截图为本地.runtime/preview/i18n-settings-zh-18000.png、i18n-settings-en-18000.png、i18n-mobile-18000.png及对应18001版本。

本轮仅前端展示，不重复后端/GPU原生终止验收。Safari/Firefox与真实手机硬件未实测；手机布局用Chrome375px模拟，未知服务器诊断保留原文供展开查看。

## 新任务默认策略

策略配置新增分组模板：默认最大运行时间30分钟、默认人工保护关闭、默认任务优先级50、默认到期动作仅提醒、默认残留worker清理关闭；中英文同步，中文专业术语可悬停。编辑仍使用时/分/秒快捷控件。模板仅在首次发现任务ID时复制，计时起点是进程启动；既有任务、重启后的任务和逐任务覆盖不被修改，系统/服务/维护账号保护与当前human范围检查仍优先。

后端本地169项通过、2项Linux专用跳过；Ubuntu171项通过，Ruff通过。新增覆盖旧配置补缺保留显式null/自定义键、新旧任务及重启、四类强制保护、API/root严格布尔/整数范围验证及失败不写入。前端60项Vitest、11条Chrome E2E和类型/生产构建通过；新增覆盖false/0/null、可编辑字段精确提交、只读键排除、保存/刷新回显及全局模板保存不覆盖既有任务。独立规格及质量审查均通过。

真实18000与演示18001部署前后核验全部已有任务（10/2个）的名称、身份、启动时间、优先级、保护、时限和到期/清理策略保持；仅PATCH全局默认设置，无任务PATCH。三个服务active，root原生写权限仍关闭。两入口实机Chrome验证中英文、语言刷新记忆、英文保护术语、30分钟/false/50表单回显与取消、375px弹窗关闭及无页面横向溢出，界面验证PATCH/PUT/DELETE均0，配置保持。截图位于.runtime/preview/defaults-{zh,en,mobile}-{18000,18001}.png。

未重复真实GPU终止验收，未实测Safari/Firefox及真实手机硬件。本轮默认到期仅提醒；30分钟从进程启动计算，首次发现时已运行超过30分钟的新任务会立即标为超时。

## 收尾状态、残留提醒与手动清理

实现运行中→收尾中→待清理→清理中→已结束；正常worker自行退出可从收尾中/待清理直接结束。主进程首次确认退出时记录收尾时间，跨采样/重启保留；默认提醒开启，默认等待5分钟，任务及新任务模板均可按时/分/秒配置（1–86400秒，不可不限时）。等待结束且无GPU成员、采集完整、人员账号无保护时才提醒管理员；不代表进程一定可以安全终止。旧自动清理开关保留API兼容但不再触发后台信号，收尾worker也排除超时自动终止。默认列表显示全部未结束状态。

后端Ubuntu全量197项通过，Ruff通过。新增24项残留专项回归及API/默认值回归，覆盖时钟边界、正常退出、实际重启、提醒关闭、真实超时及已确认旧策略仍不自动清理、GPU恢复、采集失败/权限不足/身份或PPID漂移、损坏leader信息、预览范围变化、排队后账号/保护/UID/PID变化、TERM后GPU恢复阻止KILL、已排队到期操作遇到收尾不发送信号、以及中断/结束的清理操作在采集失败时退出清理中。原生pidfd发送前核验当前UID/人员资格；注入信号器与伪采集数据验证危险边界，不对真实训练进程发送信号。

前端完整68项/10文件通过（`npm test -- --maxWorkers=2`），最终构建/类型检查和13条Chrome E2E通过。回归验证可选最大时长与必填等待时间的范围/不限时差别、false值保存、残留意图绑定预览token、原因必填、取消不执行、精确worker手动终止/其他任务不变、默认活动状态保留、清理完成从默认列表消失、queued操作轮询及中英文。E2E使用一次性演示数据库中的独立leader990000/worker990001，不修改生产演示种子。375px英文任务详情及预览发现换行/表格溢出后修复；完整信息通过悬停/聚焦保留，预览表格内部横向滚动，弹窗内容内部滚动。规格与独立质量审查均通过。

两实机入口18000/18001核对新默认值、术语、表单5分钟回显/无不限时/放弃草稿、默认active筛选、中英刷新记忆、375px无页面溢出与关闭按钮可达；界面验证PATCH/PUT/DELETE均0，配置保持。截图为.runtime/preview/residual-settings-{zh,en}-{18000,18001}.png和residual-mobile-{18000,18001}.png。部署前10个真实任务及2个演示任务旧策略字段逐项保持；部署后全局提醒设置不改变当前12个真实任务/2个演示任务的既有策略。

未实测Safari/Firefox、真实手机硬件或对真实GPU训练执行清理。执行期间成员/版本变化会保守跳过并返回partial，剩余进程需要重新预览确认；待清理是人工检查提示。

## 任务监控程序白名单

预置/usr/lib/xorg/Xorg及/usr/bin/Xorg，策略配置可编辑完整路径或显式清空。精确匹配原生exe，不按账号/进程basename/命令参数推断ML类别。命中程序不进入任务列表/详情/任务计数、超时/残留提醒或终止范围；历史元数据/策略/审计保留，可随白名单移除恢复观察。同用户训练与混合任务的非白名单成员继续采集；完整原生leader身份保留，避免忽略桌面主进程后误判正常子进程为残留。GPU设备指标和账号活动不排除白名单占用。

Ubuntu后端全量228项通过，Ruff通过。新增回归覆盖默认/旧配置/显式[]及重启、严格路径和API/root边界、nativeexe优先于伪装argv、参数/相似名称不误匹配、新旧记录/混合成员/活跃leader、指标保持、采集失败仍排除已有白名单成员、预览/排队权限撤销、相同心跳不撤销token，以及发送信号前exec变化阻止原生信号。

前端70项/10文件通过（串行npm test -- --maxWorkers=1）；最终14条Chrome E2E、类型/构建通过。新增组件测试先失败后通过，覆盖中英路径/术语、空数组保存和只写settings；浏览器追加路径、刷新、清空、恢复与训练任务策略/成员保持。375px补充检查采用poll等待布局稳定，弹窗动画期间的瞬时宽度不能代表持续溢出；最终专项检查通过。两入口实机中英、专业tooltip、追加后放弃草稿、手机完整路径/关闭/取消核验，PATCH/PUT/DELETE均0，配置保持。截图.runtime/preview/allowlist-{zh,en,mobile}-{18000,18001}.png。

实机Xorg PID4938部署前后boot_id/start_ticks相同且仍运行；其1个任务记录从真实API隐藏（12→11），独立详情404，其余11个任务旧策略字段保持。演示2个任务保持；GPU设备身份/总容量与占用指标仍返回，原生写权限仍关闭。未对真实训练进程执行信号测试；无法核验exe的旧已结束记录保留，不从显示别名推断。Safari/Firefox/真实手机未实测。

## 桌面侧栏折叠

桌面侧栏支持224px展开/64px图标模式，顶栏提供中英折叠/展开按钮、aria-expanded/controls；复用AntD Sider和inline Menu，图标悬停展示本地化菜单名称，选中路由及分组顺序保持。浏览器localStorage保存gpupm.sidebar.collapsed，读取非法/不可用值回落展开、写入失败仍可切换。折叠品牌仅G及UTC+8，菜单宽度限制在侧栏内，独立滚动保持。手机导航始终完整菜单，不继承桌面图标模式。

新增浏览器测试先失败（折叠按钮不存在），实现后完整16条Chrome E2E、类型/构建通过。覆盖224→64/内容变宽/当前页面保持、图标中英Tooltip/跳转、刷新记忆、Enter键展开、存储不可用、短屏菜单及内容独立滚动、桌面折叠后375px手机抽屉仍完整及无页面溢出。独立源码审查通过，无新增依赖或API字段。

18000/18001两个实机入口验证中英文、刷新、键盘、1440px桌面、1280×480短屏所有菜单可达、375px完整抽屉，折叠菜单无横向滚动；截图等待动画稳定后检查。PATCH/PUT/DELETE均0，策略配置前后相同。截图.runtime/preview/sidebar-collapsed-{zh,en}-{18000,18001}.png及sidebar-mobile-{18000,18001}.png。

本轮只更新前端静态包，未重跑后端或未改动的组件单元测试；Safari/Firefox和真实手机未实测。浏览器禁止存储时折叠仍可用，跨刷新记忆不可用。

## 侧栏图标语义与重复整理

检查全部11个菜单，继续使用统一AntD线框图标。Linux账号单人/User、系统组多人/Team保留；业务优先级组改为OrderedList排序列表，用户业务策略改为Solution人物+文档。存储改Hdd硬盘，共享改ShareAlt共享连接，SSH登录记录改History历史时钟，操作审计改FileSearch文档检索；总览Dashboard、GPU任务Cluster进程组、设置Setting保留。11个图标不重复，名称/路由/分组/折叠逻辑未变。

类型/构建及16条Chrome E2E通过。两个入口实机检查11个菜单及SVG类型各11个且唯一、中英图标提示、224/64px折叠和刷新、短屏菜单、375px完整手机抽屉；截屏确认显示效果。PATCH/PUT/DELETE均0，策略配置前后同值。截图沿用.runtime/preview/sidebar-collapsed-{zh,en}-{18000,18001}.png和sidebar-mobile-{18000,18001}.png，已更新为新图标。

仅展示调整，无新增依赖或后端修改；未重跑后端/无关组件单测，Safari/Firefox未实测。

## Linux 权限组管理范围收窄（2026-10-14）

默认仅展示受管普通项目权限组；其他系统组、敏感组、human 及用户私有主组进入只读视图。已有普通项目组可明确预览并启用管理，仅登记管理记录，不执行原生成员修改。组引用分别显示附属成员、主组账号及共享项目；任何引用都会阻止删除。账号及共享目录选择器同步收窄，现有只读账号关系及仅改备注的旧共享 ACL 保留。

验证覆盖：GID 身份冲突、严格且独占的 managed=true、预览/版本/引用范围变化、删除 RPC 禁止夹带其他组修改、未管理及保护/非人员账号边界、账号和组成员双向演示同步、原私有组生命周期与自己的主组恢复、共享 ACL 双方校验、旧演示数据补缺、组选择器冷加载、编辑表单版本字段隔离。

- Ubuntu 后端全量：269 项通过；Ruff（backend 及浏览器服务 fixture）通过。
- 前端：全量 77 项通过；随后新增编辑回归，最终权限组专项 8 项通过，累计覆盖 78 项。类型检查和生产构建通过。
- Chrome 全量：17 条通过。后续增强权限组专项，创建/启用管理/编辑确认保存、1280/1440px 横向滚动归零后操作按钮完整可见均通过；操作列固定在右侧，手机继续内部横向滚动。
- 两个实机入口：中英文、默认/其他范围、组名搜索、私有组只读、账号私有身份字段及 375px 页面边界检查通过；浏览器写请求为 0，设置值前后相同。
- 真实库存：109 个组，3 个受管项目权限组、106 个其他只读组，15 个私有主组；演示库存 3 个组均在其他只读视图，2 个私有主组。测试 fixture 未进入试用数据库。
- /etc/passwd 与 /etc/group 的 SHA-256 升级前后相同，三服务 active，原生写能力保持关闭。

未对真实 Linux 账号、组成员或 ACL 执行写入验收，也未测试其他浏览器。旧管理记录缺少历史 GID 时，只能在首次观察时绑定，不能追溯判断此前发生的组重建，正式启用写能力前仍须核对旧记录身份。

## 2026-10-15 当前实例原生验收脚本（执行计划）

本节记录可执行验收方法，不代表已在服务器通过。使用现有运行中 agent 的 Unix socket；不启动第二个 AgentService、不复用历史 QA 用户，也不接触 gpu_trial 或其他现有账号密码。旧 `access_smoke.py`、`quota_smoke.py`、`key_expiry_smoke.py` 是历史隔离验收工具，不用于本轮当前实例验收。

在仓库根目录，用服务器已安装项目依赖的 Python 执行（将 `/path/to/python` 替换为部署虚拟环境 Python）：

```sh
sudo env PYTHONPATH=backend/src /path/to/python scripts/native_ssh_acceptance.py --socket /run/gpupm-trial/agent.sock --output /root/gpupm-ssh-evidence.json
sudo env PYTHONPATH=backend/src /path/to/python scripts/native_storage_acceptance.py --socket /run/gpupm-trial/agent.sock --checks acl --output /root/gpupm-acl-evidence.json
sudo env PYTHONPATH=backend/src /path/to/python scripts/native_storage_acceptance.py --socket /run/gpupm-trial/agent.sock --checks quota --mount /actual/prepared/mount --output /root/gpupm-quota-evidence.json
```

- 先由管理员核实并配置真实新账号 home/data/share 根目录及配额卷；`--mount` 必须是已存在的 ext4/XFS **精确挂载点**，且 root 所有、不可由普通用户改写。脚本不执行格式化、挂载、重挂载、重启或旧目录迁移。配额未启用时失败，不降级为模拟通过。
- SSH 只连本机 `127.0.0.1`，可指定 `--port`。客户端忽略用户 SSH 配置及现有私钥，临时 known_hosts 对本机首次连接使用 accept-new。需要 OpenSSH 客户端/服务端及可用的密码与公钥认证。脚本设置 `LC_ALL=C` 并通过 `SendEnv=LC_ALL` 请求服务端使用英文；服务端不接受该变量时也支持中文 PAM 当前/新/确认密码提示及成功消息，其他未识别提示将带脱敏诊断安全失败。
- SSH 使用两个唯一临时账号，分别通过密码、公钥交互登录完成首次改密。每个账号改密前验证两种认证的非交互命令和 SFTP 被拒绝；改密后验证两种认证的命令、SFTP、umask 077，旧密码失效和私人目录 0700/跨用户拒绝。PTY 有 45 秒截止时间，普通子进程 30 秒超时。
- ACL 使用当前实例创建的三个账号、两个受管项目组和共享目录。验证 writer 新建嵌套目录/文件及写入、reader 继承读取但不可写、outsider 拒绝、撤销 reader 组成员后的新进程失去访问，以及私人 home/data 隔离。既有运行进程的补充组不会被脚本强制刷新或终止。
- 配额使用独立新 UID，在指定挂载点创建唯一 0700 测试目录，通过 agent 预览/提交策略，直接只读 quotactl 与 agent 回读交叉验证。分别验证字节及 inode 的软限制宽限、当前超额的 3 秒期限及到期后在硬限制以下拒绝写入，最后验证硬限制。单次写入最多 1 MiB，只创建少量文件；不会修改文件系统全局 grace。结束时清除此新 UID 的测试配额。
- 成功或失败均尝试通过 agent **软删除本次账号**，保留账号目录、数据和共享测试文件。项目组/共享记录也保留用于审计。私钥、askpass 和 known_hosts 位于 0700 临时目录，退出时移除。不会打印密码、私钥、原始 PTY 转录或原始命令错误；SSH 失败诊断仅保留去除凭据及终端控制字符后的有界尾部、提示阶段计数及退出/超时原因。初始 SSH 拒绝必须包含密码过期证据；SFTP 使用 DEBUG1 验证对应认证方式已经成功且未返回工作目录，并要求紧邻的同账号同认证方式 SSH 已确认密码过期。单独连接关闭、连接失败和普通认证失败不算通过；JSON 包含检查名、实际账号路径、保留资源和清理错误，`--output` 以 0600 新建且拒绝覆盖。
- 若进程被 SIGKILL、断电或 agent 不可用，finally 无法保证完成；检查 JSON 的 `requested_fixture_names` / `cleanup_errors`，只对该次明确列出的 QA 身份做受控软删除。不得按前缀批量操作其他历史账号。

无需 root、网络、SSH 或 quota 的离线脚本自检：

```sh
PYTHONPATH=backend/src:scripts backend/.venv/bin/python -m unittest scripts/test_native_acceptance.py
```

该自检验证完整/分段 PAM 提示、真实本地 PTY 交互成功与失败、密码预览脱敏、身份变更拒绝、清理范围、错误报告脱敏、配额短写后继续探测 EDQUOT，以及只读用户不得修改既有文件；不能替代上述服务器验收。

## 2026-10-15 专用工具完善：集成阶段

- 账号创建采用持久化恢复记录；在用户、目录、凭据和登录释放步骤注入中断，核验身份/目录锚点、凭据不落预览、完整初始化前不开放登录。仅公钥恢复不强制不可完成的密码更新。
- 健康接口公开真实写入能力和初始化核验结果。配置页目录来自 agent；agent 不可用时，已有快照标记过期而非伪造可写状态。
- 变更预览显示修改前后；账号限制、恢复入口及操作错误使用结构化中英文提示。
- 首轮前端全量：89 通过、2 个测试入口缺少 QueryClientProvider；修正对应真实应用入口后，相关文件 5 项通过。浏览器完整 19 项通过；最终 UI 修订后相关 11 项再次通过。构建通过。
- 首轮 Ubuntu 后端：305 通过、1 个旧健康接口精确断言失败；更新新增字段断言后，相关 Linux socket/进程测试 2 项通过。最终集成全量结果待下方追加。
- 新存储守卫测试确认：挂载设备/类型/mount ID 改变后，旧配额预览不能执行；共享目录写入前核验配置设备。
- 原生验收脚本离线自检 12 项通过。原生 SSH、ACL、配额实机结果必须另行记录，不能用本段离线结果替代。
- 升级验收工具仅在私有数据库副本上演练前版/新版/回退读取和初始化、持久配置保留及备份恢复；明确不宣称整机重启、原生账号回退或依赖包升级已验证。

### 实机集成结果补充

- Ubuntu 最终完整后端回归：**319 passed / 32.52s**（包括 Linux socket/进程以及隔离备份恢复测试）。
- 最终前端回归 92 通过，2 个断言/运行期间翻译改动问题；冻结源文件后完整 `app-i18n` 与 `components-i18n` 两文件 **11/11** 通过，保留原始错误诊断检查。最终构建通过。完整浏览器 19/19、后续相关 11/11 通过；部署后真实/演示网页只读验收均通过。
- 隔离数据库升级/回退/恢复：使用本次停服务期间备份，原始备份逻辑内容不变、恢复一致、持久业务/账号/组/策略数据保留，`release_rehearsal=true`。报告见部署备份目录。
- 当前实例 ACL **13/13** 通过，包含只读成员不能改写既有文件、撤权后的新进程不可访问、0700 目录隔离。测试账号软删除且文件保留。
- SSH 首次改密矩阵未完成，早期超时及 SFTP 缺少明确诊断不计通过；原生配额当前实例仍待准备数据卷，不以离线测试代替。

### SSH/PAM 最终实机结果

- 首次超时定位为验收脚本只识别英文，而服务器 PAM 输出“当前的密码：”。应用认证、强制改密限制均正常；只修改验收脚本的语言传递和中英文提示解析。
- 修正后实机 **24/24** 通过：密码和公钥两种交互入口，各自验证首次改密前命令/SFTP受限、改密后密码/公钥命令与SFTP可用、umask077、旧密码失效，以及主/数据目录0700和跨用户访问拒绝。
- SFTP受限证据要求已成功以指定方式认证、同账号同方式 SSH 明确提示密码到期、SFTP无目录结果且失败；单独“连接关闭”不算通过。
- 最终报告：`/var/lib/gpupm-trial/native-ssh-readiness-v4-1791998569.json`，清理无错误。两个最终测试账号已软删除，文件保留，既有 gpu_trial 未用于测试。
- 验收脚本离线自检最终 **19/19**，包含分片中文UTF-8提示、凭据脱敏、短写配额检测和共享既有文件只读检查。

### 续轮收尾验证（源码冻结后）

- 前端完整回归：**13 个文件、94/94 项通过，161.77s**。这是前述失败断言修正后的完整结果，不再只依赖定向补测。
- 单实例启动核查发现 `AgentService` 在获取独占锁前执行数据库恢复，已改为先获得锁再初始化。新增回归先失败后通过；Ubuntu 单实例与传输相关测试 **3/3** 通过。
- 在真实服务已持锁的情况下，以禁止初始化存储的替身调用新启动流程，确认收到锁冲突且初始化调用次数为0，未触碰实际数据库或现有 socket。
- 已备份并部署启动顺序修复：`/var/lib/gpupm-trial/backup-singleton-1791999380667280977`。agent 实际重启成功，agent/API/demo 均 active；健康接口正常、写入开启、目录核验通过。未做整机重启。
- 数据卷仍无选择结果；只读复核 `/data` 不存在、根分区无 user quota。实际存储初始化及配额验收继续待定。

### 2026-10-15 系统盘 /data 配置验收

用户选择直接使用系统盘 /data，并将涉及根文件系统修改/重启的配额启用留待维护窗口。本轮按此明确范围执行，未创建100GiB文件卷。

- agent/API 配置读取均为 home_base=/home、data_base=/data、share_base=/data/shared；UUID设备校验和服务启动依赖已配置，服务重启后健康检查通过。
- 既有账号及48个已记录目录的身份/权限核对未变；旧数据未迁移。
- 新根目录上的 ACL **13/13** 通过，报告 `/var/lib/gpupm-trial/native-acl-system-data-1792027081.json`。实际测试目录 `/home/gpupmqa_*`、`/data/gpupmqa_*`、`/data/shared/gpupmqa_*`。
- 新根目录上的 SSH/PAM/私有隔离 **24/24** 通过，报告 `/var/lib/gpupm-trial/native-ssh-system-data-1792027081.json`。两组验收均无清理错误，测试账号软删除并保留文件。
- 根 ext4 用户配额仍未启用，未执行限额/宽限期实机验收；维护窗口尚未确定，不宣称已完成启用。
- 部署后真实网页只读验证通过：设置页显示 `/home`、`/data`、`/data/shared`，存储页显示“尚未启用”配额；无页面异常、无业务写入。

### 启动修复后的完整后端回归与验收索引

Ubuntu 完整后端 **320/320，32.75s** 通过，日志 `.runtime/readiness-ubuntu-post-singleton.log`。执行前后核对服务器测试副本与本地：全部 backend/src 和 backend/tests Python 文件一致；scripts/test_native_acceptance.py 存在副本差异，因此本次 pytest 不用于更新原生脚本自检结论。三个部署服务均 active。本轮没有修改运行代码、配额或用户数据。

新增 [当前验收状态](ACCEPTANCE_STATUS.md)，按需求映射测试、实机证据和未验收边界；历史待办保留但明确标记为历史记录。配额继续等待用户指定维护窗口，未标记全目标完成。

### 原生验收脚本副本对齐

已同步服务器测试工作区的 `scripts/test_native_acceptance.py`，使用部署虚拟环境重新执行离线自检，**19/19** 通过（0.218s），日志 `.runtime/native-acceptance-selfcheck-final.log`。仅更新测试副本，不修改部署应用、真实账号或文件系统配置。当前配额启用与原生限额验收仍等待维护窗口，不能以此自检替代。

## 2026-10-15: quota removal (current user-approved scope)

Disk quota management and its maintenance gate are removed. Directory usage, capacity/inode alerts, private isolation and group/ACL sharing remain. Removed API/schema/RPC/native quota calls and polling; legacy quota snapshots are discarded. Tests verify removed endpoints (404/405), unsupported host RPCs, legacy snapshots and no quota requests from the account UI.

- Ubuntu backend: 315 passed / 32.27s (`.runtime/quota-removal-ubuntu.log`).
- Frontend: 13 files, 92 passed / 176.34s (`.runtime/quota-removal-frontend.log`).
- Chrome full E2E: 19 passed / 43.9s (`.runtime/quota-removal-e2e.log`).
- Native acceptance driver offline checks: 17 passed; obsolete quota-only checks removed, ACL/SSH helpers preserved.
- Typecheck/build, Ruff and diff checks passed. Historical bundle-size warning remains.
- Backup/deployment: `/var/lib/gpupm-trial/backup-remove-quotas-1792029699698874711`; isolated release rehearsal passed. Agent config, passwd/group and recursive shared-directory ACLs unchanged.
- Actual host/demo browser checks: both 18000/18001, deep links, refresh, Chinese/English and 375px width; zero business writes, zero quota requests, zero page errors. API storage has no quota fields; OpenAPI has no quota endpoints. Three services active; root mount still `rw,relatime`.

No host reboot, native quota enablement, file migration, or training termination was performed. Prior quota results are historical, not outstanding deliverables. Long-load, full hardware combinations and non-Chrome browsers remain outside the evidence established here.

## 2026-10-15 存储与团队共享专项整改

- 存储页改为容量卡片、结构化告警/共享用量、搜索/排序/生命周期筛选；默认未软删除账号。共享页补齐当前组成员、权限说明、路径复制、缺组引导、创建位置、搜索与采样状态；完整中英文。
- 共享创建异常注入验证空目录可清理重试、非空文件保留并收紧访问、已有目录和替换目录不删除；ACL回读验证实际权限和默认继承；编辑失败产生需复核状态和新版本；OSError转为可审计DomainError。后台采样不持有进程控制锁。
- Ubuntu最终全量 **323 passed / 33.30s**，`.runtime/storage-experience-ubuntu-release.log`。
- 前端全量 **95 passed / 169.63s**，`.runtime/storage-experience-frontend.log`；相关20项再次通过，最后默认筛选/列宽调整相关3项通过。
- Chrome全量 **20 passed / 45.2s**，`.runtime/storage-experience-e2e.log`；最后共享创建-预览确认-备注修改-刷新-中英文-375px流程再次通过。
- 构建/类型检查、Ruff和diff检查通过。未增加依赖；原有bundle大小提示保留。
- 当前实例原生ACL **13/13** 通过，`/var/lib/gpupm-trial/native-acl-storage-experience-20261015.json`。writer/reader/outsider访问、既有文件只读、继承、撤权后新进程及0700私人隔离通过。账号1032/1033/1034已软删除，文件保留，cleanup_errors=[]。
- 真实18000与演示18001网页只读检查均通过：中英文、1440px/375px、搜索入口、容量显示、无默认原始JSON、成员展开、创建弹窗与取消，无业务写请求/无页面错误。首次与原生验收同时执行时冷缓存超过5秒，等待采样完成后通过；不将等待中的空统计当作零容量。
- 截图 `.runtime/preview/storage-new-{18000,18001}.png`、`shares-new-{18000,18001}.png`及对应mobile和创建弹窗已实际查看；修正单文件系统卡片空白、固定操作列遮挡和默认历史账号干扰。

完整部署备份：`/var/lib/gpupm-trial/backup-storage-experience-1792031368302101701`，布局补充备份：`/var/lib/gpupm-trial/backup-storage-layout-1792031579317565714`。数据库隔离升级/回退/恢复演练通过，配置和既有passwd/group/共享ACL一致。未重启主机，未迁移或删除原有数据。

未做Safari/Firefox、真实手机及大目录压力测试；成员展示以组配置为准，既有会话/历史文件权限可不同。进程被强杀或断电留下的未知目录需管理员检查，不自动递归清理。

最后异常映射补丁备份：`/var/lib/gpupm-trial/backup-share-errors-1792031772859995577`。部署后 storage.py SHA-256 与已测试本地源码一致，agent/API/demo 均 active，健康接口 status=ok、root_readiness.ready=true。

### 2026-10-15 手动目录用量刷新

- Ubuntu 后端全量 328 passed；最后调整未采样共享目录的未知值后，相关后端 124 passed。
- 前端串行全量 96 passed（14 文件）；初次并行运行因超时失败，串行复跑通过。
- Chrome 共享项目及手动刷新 E2E 1 passed，覆盖英文按钮、完成时间与 375px 布局。
- 测试覆盖页面与定时采集不遍历目录、并发刷新去重、完成和失败重试、目录时间戳保留、登录及 CSRF。
- 构建、Ruff、git diff --check 通过。
- 已部署 wzx-ubuntu，备份 `/var/lib/gpupm-trial/backup-manual-storage-1792033068249608376`。隔离升级演练通过，原系统配置、账号及共享 ACL 未变。
- 部署后真实站点只读验收与演示站点手动刷新通过，桌面/375px、中英文无页面错误；真实站点读取前后 scanning=false，目录统计时间不变。
- 未做百万小文件压力测试，也未在验收中主动全盘扫描真实用户目录。手动扫描仍可能增加磁盘 I/O。

### 2026-10-15 共享目录按成员授权

- Ubuntu 后端全量 341 passed（`.runtime/share-members-ubuntu-release.log`），覆盖角色校验、去重、身份漂移、专用组冲突、降权/撤销、失败限制权限、旧组/文件保留、旧路径不误写同名目录。
- 前端 98 passed / 15 文件（`.runtime/share-members-frontend-final.log`）。成员默认只读、读写切换、移除、中英文及无需预建组通过。早期用例点击了控件隐藏 input，已改为点击真实可见权限标签并断言选中状态。
- Chrome 全量 20 passed，最后布局改动后共享流程 1 passed；覆盖创建→授权预览→执行→备注修改→刷新→英文→375px。
- 当前服务器原生权限 18/18，通过实际非特权进程验证继承读写、只读拒写、撤销、升降权、内部组不可另行授权、跨项目隔离和私人目录隔离。报告 `/var/lib/gpupm-trial/native-share-members-20261015.json`。
- 原生测试账号 1035–1037 已软删除，清理错误为空；文件与两个测试共享目录保留。
- 构建、Ruff、git diff --check、验收脚本自测 17 项通过。已部署，备份 `/var/lib/gpupm-trial/backup-share-members-1792043343619963582`；升级演练通过。
- 边界：已有文件 ACL 不递归覆盖，新登录生效；旧路径共享目录授权修改会在预览阶段拦截，备注仍可修改。未做大规模成员及多浏览器压力测试。

### 2026-10-15 gpu_trial 共享授权错误定位与提示修复

真实服务器确认 gpu_trial（UID 1018）为 active、managed、is_human，非 protected，无恢复限制。单独验证及实际共享变更预览通过；原共享名单中残留已软删除的 gpupmqa 测试账号会导致整份名单校验失败。此前泛化错误没有指出具体成员。

修复：后端错误带被拒绝的用户名；界面显示具体错误成员。编辑器读取含软删除账号的状态，逐行标识，并在提交预览前明确列出不可授权成员，保留人工移除决定。

回归：Ubuntu 相关后端 68 passed，前端相关 16 passed，构建/Ruff/git diff --check 通过。已备份部署，备份 `/var/lib/gpupm-trial/backup-share-member-diagnostic-1792045848019697042`。未代用户执行共享授权变更。

### 2026-10-15 旧共享目录原位置授权

修正此前共享根目录校验过严：已有目录按 root 端记录的路径管理，新目录仍创建于配置共享根。旧目录要求根拥有、安全父目录、逐组件禁止符号链接，预览绑定路径/device/inode，执行复核并固定目录描述符。客户端仍不能提交任意路径。不移动目录，不递归覆盖子文件 ACL。

验证：Ubuntu 后端全量 344 passed；包含旧目录/当前根同名目录隔离、符号链接拒绝、预览后替换目录阻断、原文件保留。实际服务器 `/var/lib/gpupm-qa/data/shared/gpupmqa_97001781d8` 的 gpu_trial 只读授权预览通过，未执行授权。已部署，备份 `/var/lib/gpupm-trial/backup-legacy-share-path-1792047713238652439`；服务健康正常，Ruff/git diff --check 通过。

### 2026-10-15 成功后版本冲突与过期误报

真实审计确认 gpu_trial 在旧共享目录的读写授权已成功，revision 从 1 变为 2；错误来自成功后的自动预览重放，不是该授权失败。useSave 全量刷新触发旧版本预览请求，且完成后计时器仍显示过期。

修复冻结预览的刷新范围、成功状态和倒计时，增加保留原因的显式重新预览。保留真实冲突拦截，并补齐演示后端的 revision 校验。

验证：新生命周期回归 4 项先失败后通过；前端全量 104 passed，Ubuntu 后端全量 345 passed，Chrome 全量 20 passed，后端对齐后共享相关 E2E 再次通过。真实服务器旧版本相同 UI 测试复现错误，新版完整链路通过：QA 目录备注提交→超过30秒→关闭重开→恢复备注，总计2次预览/2次执行，无错误、无重复请求，gpu_trial 授权/版本未改变。截图 `.runtime/preview/preview-success-after-expiry.png`。

已部署，备份 `/var/lib/gpupm-trial/backup-preview-lifecycle-1792050164249694445`，升级演练和服务健康通过。Ruff、构建、git diff --check 通过。未执行新的真实用户授权。

### 2026-10-15 查看访问成员改为弹窗

共享目录“查看访问成员”和项目名改为打开只读弹窗，移除表格展开行；复用现有成员信息，按最新轮询数据展示。样式采用编辑弹窗的650px居中及限定高度滚动，保留路径复制、权限提示和备注。

验证：相关前端4项通过、构建/类型检查通过、Chrome共享完整流程1项通过。真实服务18000中英文/375px、项目名入口、关闭图标、关闭按钮和Esc验证通过，无业务写请求或页面错误。部署备份 `/var/lib/gpupm-trial/backup-members-modal-1792052118955065117`。演示实例18001无共享记录，线上数据验收未覆盖该空实例，演示创建/弹窗流程由E2E创建的fixture覆盖。未修改成员、权限及文件。

### 2026-10-15 GPU 筛选及空结果定位

复现：后端筛选只查当前 members.gpu_memory，结束清空 members 后按 GPU 查不到历史任务；前端用户框未受控，切换范围后 uid 清空但旧用户名仍显示。新增对应失败测试后修复。保留任务设备历史，统一筛选状态/勾选/分页，补充匹配数量、空态引导、错误重试、GPU 列和已结束任务终止限制，覆盖中英文。

验证：相关后端127项、白名单/残留54项通过；既有相关前端17项、新增筛选/错误/结束详情4项通过；Chrome既有管理员/布局10项、新增筛选1项通过，构建/类型检查及Ruff通过。新增浏览器测试使用与既有用例一致的键盘操作Select，并等待响应式布局收敛。

真实服务器：gpu_trial 运行30秒低负载CUDA验证任务，ID effed22f-c1e3-426b-b577-8f4130a705bd；结束后members为空，GPU UUID仍保留，API与网页按设备+已结束均可找到，终止按钮禁用，中英文/375px验证通过，无页面错误。截图 .runtime/preview/task-filters-native-desktop.png、task-filters-native-mobile.png。测试别名首次提交遇到初始默认策略落地的revision变化；重新读取revision后提交成功，版本保护未绕过。未修改其他任务策略及用户权限。本轮为相关回归，未重跑全平台全量测试。

部署备份 /var/lib/gpupm-trial/backup-task-filters-1792055678417087879；数据库兼容演练通过，账号/权限组/共享ACL及root配置部署前后校验不变，真实/演示实例健康正常。旧任务已丢失的GPU关联无法自动补回。

最终前端补充详情页已结束任务禁用终止，静态资源备份 `/var/lib/gpupm-trial/backup-task-filters-final-1792056267051042639`。

### 2026-10-15 已结束计时及服务主进程到期终止

根因：host/API一直用now-start计算结束任务运行时间/剩余时间；终止候选把全部PPID=1进程作为未授权孤儿排除，systemd启动的已确认leader也受影响。新增失败回归先复现实际未发送信号和结束后继续计时，再修复。共用task_timing计算时间，residual_status持久化观察结束时间；演示预览/执行与原生leader规则一致，主进程不再误标orphan。

验证：相关后端197项通过，另加“例外仅限已确认leader、其他PPID1仍排除”1项通过，共198项；前端21项、Chrome任务/策略/残留7项、构建/类型检查、Ruff及git diff --check通过。保留既有残留人工清理与保护/心跳/版本安全回归，未重跑全平台全量测试。

真实验收任务cc53ced0-7c67-42bf-9d45-e99c26c4eeda，gpu_trial PID554915。平台设置30秒，systemd RuntimeMaxSec仅在120秒兜底。19:39:24启动，19:39:57系统日志Deactivated successfully（未触发systemd timeout），19:39:58.271780采集确认结束，运行时长35.11178秒；平台审计actor=policy、同PID term=signaled、final=exited、job completed。后续跨多个5秒采集周期复读运行时长/finished_at完全不变、remaining_seconds为空、overdue=false。记录`.runtime/task-deadline-native-result.json`。此前5分钟历史任务无真实结束记录，运行/剩余时间为无数据，不伪造回填。测试未改其他任务策略或全局默认值。

已部署备份`/var/lib/gpupm-trial/backup-task-deadline-1792064341965209486`，数据库升级兼容演练通过；部署前后系统账号/权限组、共享ACL和root配置校验不变，真实/演示健康检查通过。

真实网页详情的采集确认结束时间、中英文/375px及终止按钮禁用验证通过，无页面错误；截图`.runtime/preview/task-clock-native-desktop.png`和`task-clock-native-mobile.png`。

### 2026-10-16 导航名称精简

本地账号和权限组去掉Linux前缀，中文/英文及相关断言同步。相关前端17项、构建与类型检查通过；真实服务中英文两个页面标题/侧栏校验通过，无页面错误。仅改显示名称，后端与权限规则未改。

## 2026-10-16 用户组与任务策略继承

- 用户组统一默认组、普通组和自定义组；账号详情选择分组，个人配置仅在自定义组生效，切换后保留。移除独立用户业务策略入口；原生权限组保留于账号高级功能。
- 按字段区分继承与覆盖（包含明确不限时），解析有效值和来源。新任务持久化策略/来源/分组快照；已有任务不被后续组或全局设置覆盖。历史任务排序及个人旧配置通过审计迁移保存。
- 修复独立复核发现的保护账号策略旁路、迁移排序、首次编辑尚未同步的新任务，以及 worker 成员变动导致误判旧任务的问题。默认组成员数与人员账号列表一致。
- 后端全量：`uv run pytest -q`，364 passed、2 skipped（macOS 缺少 Linux SO_PEERCRED/procfs）。随后成员统计修复的 API 回归 61 passed；Ruff 通过。
- 在 wzx-ubuntu 使用隔离临时数据库运行 Linux 专用 `test_host_transport.py`：2 passed（普通 SSH 用户执行；root 分支保护由独立单元测试覆盖）。
- 前端全量：`npm test -- --maxWorkers=1 --testTimeout=20000`，18 files / 114 passed；最后增加的保留名称冲突显示测试另行通过（1 passed）。更新老测试的 /users、/groups mocks，异步界面断言等待上限设为5秒，未替换业务断言或使用固定等待。
- Chrome 浏览器相关回归分批16项通过：导航、任务编辑、账号恢复、国际化、固定/折叠侧栏、移动布局、高级系统组、只读模式，以及创建组/不限时/个人分组切换与配置保留。新增流程先复现选择器与动画期尺寸断言问题，改用可访问角色、键盘选择与稳定状态断言后通过。
- TypeScript/Vite build 与 `git diff --check` 通过。保留已有大 bundle 警告与 Ant Design InputNumber 弃用提示，本次未新增依赖。
- 发布前对实际数据库备份进行新版/旧版隔离启动验收，通过审计校验允许的迁移差异，原生账号与共享目录数据不变。真实服务健康正常，浏览器中英文/375px验收无 pageerror。
- 真实数据只读核验：2个组、38个人员账号；25个任务均具有策略来源和分组快照，已结束任务无倒计时，组人数与成员列表一致；gpu_trial可配置、维护账号只读。
- 本轮未启动新的真实 GPU 任务或执行真实任务终止；不以演示流程代替完整 GPU 负载验收。已保存迁移前完整备份，回滚必须同时还原数据库与代码，不能仅回退程序文件。

## 2026-10-17 任务策略组与系统用户组分离

- 后端全量：367 passed，2 skipped（本机非 Linux）；Ruff 与 diff whitespace 检查通过。
- 前端 117 项覆盖分批通过：首轮 113 passed / 4 failed；修复新增菜单位置索引遗漏、更新系统组英文标题断言、调整多选输入可见性断言后，5 个受影响文件 42/42 passed。原有任务编辑测试在并发负载下触发 10s 超时，受影响文件复测通过。
- 浏览器：管理员原有流程 4 项、中英文 3 项、布局 6 项、系统组 1 项、只读模式 1 项、任务策略组 2 项，共 17 个不同场景分批通过。任务组流程使用独立临时服务，避免账号停用场景污染共享 demo 账号。
- 新增断言覆盖批量原子性、原分组冲突、实时受保护账号拒绝、重复/空/非法成员、个人配置保留、已有任务快照不变、失败选择保留与取消，以及原生系统组不变。
- 浏览器多选搜索需先等待弹窗进入动画完成；选择后点击标题收起下拉，再保存。录制追踪确认先前卡住是测试在进入动画中抢焦点或点击被下拉遮挡的按钮。
- TypeScript/Vite 构建通过；既有大包和 Ant InputNumber 弃用提示未在本轮处理。
- 部署后实机只读验收：3 个任务策略组、38 个人员账号；gpu_trial 可编辑，维护账号不可编辑；中文/英文、375px 布局、旧高级系统组路径跳转、成员接口空列表拒绝均通过，无 pageerror。
- 未新增真实 GPU 终止或真实账号组成员变更试验。真实服务器仅做只读/无效请求校验；完整成员写入流程在隔离 demo 与后端测试中验证。

## 2026-10-17 系统用户组成员操作优化

- 前端增加独立成员弹窗、搜索、主组/附加成员区分、账号链接、增量添加和逐项移除。组名编辑不再携带成员字段，创建组仍支持初始成员。
- 复用已有 revision/token/reason 预览执行流程；保留原成员、其他系统组和任务策略。受保护/只读/恢复中账号不会进入添加候选，主组成员不提供移除按钮。
- 单元测试：原系统组文件 8 项通过；新增成员交互 3 项通过（等待弹窗进入动画完成后验证可见性）。
- 浏览器：系统组原流程与新增成员流程、中英文共 5 项通过；窄屏成员弹窗另做截图与视口检查，避免动画中截图造成假空白。新增/移除确认前后状态、既有成员保留及任务策略不变均有断言。
- TypeScript/Vite 构建和 git diff --check 通过。本轮无后端代码变更，未重复后端全量测试。
- 实机只读验收 gpupmqa_grp_60b280：中英文、桌面与 375px 成员弹窗通过，无页面错误。未在真实服务器修改任何成员关系。

## 2026-10-17 独立审查后的可靠性修复

- 修复六项已确认问题：历史任务大快照分帧、失败任务策略恢复、写入中弹窗关闭、冲突后草稿恢复、旧账号策略接口资格一致性、目录实际分配空间统计。没有新增业务功能或依赖。
- 快照保持单次采集、1 MiB 单帧上限；客户端校验顺序和完整长度后返回，64 MiB 为总上限。失败策略修改保留最后生效值；心跳核对 root 实际策略，不重放失败候选。极旧未登记任务只按观察值和 revision 做无变化登记。
- 独立复核额外发现账号草稿跨账号残留，已将草稿绑定到具体操作；新增“冲突→返回编辑→取消→另一账号启用管理”回归。
- 后端全量 391 passed、2 skipped（macOS 的 Linux 专用测试）；Ruff 通过。独立复核涉及账号/存储 111 项、任务通信/恢复 16 项均通过。
- wzx-ubuntu 普通 SSH 用户通过隔离 socket 验证 4,000 条长中文名称任务、单次采集、Linux peer credentials；未使用真实 agent socket 或改变真实进程。
- 目录用量改为 st_blocks × 512，单个扫描根按设备/inode 去重，含目录自身且不跟随符号链接、不跨设备；已有缓存需管理员手动刷新后更新。统计不是删除目录后保证可回收的容量。

- Frontend: 127 distinct tests covered across runs. Initial run: 120 passed / 7 failed (6 timeouts, 1 stale account draft regression). Final affected-file rerun: 23/23 passed without raising the tests' existing timeouts. Independent review confirmed action-bound drafts.
- Chrome: 7 passed (i18n, native group members, conflict recovery and pending-write close prevention, shared directory layout). TypeScript/Vite build and whitespace checks passed.
- Deployment rehearsal and full backup succeeded. Installed Linux transport passed the 4,000-task isolated check again. All three services active; agent=ok, root_readiness.ready=true. Live zh/en and 375px UI checks passed, including group members, account eligibility and allocated-space text; no pageerror.
- Native accounts/groups, shared ACL and root config unchanged. No live GPU signals, native membership mutations or directory scans were performed. Existing bundle-size and Ant InputNumber deprecation warnings remain.
