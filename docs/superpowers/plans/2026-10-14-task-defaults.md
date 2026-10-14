# Task Defaults Implementation Plan

> Use superpowers:subagent-driven-development for backend/frontend isolated scopes, then spec review and quality review.

**Goal:** 策略配置中的新任务模板包含运行时间、人工保护、优先级、到期动作和残留清理。
**Architecture:** domain模板首次发现复制；数据库缺省补全保留原值；前端分组、i18n及术语。
**Tech Stack:** Python/FastAPI/SQLite、React/AntD、Pytest/Vitest/Playwright。

- [x] 后端模板、设置schema/root验证、旧配置补缺及新任务应用，先失败回归再实现。
- [x] 前端新任务默认分组、编辑开关/优先级、国际化及术语测试。
- [x] 规格/质量审查、全后端/前端/浏览器回归与Ubuntu测试。
- [x] 一致备份部署；API设置30分钟默认，既有任务身份/策略不变；文档/提交。
