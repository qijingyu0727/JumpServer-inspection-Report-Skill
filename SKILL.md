---
name: jumpserver-inspection-report
description: 通过内置 `scripts/jms_inspection.py` 生成 JumpServer 巡检日报、管理摘要、飞书消息载荷与本地定时计划。适用于“按模板生成今日/昨日巡检报告”“保存我的 Markdown 模板”“输出 open_id/group_id 推送载荷”“设置每日 08:00 定时巡检”“补充登录异常/资产状态/活跃会话/风险统计”等请求。
---

# JumpServer Inspection Report

## 快速概览

- 这是执行型 skill；命中标准流程时，直接运行 `python3 scripts/jms_inspection.py ...`。
- 正式入口统一放在 `scripts/`，模板资产放在 `assets/templates/`，运行产物写入 `runtime/`，详细规则拆到 `references/`。
- 默认模板选择顺序固定为 `runtime/template.md -> assets/templates/daily.md`；`executive` 模板作为管理层摘要模板保留。
- 用户要求增加统计项、优化摘要结构、补充推送字段或调整容错逻辑时，优先修改 `scripts/jms_inspection.py` 与对应 reference，不生成一次性临时脚本。
- 不在回复中打印或复述 Token / Secret 原文；鉴权异常时只返回脱敏说明与下一步动作。

## 核心路由

| 用户请求/条件 | 首选入口 | 读取文档 | 禁止事项 |
|---|---|---|---|
| 保存或更新用户自己的 Markdown 模板 | `python3 scripts/jms_inspection.py save-template ...` | [references/templates.md](references/templates.md) | 不要覆盖内置模板，除非用户明确指定路径 |
| 生成今日/昨日/指定日期巡检报告 | `python3 scripts/jms_inspection.py generate ...` | [references/templates.md](references/templates.md) | 不要把输出写回 skill 根目录 |
| 输出飞书推送载荷 | `python3 scripts/jms_inspection.py send-payload ...` | [references/delivery.md](references/delivery.md) | 不要假装已经完成真实发送 |
| 写入每日定时计划或启动常驻进程 | `setup-daily-push` / `daemon` | [references/delivery.md](references/delivery.md) | 不要把一次性 `setup` 说成已经在后台常驻执行 |
| 首次接入、Token 更新、接口联调、自检 | `python3 scripts/jms_inspection.py self-test` / `update-token` | [references/runtime.md](references/runtime.md) | 不要在配置缺失时继续生成报告 |
| 模板渲染异常、接口字段变化、空数据排查 | 先读 reference 再调整脚本 | [references/troubleshooting.md](references/troubleshooting.md) | 不要把接口 500 或字段缺失直接暴露成裸异常 |

## 正式入口

```text
python3 scripts/jms_inspection.py generate --date 2026-03-20
python3 scripts/jms_inspection.py generate --template-file executive
python3 scripts/jms_inspection.py save-template --content-file /path/to/template.md
python3 scripts/jms_inspection.py send-payload --open-id ou_xxx
python3 scripts/jms_inspection.py setup-daily-push --hour 8 --minute 0 --template-file daily
python3 scripts/jms_inspection.py daemon --hour 8 --minute 0 --template-file runtime/template.md
python3 scripts/jms_inspection.py self-test --date 2026-03-20
python3 scripts/jms_inspection.py update-token
```

## 不适用场景

- 非 JumpServer 巡检报告任务
- 需要真实飞书发送能力，但宿主环境并未提供发送工具或 webhook 约定
- 需要复杂多源报表编排、数据库落库或外部告警平台集成，但当前 skill 还没有正式入口
- 用户只想看文档说明，不希望执行脚本或修改本地模板

## 成功标准

- [ ] 目录层级清晰，根目录只保留 skill 元数据与兼容入口
- [ ] `SKILL.md` 只保留触发规则、入口和边界，细节下沉到 `references/`
- [ ] 模板、运行产物、脚本实现分离，不再把样例报告放在根目录
- [ ] 默认命令可直接定位到 `scripts/jms_inspection.py`
- [ ] 定时计划、报告输出、自优化记录统一落到 `runtime/`
