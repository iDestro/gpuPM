# Runtime Only Implementation Plan

> Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 任务界面仅以最大运行时间控制期限。
**Architecture:** 删除任务datetime字段，任务保存清除expires_at；API保留旧字段兼容性。
**Tech Stack:** React、AntD、Vitest、Playwright。

- [x] 添加任务编辑无截止输入/旧期限清除回归并确认失败。
- [x] 移除输入、保存清除旧期限、详情改为只读预计结束时间。
- [x] 前端测试/构建/浏览器回归；部署后只读/草稿验证。
- [x] 文档及本地提交。
