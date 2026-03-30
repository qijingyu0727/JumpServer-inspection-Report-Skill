---
name: jumpserver-inspection-report
description: 作为 JumpServer 正式巡检报告 skill 处理“巡检报告/日报/月报/正式报告/legacy 报告”等请求。用户提供参数后，默认直接走 official `jms-inspect-go` 远程巡检并输出 `legacy` HTML 正式报告；首次接入需要先补齐 JUMPSERVER_URL、JUMPSERVER_USERNAME、JUMPSERVER_PASSWORD、JumpServer_IP、JMS_OFFICIAL_SSH_USERNAME、JMS_OFFICIAL_SSH_PASSWORD 等关键参数并写回 profile。
---

# JumpServer Formal Inspection Report

## 默认规则

- 只要用户是在要正式巡检报告，例如：
  - `生成巡检报告`
  - `给我昨天的巡检日报`
  - `发一下上个月的月报`
  - `给我一个 legacy 正式巡检报告`
- 并且参数已经齐全，默认必须直接执行：
  - `bin/jms-report <profile> <date> html`
  - 或 `python3 scripts/jms_inspection.py report <profile> <date> html`
- HTML 报告默认样式固定为 `legacy`，其 provider 默认固定为 `official`
- 正式报告默认输出 official `jms-inspect-go` 远程巡检生成的 HTML，不允许优先改走：
  - `generate --format markdown`
  - `fill-template`
  - `runtime/template.md`
  - 任意旧模板产物

## 首次接入必须补齐

- `JUMPSERVER_URL`
- `JUMPSERVER_USERNAME`
- `JUMPSERVER_PASSWORD`
- `JumpServer_IP`：JumpServer 部署服务器的资产名或 IP
- `JMS_EXEC_ACCOUNT_NAME`：连接该服务器的账号名，未说明时默认 `root`
- `JMS_OFFICIAL_SSH_USERNAME`
- `JMS_OFFICIAL_SSH_PASSWORD`

缺少这些项时，必须先补齐并立刻写回 env/profile，不要先产模板草稿。

推荐写回：

- `python3 scripts/jms_inspection.py save-config --profile <profile> KEY=VALUE [KEY=VALUE ...]`

新接入统一使用 `JumpServer_IP`；旧字段 `JMS_EXEC_ASSET_NAME` 仅作兼容。

## 主入口

- 正式巡检报告：
  - `bin/jms-report <profile> <date> html`
  - `python3 scripts/jms_inspection.py report <profile> <date> html [--from <YYYY-MM-DD>] [--to <YYYY-MM-DD>] [--org-name <名称> | --all-orgs]`
- 首次安装自举：
  - `python3 scripts/jms_inspection.py bootstrap --profile <profile>`
- 环境自检：
  - `python3 scripts/jms_inspection.py self-test --profile <profile> --date <YYYY-MM-DD>`
- 组织列表：
  - `python3 scripts/jms_inspection.py list-orgs --profile <profile>`
- 依赖补装：
  - `python3 scripts/jms_inspection.py ensure-deps official`
  - `python3 scripts/jms_inspection.py ensure-deps all`

## 允许的显式高级能力

- 只有用户明确提到以下关键词时，才允许走模板补全或 Markdown 路线：
  - `模板`
  - `Word`
  - `PDF`
  - `doc`
  - `docx`
  - `补全文档`
- 只有用户明确说要分析，不要求正式报告时，才允许走：
  - `analyze`
  - `host-usage`
- 模板与分析能力是显式能力，不是正式报告默认路径。

## 关键行为

- `legacy` 正式报告默认通过 official 引擎 SSH 到 JumpServer 主机，上传 `jms_inspect` 二进制、读取 `/opt/jumpserver/config/config.txt` 并远程完成系统、数据库、Redis 与服务巡检。
- 如果用户要求的是正式巡检报告，而当前还没有 JumpServer 服务器资产/IP 或 official SSH 凭据：
  - 必须继续追问
  - 不要用 API 摘要或模板 Markdown 冒充最终报告
- 用户明确给的是长时间范围时，只生成一份汇总报告，不拆成多个日报。
- 成功后优先返回：
  - 官方 HTML 报告路径
  - 如有 `_official_bundle/`，同时返回 bundle 目录

## Fresh Install

- fresh install 优先执行 `bootstrap`，不要默认先跑 `ensure-deps all`
- `bootstrap` 默认准备 `db + exec + docx + official`
- `legacy` 正式报告至少还需要：
  - `JumpServer_IP`
  - `JMS_OFFICIAL_SSH_USERNAME`
  - `JMS_OFFICIAL_SSH_PASSWORD`
- 安装完成后的最低验收动作：
  - `python3 scripts/jms_inspection.py self-test --profile <profile> --date <YYYY-MM-DD>`
  - `bin/jms-report <profile> <date> html`
- 成功标准必须是得到 official HTML 正式报告，而不是模板 Markdown

## 边界与禁止事项

- 没有 `profile`、组织范围、时间范围这类关键参数时，不要模糊执行。
- 不要把 `fill-template` 当成巡检报告默认入口。
- 不要因为模板文件存在，就把模板产物当成最终报告。
- official 报告失败时，要返回明确的 official 失败原因；除非用户显式设置 `JMS_LEGACY_PROVIDER=python`，否则不要静默回退旧 Python legacy HTML。
- 不要在输出中回显 Token / Secret / Password 原文。

## 文档入口

- 运行方式与环境：`references/runtime.md`
- 意图与追问规则：`references/intent-routing.md`
- 模板能力：`references/templates.md`
- 推送与定时：`references/delivery.md`
- 常见问题：`references/troubleshooting.md`
- 目录与元数据：`references/metadata/repo-layout.md`
