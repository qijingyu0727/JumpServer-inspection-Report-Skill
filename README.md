# JumpServer Inspection Report

[English](README.en.md)

`jumpserver-inspection-report` 是一个面向 JumpServer 巡检报告场景的执行型 skill。它通过内置脚本生成 Markdown 巡检日报、管理摘要、飞书消息载荷和本地定时计划，适合售后、运维和交付场景中的固定巡检流程。

## 目录结构

```text
.
├── SKILL.md
├── README.md
├── README.en.md
├── .gitignore
├── agents/
│   └── openai.yaml
├── assets/
│   └── templates/
│       ├── daily.md
│       └── executive.md
├── references/
│   ├── runtime.md
│   ├── templates.md
│   ├── delivery.md
│   └── troubleshooting.md
├── runtime/
│   └── .gitkeep
├── scripts/
│   ├── jms_inspection.py
│   └── load_probe.sh
├── main.py
└── requirements.txt
```

## 核心能力

- 根据 JumpServer API 数据生成巡检日报
- 支持占位符模板和自然语言模板
- 输出飞书消息载荷，供上层系统发送
- 写入本地定时计划并支持前台守护进程
- 在单个接口失败时做降级输出，不让整份报告直接报废

## 运行要求

- Python 3
- JumpServer 地址和认证环境变量

支持两种鉴权方式：

```bash
export JUMPSERVER_URL="https://your-jumpserver.example.com"
export JUMPSERVER_TOKEN="your_token"
```

或：

```bash
export JUMPSERVER_URL="https://your-jumpserver.example.com"
export JUMPSERVER_KEY_ID="your_key_id"
export JUMPSERVER_SECRET_ID="your_secret"
```

当前实现只使用 Python 标准库，[requirements.txt](/Users/qixiaoc/Code/skills/jumpserver-inspection-report/requirements.txt) 不包含第三方依赖。

## 常用命令

```bash
python3 scripts/jms_inspection.py generate --date 2026-03-20
python3 scripts/jms_inspection.py generate --template-file executive
python3 scripts/jms_inspection.py save-template --content-file /path/to/template.md
python3 scripts/jms_inspection.py send-payload --open-id ou_xxx
python3 scripts/jms_inspection.py setup-daily-push --hour 8 --minute 0 --template-file daily
python3 scripts/jms_inspection.py daemon --hour 8 --minute 0 --template-file runtime/template.md
python3 scripts/jms_inspection.py self-test --date 2026-03-20
python3 scripts/jms_inspection.py update-token
```

## 文档入口

- 执行边界与路由规则：`SKILL.md`
- 环境与运行方式：`references/runtime.md`
- 模板说明：`references/templates.md`
- 推送与定时：`references/delivery.md`
- 常见问题：`references/troubleshooting.md`
