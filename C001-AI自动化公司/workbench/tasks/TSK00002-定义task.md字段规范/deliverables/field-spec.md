# task.md 字段规范（草案）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | string | 是 | 全局唯一编号，如 TSK00002 |
| title | string | 是 | 卡片标题 |
| status | enum | 是 | backlog/in_progress/review/done/failed/paused |
| owner | string | 是 | 承接员工 ID，如 E0002 |
| project | string | 否 | 所属项目 ID，如 P0001 |
| priority | 高/中/低 | 否 | 优先级圆点 + 筛选 |
| type | 需求/bug/任务 | 否 | 类型筛选 |
| due | date | 否 | 截止日 YYYY-MM-DD |
| tags | list | 否 | 自由标签，多选筛选 |
| created | date | 否 | 创建时间 |
| updated | date | 否 | 更新时间 |
| description | text(正文) | 否 | frontmatter 之后为正文 |
