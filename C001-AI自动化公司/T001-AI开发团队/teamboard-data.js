window.TEAMBOARD_DATA = {
  "generated_at": "2026-08-28 05:11:34",
  "page_version": "v1.1",
  "config": {
    "stale_days": 14
  },
  "tid": "T001",
  "name": "AI开发团队",
  "member_count": 2,
  "members": [
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
      "mydesk": "../E0001-AI员工-分析员/mydesk.html"
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
      "mydesk": "../E0002-AI员工-项目经理/mydesk.html"
    }
  ],
  "stats": {
    "planned": 1,
    "in_progress": 4,
    "done": 4,
    "total": 9,
    "ongoing": 5,
    "rate": 0.4444,
    "done_7d": 4
  },
  "projects": [
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
  "notices": [
    {
      "title": "示例公告：团队看板体系上线",
      "date": "2026-08-27",
      "author": "E0002",
      "body": ""
    }
  ],
  "assets": [
    {
      "name": "team-dev-standards",
      "desc": "T001 团队级开发规范技能（团队内部使用）。触发词：团队规范、开发规范、交付标准、代码评审、T001。T001 团队成员（开发/前端/后端）在团队内开展开发交付、评审协作时加载本技能；公司级工单操作一律按公司级技能 skills/ticket-system/SKILL.md 执行，本技能只承载团队专属约定，不与公司级规范耦合。"
    }
  ],
  "links": {
    "dashboard": "../dashboard.html",
    "kanban": "../workbench/kanban.html"
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
