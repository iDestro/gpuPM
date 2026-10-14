# gpuPM

管理员管理现有 SSH/nohup 启动的 NVIDIA GPU 任务，并管理 Ubuntu 本地账号、系统组、期限、私人数据目录、配额及共享目录。

- React + TypeScript + Ant Design + TanStack Query
- Python 3.12 + FastAPI + SQLite
- 普通权限 Web API；独立 root agent；Unix socket 通信
- 数据目录为 `/data/<用户名>`，私人目录默认 0700
- 用户删除仅软删除，账号和全部文件原地保留；不自动结束既有活动

## 本机运行演示

需要 Python 3.12、uv、Node.js 22.12+（或兼容所锁 Vite 的版本）。

```bash
cd backend
uv sync --locked
uv run gpupm admin-add --username admin
cd ../frontend
npm ci
npm run build
cd ../backend
uv run gpupm serve --mode demo
```

打开 <http://127.0.0.1:8000>，使用自己创建的管理员密码。演示模式始终显示来源提示，数据保存在后端 `.runtime/` 中，所有操作仅改变演示数据库。系统不会自动创建默认生产密码。

开发时前端运行 `npm run dev -- --host 127.0.0.1`，Vite `/api` 代理到 8000。宿主机模式为默认模式，必须连接 agent；连接失败不会回退到演示数据。

## 验证

```bash
uv run --project backend pytest backend/tests -q
uv run --project backend ruff check backend/src backend/tests
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend exec -- playwright install chromium
npm --prefix frontend run test:e2e
```

E2E 自动启动临时演示数据库和本地 8001 服务，专用测试凭据仅用于该测试进程。真实宿主机写操作需单独配置并执行专用账号/进程验收；不要用真实训练或现有用户文件测试删除/终止。

需求：[PRD](docs/PRD.md)。方案：[实施计划](docs/superpowers/plans/2026-10-14-gpupm-implementation.md)。部署与运维：[DEPLOYMENT](docs/DEPLOYMENT.md)。实测记录：[TEST_REPORT](docs/TEST_REPORT.md)。
