# Dashboard 整改实施计划

**Goal:** 浅色专业 dashboard、稳定导航与紧凑信息层级。
**Architecture:** 保留 React/AntD；App/style/theme 管理固定视口和手机导航，components/pages 管理长文本与表格摘要；只调整前端。
**Tech Stack:** React19、AntD5、CSS、Vitest、Playwright。

- [x] 在 e2e 新增长审计数据、长文本、桌面滚动和手机导航/溢出失败用例；原导航、权限与操作预览测试保留。
- [x] App.tsx/style.css/main.tsx 改固定框架、独立滚动、分组浅色导航、手机Drawer、简洁主题；路径切换重置内容滚动。
- [x] components.tsx/pages.tsx 统一紧凑文本/中文状态，日志固定列宽和展开详情，账号/任务/存储/共享重点列防长字符串撑开；相关组件测试先失败再实现。
- [x] 前端全部测试、类型/构建、Chrome E2E；桌面/短屏/375px截图核对，审查完整信息访问与权限未改变。
- [x] 更新两个试用入口静态包，实机登录和截图验证，记录参考来源/实际结果并本地提交。
