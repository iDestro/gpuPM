# Task Alias Implementation Plan

> Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 名称编辑作为别名，原名在悬停与详情可查。
**Architecture:** agent JSON状态保留只读original_name，API原样输出；复用CompactText tooltip。
**Tech Stack:** Python/FastAPI、React/AntD、Vitest/Playwright。

- [x] 添加后端名称保留、刷新结束/旧记录和前端hover回归，确认修改前失败。
- [x] agent生成及旧状态恢复original_name；前端别名文案、tooltip、详情；不修改name协议。
- [x] 运行相关后端测试、全前端测试/构建/E2E。
- [x] 更新试用服务、验证HTTP原名及浏览器hover，记录并提交。
