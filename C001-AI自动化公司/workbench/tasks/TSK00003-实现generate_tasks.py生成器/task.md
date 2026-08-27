---
id: TSK00003
title: 实现 generate_tasks.py 生成器 + 监听
status: review
owner: E0001
project: P0001
owner_name: 分析员
project_name: 示例项目
priority: 中
type: 需求
due: 2026-08-28
tags: [工具链, 前端, 自动化]
created: 2026-08-26
updated: 2026-08-26
---
实现零依赖生成器：扫描 tasks/ 解析 frontmatter + 内联 messages/deliverables/logs，产出 tasks-data.json；提供 --watch 文件监听自动重跑。需待总管评审后合并。
