# human 管理范围实施计划

**Goal:** human 账号与任务为默认管理对象，其余只读，并更新服务器试用部署。
**Architecture:** 依据真实 Linux 主组/附属组解析 human；agent 为写操作权威边界，API 附加筛选与元数据限制，React 提供 human/other 入口。demo 同步相同语义。
**Tech Stack:** 原有 Python/FastAPI/SQLite、React/AntD。

- [x] 在 backend/tests/unit/test_host_agent.py 和 integration/test_api.py 添加 non-human 越权、移组撤销、创建默认组的失败测试；运行确认红灯。
- [x] agent/accounts.py 集中 human 身份与 writable 校验；保护 human 组；agent/host.py 策略/归组/终止与每次信号、后台策略核验；storage 共享成员及 quota 保留同样校验；demo.py 对齐。
- [x] api/context.py 和 routes 增加 human 分类、默认筛选及业务用户修改拒绝；heartbeat 跳过 other，GPU 总量不变。
- [x] frontend/src/pages.tsx 增加分类、只读限制、列表终止入口；更新 fixtures 并补组件测试，先红后绿。
- [x] 完整后端/前端/E2E/构建与 Ruff；核对服务器指定账号，创建或验证 human 普通组，仅增补成员，不修改其他组；更新代码及重启试用服务，验证 host/demo 来源、分类、只读和原训练存活。
- [x] 更新文档、提交本地功能分支并交付现有试用链接。
