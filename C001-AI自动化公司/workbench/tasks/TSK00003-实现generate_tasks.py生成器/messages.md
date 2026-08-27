# 评审备注

- 已实现极简 frontmatter 解析，覆盖列表型 tags（[a, b, c]）。
- 容错：缺字段 / 坏 frontmatter 跳过并告警，不中断整体生成。
- 已内联详情数据（messages / deliverables / logs）进 JSON，满足 file:// 离线加载需求。
- 待评审：监听采用 1s 轮询 mtime 方案，是否够用？高频改动场景可后续换 watchdog。
