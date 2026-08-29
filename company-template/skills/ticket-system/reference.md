# ticket-system 参考细则（reference）

> 本文件是 SKILL.md 的 Level 3 附属：模板、字段细则、告警对照。按需查，不必整读。

## task.md 完整模板

```markdown
---
id: TSK00001
title: 工单标题
status: backlog
owner: E0001
project: P0001
priority: 中
type: 任务
due: 2026-08-30
tags: [标签1, 标签2]
created: 2026-08-27
updated: 2026-08-27
parent:                   ← 子单才填：所属需求父单编号（TSKxxx）
blocked_by: []            ← 有前置工单才填：[TSK00007, TSK00009]（单行）
---

正文：这个工单要做什么、目标是什么
```

> ⚠️ frontmatter 每行只能是 `key: value`（单行），**不要写行尾注释**；`handoffs`/`inputs` 必须单行 JSON（换行/缩进会污染 frontmatter 解析）。

## 字段细则

- **inputs（输入物）**：`[{"name":"PRD 需求规格","path":"tasks/TSK00001-xxx/deliverables/PRD.md"}]`
  - **引用不复制**（避免两份真相漂移）；路径相对 `workbench/`：项目文件写 `opc://company:C00x/project/<PID>/<文件>`，上游工单交付物写 `tasks/TSKxxx-…/deliverables/…`。
  - 上一手的交付物就是下一手的输入物——流转时把上游交付物列为你的输入；路径失效 → 生成器告警 + 看板标「⚠️ 路径失效」，及时修。
- **status_history（可选审计）**：`[{"to":"in_progress","at":"2026-08-27"}]`（单行 JSON），看板详情显示「状态轨迹」。
- **completed_at**：实际完成时间；≤ due 按期，> due 看板标「逾期完成」。

## 生成器告警对照（遇到告警怎么修）

| 告警 | 处理 |
|---|---|
| `缺少 frontmatter…跳过` | task.md 补 `---` 包裹 |
| `status=… 非法` | 改成 7 个合法值之一 |
| `id=… 重复，跳过` | 改编号（找总管） |
| `handoffs 最后交接给 X，但 owner=Y` | 对齐两者 |
| `inputs[…] 路径不存在` | 修路径 / 把文件移回 |
| `status=done 但未填 completed_at` | 补填 |
| `…日期格式无法识别` | 改成 `YYYY-MM-DD`（可带 `HH:MM`） |
| `frontmatter id=… 与目录名前缀不一致` | 统一编号 |
| `handoffs 时间倒序` | 按时间重排 |
| `due/completed_at 早于 created` | 修正日期 |
| `读取失败（疑似非 UTF-8）` | 另存为 UTF-8 |
| `owner/project 未找到且无兜底名` | 建目录或补 `owner_name`/`project_name` |
| `blocked_by 引用的工单不存在` | 找总管核对编号；上游取消则确认本单是否还做 |
| `上游已 done，本单仍标阻塞` | 好消息：可开工了，正常推进即可 |
| `子单未全部完成，父单已 done` | 父单状态回退（父单只有子单全 done 才能 done） |
| `parent 指向的父单不存在` | 找总管核对编号笔误 |
| `未认领（owner 有主但 worklog 无条目）` | 该 owner 按 SKILL.md §2 补认领动作 |
