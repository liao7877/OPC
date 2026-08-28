window.KANBAN_DATA = {
  "generated_at": "2026-08-28 05:11:34",
  "source": "workbench/tasks/",
  "status_meta": {
    "backlog": "待领",
    "in_progress": "进行中",
    "review": "待审",
    "done": "完成",
    "failed": "失败",
    "paused": "暂停",
    "cancelled": "取消"
  },
  "employees": {
    "E0000": "总管",
    "E0001": "分析员",
    "E0002": "项目经理"
  },
  "projects": {
    "P0001": "示例项目",
    "P0002": "知识库体系",
    "P0003": "流程自动化",
    "P0004": "公司看板与工作记录系统"
  },
  "tasks": [
    {
      "id": "TSK00004",
      "title": "搭建 kanban.html 前端（暗亮双主题/筛选/详情）",
      "status": "backlog",
      "owner": "E0001",
      "project": "P0001",
      "owner_name": "分析员",
      "project_name": "示例项目",
      "priority": "中",
      "type": "需求",
      "due": "2026-08-29",
      "tags": [
        "前端",
        "可视化"
      ],
      "created": "2026-08-26",
      "updated": "2026-08-26",
      "completed_at": null,
      "description": "单文件 vanilla JS 看板：经典状态列、分组维度切换（状态/项目/负责人）、筛选条（优先级/类型/标签/搜索）、暗亮双主题（默认暗）、卡片与详情面板、空状态占位。数据读 tasks-data.json。",
      "messages": "# 备注\n\n- 排队中，等 TSK00003 生成器产出数据契约稳定后开工。\n- 廖哥偏好暗色监控风，默认暗；右上角放主题切换，localStorage 记忆。\n- 技术约束：纯 vanilla JS、无框架、单文件、双击即开（file:// 直接可用）。\n",
      "escalations": [],
      "deliverables": [],
      "logs": [],
      "handoffs": [
        {
          "from": "E0000",
          "to": "E0001",
          "at": "2026-08-27",
          "reason": "总管派发前端搭建任务"
        }
      ],
      "participants": [
        "E0000",
        "E0001"
      ],
      "last_handoff_at": "2026-08-27",
      "parent": null,
      "children": [],
      "links": [],
      "blocked_by": [],
      "inputs": [
        {
          "name": "字段规范",
          "path": "tasks/TSK00002-定义task.md字段规范/deliverables/field-spec.md",
          "valid": true
        }
      ],
      "status_history": []
    },
    {
      "id": "TSK00007",
      "title": "知识库结构化归档规范",
      "status": "in_progress",
      "owner": "E0000",
      "project": "P0002",
      "owner_name": "总管",
      "project_name": "知识库体系",
      "priority": "高",
      "type": "需求",
      "due": "2026-09-05",
      "tags": [
        "运营",
        "知识库",
        "规范"
      ],
      "created": "2026-08-27",
      "updated": "2026-08-27",
      "completed_at": null,
      "description": "制定全公司知识库（E:\\WorkBuddy_KnowledgeBase）的结构化归档规范：链接归档模板、核心内容提取规则、缺失信息补全流程。目标是让每个分享链接都能被无遗漏地沉淀为可检索 Markdown。\n\n## 验收标准\n- 归档模板覆盖：来源 / 核心结论 / 关键数据 / 待办 / 关联\n- 与现有 skill-registry 检索链路打通",
      "messages": "【2026-08-27 E0000】分配给 E0000 牵头，P0002 知识库建设项目首批需求。要求 9 月初出 v1 规范稿，先和 E0002 对齐归档模板字段。\n",
      "escalations": [],
      "deliverables": [],
      "logs": [],
      "handoffs": [],
      "participants": [
        "E0000"
      ],
      "last_handoff_at": "",
      "parent": null,
      "children": [],
      "links": [],
      "blocked_by": [],
      "inputs": [],
      "status_history": []
    },
    {
      "id": "TSK00009",
      "title": "历史数据迁移与归档",
      "status": "in_progress",
      "owner": "E0001",
      "project": "P0003",
      "owner_name": null,
      "project_name": null,
      "priority": "高",
      "type": "任务",
      "due": "2026-08-24",
      "tags": [
        "数据",
        "迁移"
      ],
      "created": "2026-08-20",
      "updated": "2026-08-27",
      "completed_at": null,
      "description": "将旧格式的工单数据迁移到新规范结构，并归档历史记录。",
      "messages": "> 2026-08-24 E0001：迁移脚本已写好，等待数据校验。\n> 2026-08-26 E0001：数据校验中发现 3 条脏数据，正在清理。\n",
      "escalations": [],
      "deliverables": [],
      "logs": [],
      "handoffs": [],
      "participants": [
        "E0001"
      ],
      "last_handoff_at": "",
      "parent": null,
      "children": [],
      "links": [],
      "blocked_by": [],
      "inputs": [],
      "status_history": []
    },
    {
      "id": "TSK00002",
      "title": "定义 task.md 字段规范（frontmatter）",
      "status": "in_progress",
      "owner": "E0002",
      "project": "P0001",
      "owner_name": "项目经理",
      "project_name": "示例项目",
      "priority": "高",
      "type": "任务",
      "due": "2026-08-27",
      "tags": [
        "规范",
        "数据契约"
      ],
      "created": "2026-08-26",
      "updated": "2026-08-26",
      "completed_at": null,
      "description": "为看板立数据契约：定义 task.md 的 frontmatter 字段集（id / title / status / owner / project / priority / type / due / tags / created / updated / description），并约定状态机与解析规则，供 E0000 派单和全员建任务遵循。",
      "messages": "# 进行中备注\n\n- 字段集已与 PRD 对齐，重点确认了 priority 三档（高/中/低）、type 三类（需求/bug/任务）的取值字典。\n- 待决：tags 是否限制词表？暂定自由标签，生成器按出现频率聚合。\n- 阻塞：TSK00006 使用文档依赖本规范定稿，需尽快收敛。\n",
      "escalations": [],
      "deliverables": [
        {
          "name": "field-spec.md",
          "rel_path": "TSK00002-定义task.md字段规范/deliverables/field-spec.md"
        }
      ],
      "logs": [
        {
          "name": "2026-08-26.md",
          "rel_path": "TSK00002-定义task.md字段规范/logs/2026-08-26.md"
        }
      ],
      "handoffs": [],
      "participants": [
        "E0002"
      ],
      "last_handoff_at": "",
      "parent": null,
      "children": [],
      "links": [],
      "blocked_by": [],
      "inputs": [
        {
          "name": "项目章程",
          "path": "../../companies/C001/P0001-示例项目/project.md",
          "valid": true
        },
        {
          "name": "PRD 需求规格",
          "path": "tasks/TSK00001-协作看板需求澄清与规格定稿/deliverables/PRD.md",
          "valid": true
        }
      ],
      "status_history": []
    },
    {
      "id": "TSK00008",
      "title": "自动化流程痛点调研",
      "status": "review",
      "owner": "E0001",
      "project": "P0003",
      "owner_name": "分析员",
      "project_name": "流程自动化",
      "priority": "中",
      "type": "任务",
      "due": "2026-09-02",
      "tags": [
        "调研",
        "自动化",
        "复盘"
      ],
      "created": "2026-08-27",
      "updated": "2026-08-27",
      "completed_at": null,
      "description": "调研公司当前各 AI 员工（E0000/E0001/E0002）协作流程中的断点与重复劳动，输出痛点清单与优先级排序，作为下一阶段自动化改造的输入。\n\n## 范围\n- 工单派发是否顺畅（对照 dispatch-sop）\n- 状态流转是否有人工遗漏\n- 跨项目信息检索成本",
      "messages": "【2026-08-27 E0001】初稿完成，进入待审。请 E0002 复核\"跨项目检索成本\"一节的数据是否准确。\n",
      "escalations": [],
      "deliverables": [],
      "logs": [],
      "handoffs": [],
      "participants": [
        "E0001"
      ],
      "last_handoff_at": "",
      "parent": null,
      "children": [],
      "links": [],
      "blocked_by": [],
      "inputs": [],
      "status_history": []
    },
    {
      "id": "TSK00003",
      "title": "实现 generate_tasks.py 生成器 + 监听",
      "status": "review",
      "owner": "E0001",
      "project": "P0001",
      "owner_name": "分析员",
      "project_name": "示例项目",
      "priority": "中",
      "type": "需求",
      "due": "2026-08-28",
      "tags": [
        "工具链",
        "前端",
        "自动化"
      ],
      "created": "2026-08-26",
      "updated": "2026-08-26",
      "completed_at": null,
      "description": "实现零依赖生成器：扫描 tasks/ 解析 frontmatter + 内联 messages/deliverables/logs，产出 tasks-data.json；提供 --watch 文件监听自动重跑。需待总管评审后合并。",
      "messages": "# 评审备注\n\n- 已实现极简 frontmatter 解析，覆盖列表型 tags（[a, b, c]）。\n- 容错：缺字段 / 坏 frontmatter 跳过并告警，不中断整体生成。\n- 已内联详情数据（messages / deliverables / logs）进 JSON，满足 file:// 离线加载需求。\n- 待评审：监听采用 1s 轮询 mtime 方案，是否够用？高频改动场景可后续换 watchdog。\n",
      "escalations": [],
      "deliverables": [
        {
          "name": "README.md",
          "rel_path": "TSK00003-实现generate_tasks.py生成器/deliverables/README.md"
        }
      ],
      "logs": [
        {
          "name": "2026-08-26.md",
          "rel_path": "TSK00003-实现generate_tasks.py生成器/logs/2026-08-26.md"
        }
      ],
      "handoffs": [],
      "participants": [
        "E0001"
      ],
      "last_handoff_at": "",
      "parent": null,
      "children": [],
      "links": [],
      "blocked_by": [],
      "inputs": [],
      "status_history": []
    },
    {
      "id": "TSK00001",
      "title": "协作看板需求澄清与规格定稿",
      "status": "done",
      "owner": "E0002",
      "project": "P0001",
      "owner_name": "项目经理",
      "project_name": "示例项目",
      "priority": "高",
      "type": "任务",
      "due": "2026-08-26",
      "tags": [
        "需求",
        "协作",
        "PRD"
      ],
      "created": "2026-08-26",
      "updated": "2026-08-26",
      "completed_at": "2026-08-27",
      "description": "与廖哥以一问一答形式澄清看板需求，锁定 7 项决策（取数机制 / 协作语义 / 数据契约 / 布局 / 演示数据 / 风格 / 与 E0000 关系），产出 KANBAN_PRD.md 作为后续构建依据。",
      "messages": "# 交接备注\n\n- 需求澄清采用一问一答，逐层挖深，共 7 轮。\n- 关键结论：静态生成 + 自动重跑；只读共享视图 + 客户端交互；完整 frontmatter 字段；经典状态看板 + 切换分组；暗亮双主题默认暗；独立不碰 E0000。\n- 廖哥特别强调：演示数据要反映真实工单功能形态，不能是玩具数据。\n- 下一步：TSK00002 定字段规范 → TSK00003 写生成器 → TSK00004 搭前端。\n",
      "escalations": [],
      "deliverables": [
        {
          "name": "PRD.md",
          "rel_path": "TSK00001-协作看板需求澄清与规格定稿/deliverables/PRD.md"
        }
      ],
      "logs": [
        {
          "name": "2026-08-26.md",
          "rel_path": "TSK00001-协作看板需求澄清与规格定稿/logs/2026-08-26.md"
        }
      ],
      "handoffs": [
        {
          "from": "E0001",
          "to": "E0002",
          "at": "2026-08-26",
          "reason": "需求分析完成，转规格定稿"
        }
      ],
      "participants": [
        "E0001",
        "E0002"
      ],
      "last_handoff_at": "2026-08-26",
      "parent": null,
      "children": [],
      "links": [],
      "blocked_by": [],
      "inputs": [],
      "status_history": []
    },
    {
      "id": "TSK00006",
      "title": "编写看板使用文档与交接",
      "status": "failed",
      "owner": "E0002",
      "project": "P0001",
      "owner_name": "项目经理",
      "project_name": "示例项目",
      "priority": "低",
      "type": "任务",
      "due": "2026-08-31",
      "tags": [
        "文档"
      ],
      "created": "2026-08-26",
      "updated": "2026-08-26",
      "completed_at": null,
      "description": "产出面向廖哥与 AI 员工的使用文档（怎么跑生成器、怎么看板、怎么加工单），并完成向总管的交接登记。",
      "messages": "# 失败说明\n\n- 失败原因：原计划依赖一份自动生成的字段字典，但字段规范（TSK00002）仍未定稿，文档无法锁定表述，评审被打回。\n- 处置：待 TSK00002 定稿后重开，转为新任务跟踪（建议新建 TSK00007 承接，避免在本失败任务上直接改状态造成历史污染）。\n",
      "escalations": [],
      "deliverables": [],
      "logs": [
        {
          "name": "2026-08-26.md",
          "rel_path": "TSK00006-编写看板使用文档与交接/logs/2026-08-26.md"
        }
      ],
      "handoffs": [],
      "participants": [
        "E0002"
      ],
      "last_handoff_at": "",
      "parent": null,
      "children": [],
      "links": [],
      "blocked_by": [],
      "inputs": [],
      "status_history": []
    },
    {
      "id": "TSK00005",
      "title": "联调自测与边界验证（空状态/解析异常）",
      "status": "paused",
      "owner": "E0002",
      "project": "P0001",
      "owner_name": "项目经理",
      "project_name": "示例项目",
      "priority": "低",
      "type": "任务",
      "due": "2026-08-30",
      "tags": [
        "测试",
        "质量"
      ],
      "created": "2026-08-26",
      "updated": "2026-08-26",
      "completed_at": null,
      "description": "对看板做联调：空 tasks/ 占位、坏 frontmatter 容错、字段缺失降级。因等待真实工单样本与前端联调窗口，暂时挂起。",
      "messages": "# 暂停说明\n\n- 暂停原因：前端（TSK00004）尚未开工，联调缺少对象；且当前仅有示例工单，边界样本不足。\n- 恢复条件：TSK00004 完成后重启，并补充 1 条故意损坏的 task.md 作负向用例，验证生成器跳过而非崩溃。\n",
      "escalations": [],
      "deliverables": [],
      "logs": [
        {
          "name": "2026-08-26.md",
          "rel_path": "TSK00005-联调自测与边界验证/logs/2026-08-26.md"
        }
      ],
      "handoffs": [
        {
          "from": "E0001",
          "to": "E0002",
          "at": "2026-08-27",
          "reason": "联调中发现边界问题，转项目经理协调后暂停"
        }
      ],
      "participants": [
        "E0001",
        "E0002"
      ],
      "last_handoff_at": "2026-08-27",
      "parent": null,
      "children": [],
      "links": [],
      "blocked_by": [],
      "inputs": [],
      "status_history": []
    }
  ]
};
