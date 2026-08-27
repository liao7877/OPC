window.DASHBOARD_DATA = {
  "generated_at": "2026-08-28 06:43:43",
  "page_version": "v1.1",
  "config": {
    "stale_days": 14
  },
  "company": {
    "cid": "C001",
    "name": "AI自动化公司"
  },
  "employees": [
    {
      "eid": "E0000",
      "name": "总管",
      "role": "总管",
      "status": "在职",
      "teams": [],
      "rank": "-",
      "registered": true,
      "dir": "E0000-AI员工-总管",
      "stats": {
        "planned": 0,
        "in_progress": 1,
        "done": 3,
        "total": 4,
        "ongoing": 1,
        "rate": 0.75,
        "done_7d": 3
      },
      "mydesk": "E0000-AI员工-总管/mydesk.html"
    },
    {
      "eid": "E0001",
      "name": "分析员",
      "role": "分析员",
      "status": "在职",
      "teams": [
        "T001"
      ],
      "rank": "成员",
      "registered": true,
      "dir": "E0001-AI员工-分析员",
      "stats": {
        "planned": 0,
        "in_progress": 2,
        "done": 3,
        "total": 5,
        "ongoing": 2,
        "rate": 0.6,
        "done_7d": 3
      },
      "mydesk": "E0001-AI员工-分析员/mydesk.html"
    },
    {
      "eid": "E0002",
      "name": "项目经理",
      "role": "项目经理",
      "status": "在职",
      "teams": [
        "T001"
      ],
      "rank": "lead",
      "registered": true,
      "dir": "E0002-AI员工-项目经理",
      "stats": {
        "planned": 1,
        "in_progress": 2,
        "done": 1,
        "total": 4,
        "ongoing": 3,
        "rate": 0.25,
        "done_7d": 1
      },
      "mydesk": "E0002-AI员工-项目经理/mydesk.html"
    }
  ],
  "teams": [
    {
      "tid": "T001",
      "name": "AI开发团队",
      "dir": "T001-AI开发团队",
      "leads": [
        "E0002"
      ],
      "member_count": 2,
      "teamboard": "T001-AI开发团队/teamboard.html"
    }
  ],
  "projects": [
    {
      "pid": "P0001",
      "name": "示例项目",
      "owner": null,
      "status": "active",
      "teams": [],
      "dir": "P0001-示例项目",
      "ticket_stats": {
        "total": 6,
        "byStatus": {
          "backlog": 1,
          "in_progress": 1,
          "review": 1,
          "done": 1,
          "failed": 1,
          "paused": 1
        },
        "overdue": 1
      }
    },
    {
      "pid": "P0002",
      "name": "知识库体系",
      "owner": "E0000",
      "status": "active",
      "teams": [],
      "dir": "P0002-知识库体系",
      "ticket_stats": {
        "total": 1,
        "byStatus": {
          "in_progress": 1
        },
        "overdue": 0
      }
    },
    {
      "pid": "P0003",
      "name": "流程自动化",
      "owner": "E0001",
      "status": "active",
      "teams": [],
      "dir": "P0003-流程自动化",
      "ticket_stats": {
        "total": 2,
        "byStatus": {
          "in_progress": 1,
          "review": 1
        },
        "overdue": 1
      }
    },
    {
      "pid": "P0004",
      "name": "公司看板与工作记录系统",
      "owner": "E0000",
      "status": "active",
      "teams": [
        "T001"
      ],
      "dir": "P0004-公司看板与工作记录系统",
      "ticket_stats": {
        "total": 0,
        "byStatus": {},
        "overdue": 0
      }
    }
  ],
  "affairs": [
    {
      "id": "AFF0001",
      "title": "行业周报运营",
      "status": "active",
      "owner": "E0001",
      "cadence": "每周",
      "priority": "中",
      "created": "2026-08-28",
      "updated": "2026-08-28",
      "body": "## 例行说明\n每周五收集 AI 行业要闻（≥10 条），筛选点评 3 条重点，产出《行业周报》到 assets/。\n\n## 质量标准\n- 信息有出处链接；点评不超过 100 字/条\n- 当周周五 18:00 前发布\n\n## 变更记录\n- 2026-08-28 建档（示例事务，验证全链路）",
      "dir": "AFF0001-行业周报运营",
      "last_touched": "2026-08-28",
      "last_by": "E0001",
      "overdue": false,
      "never_done": false
    }
  ],
  "activity": [
    {
      "eid": "E0001",
      "name": "分析员",
      "wid": "W-20260828-201",
      "title": "首期行业周报框架搭建",
      "status": "已完成",
      "type": "事务",
      "ticket": "",
      "project": "",
      "updated": "2026-08-28",
      "date": "2026-08-28"
    },
    {
      "eid": "E0000",
      "name": "总管",
      "wid": "W-20260827-001",
      "title": "三级看板需求澄清（廖哥四轮问答）",
      "status": "已完成",
      "type": "直聊",
      "ticket": "",
      "project": "P0004",
      "updated": "2026-08-27",
      "date": "2026-08-27"
    },
    {
      "eid": "E0000",
      "name": "总管",
      "wid": "W-20260827-002",
      "title": "撤销需求池工单 TSK00010~16 并回收编号",
      "status": "已完成",
      "type": "直聊",
      "ticket": "",
      "project": "",
      "updated": "2026-08-27",
      "date": "2026-08-27"
    },
    {
      "eid": "E0000",
      "name": "总管",
      "wid": "W-20260827-003",
      "title": "员工编号四位化改造（E000→E0000 等）",
      "status": "已完成",
      "type": "直聊",
      "ticket": "",
      "project": "",
      "updated": "2026-08-27",
      "date": "2026-08-27"
    },
    {
      "eid": "E0000",
      "name": "总管",
      "wid": "W-20260827-004",
      "title": "知识库结构化归档规范制定",
      "status": "进行中",
      "type": "工单",
      "ticket": "TSK00007",
      "project": "P0002",
      "updated": "2026-08-27",
      "date": "2026-08-27"
    },
    {
      "eid": "E0001",
      "name": "分析员",
      "wid": "W-20260827-101",
      "title": "自动化流程痛点调研",
      "status": "进行中",
      "type": "工单",
      "ticket": "TSK00008",
      "project": "P0003",
      "updated": "2026-08-27",
      "date": "2026-08-27"
    },
    {
      "eid": "E0001",
      "name": "分析员",
      "wid": "W-20260827-102",
      "title": "历史数据迁移与归档",
      "status": "已完成",
      "type": "工单",
      "ticket": "TSK00009",
      "project": "P0003",
      "updated": "2026-08-27",
      "date": "2026-08-27"
    },
    {
      "eid": "E0001",
      "name": "分析员",
      "wid": "W-20260827-103",
      "title": "generate_tasks.py 生成器实现收尾",
      "status": "进行中",
      "type": "工单",
      "ticket": "TSK00003",
      "project": "P0001",
      "updated": "2026-08-27",
      "date": "2026-08-27"
    },
    {
      "eid": "E0002",
      "name": "项目经理",
      "wid": "W-20260827-201",
      "title": "知识库结构化归档规范",
      "status": "进行中",
      "type": "工单",
      "ticket": "TSK00007",
      "project": "P0002",
      "updated": "2026-08-27",
      "date": "2026-08-27"
    },
    {
      "eid": "E0002",
      "name": "项目经理",
      "wid": "W-20260827-202",
      "title": "整理廖哥投喂的项目管理资料",
      "status": "计划中",
      "type": "直聊",
      "ticket": "",
      "project": "",
      "updated": "2026-08-27",
      "date": "2026-08-27"
    },
    {
      "eid": "E0002",
      "name": "项目经理",
      "wid": "W-20260827-203",
      "title": "task.md 字段规范定稿",
      "status": "进行中",
      "type": "工单",
      "ticket": "TSK00002",
      "project": "P0001",
      "updated": "2026-08-27",
      "date": "2026-08-27"
    },
    {
      "eid": "E0001",
      "name": "分析员",
      "wid": "W-20260826-101",
      "title": "搭建 kanban.html 前端",
      "status": "已完成",
      "type": "工单",
      "ticket": "TSK00004",
      "project": "P0001",
      "updated": "2026-08-26",
      "date": "2026-08-26"
    },
    {
      "eid": "E0002",
      "name": "项目经理",
      "wid": "W-20260826-201",
      "title": "协作看板需求澄清与规格定稿",
      "status": "已完成",
      "type": "工单",
      "ticket": "TSK00001",
      "project": "P0001",
      "updated": "2026-08-26",
      "date": "2026-08-26"
    }
  ],
  "risks": {
    "stale": [],
    "warnings": [
      {
        "scope": "核验",
        "msg": "E0001「历史数据迁移与归档」已完成，但工单 TSK00009 仍未关（in_progress）——记得关单"
      },
      {
        "scope": "核验",
        "msg": "E0001「搭建 kanban.html 前端」已完成，但工单 TSK00004 仍未关（backlog）——记得关单"
      },
      {
        "scope": "核验",
        "msg": "E0001 的 TSK00009 工单在途，但 worklog 记录非「进行中」"
      },
      {
        "scope": "核验",
        "msg": "E0002 的工单 TSK00005「联调自测与边界验证（空状态/解析异常）」未认领（worklog 无条目；按 ticket-system §1.5 认领）"
      }
    ]
  },
  "links": {
    "kanban": "workbench/kanban.html"
  },
  "status_meta": {
    "backlog": "待领",
    "in_progress": "进行中",
    "review": "待审",
    "done": "完成",
    "failed": "失败",
    "paused": "暂停",
    "cancelled": "取消"
  }
};
