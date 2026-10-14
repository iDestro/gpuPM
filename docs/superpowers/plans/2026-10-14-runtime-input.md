# Runtime Input Implementation Plan

> Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 最大运行时间无需人工换算秒数。
**Architecture:** 共用duration表单类型，内部时分秒对象在加载/提交边界与既有API秒值转换。
**Tech Stack:** React、AntD Form/InputNumber、Vitest、Playwright。

- [x] 添加回显/换算/快捷/不限时/无效时长回归，确认修改前失败。
- [x] 实现共享时长控件与表单校验，任务及默认最大时长接入。
- [x] 全前端测试、构建和浏览器回归。
- [x] 部署两个试用入口，实机只改草稿验证，记录并提交。
