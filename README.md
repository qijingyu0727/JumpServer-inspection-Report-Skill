# JumpServer Inspection Toolbox

[English](README.en.md)

`jumpserver-inspection-report` 是一个面向团队使用的 JumpServer 巡检工具箱，覆盖正式巡检报告、异常登录与 Top N 分析、单机负载与会话查询、Word/PDF 模板补全、飞书载荷与本地定时计划。

默认 HTML 报告走 `legacy`，输出新版正式巡检完整版；`modern` 提供同一套 JumpServer 企业绿色视觉下的控制台摘要版。两种样式都已升级为新版 HTML 模版。

## 小龙虾安装 Skill 直接照抄

安装命令：

```bash
python3 scripts/jms_inspection.py bootstrap --profile prod
```

最小配置：

```ini
JUMPSERVER_URL=https://jumpserver.example.com
JUMPSERVER_USERNAME=admin
JUMPSERVER_PASSWORD=change_me
JumpServer_IP=10.1.12.46
JMS_EXEC_ACCOUNT_NAME=root
JMS_REPORT_STYLE=legacy
JMS_AUTO_INSTALL=true
```

网络受限环境可选补充：

```ini
HTTPS_PROXY=http://127.0.0.1:7890
HTTP_PROXY=http://127.0.0.1:7890
PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=180000
```

如果数据库连接不想走远端 `/opt/jumpserver/config/config.txt`，再补这一组：

```ini
DB_ENGINE=mysql
DB_HOST=10.1.12.46
DB_PORT=3306
DB_USER=root
DB_PASSWORD=change_me
DB_NAME=jumpserver
```

验证命令：

```bash
python3 scripts/jms_inspection.py list-orgs --profile prod
python3 scripts/jms_inspection.py self-test --profile prod --date 2026-03-20
bin/jms-report prod 2026-03-20 html
```

说明：

- `bootstrap` 默认安装 `db + exec + docx`
- 如果你还要用 PDF 模板补全，再执行 `python3 scripts/jms_inspection.py bootstrap --profile prod --include-pdf`
- 这样能避开 fresh install 时被 `pdf/libreoffice` 非核心依赖直接卡住
- `bootstrap` 会自动创建 `runtime/profiles/prod.env`，并把 Chromium 浏览器缓存放到 `runtime/.playwright-browsers`
- 如果 Chromium 下载容易超时，优先在 profile 里补 `HTTPS_PROXY/HTTP_PROXY` 或 `PLAYWRIGHT_DOWNLOAD_HOST`

## 功能概览

- 正式巡检报告：支持 `html` / `markdown`，`html` 默认输出 `legacy` 正式完整版，`modern` 提供摘要版
- 完整版数据链路：默认从 JumpServer 节点本机和数据库补齐系统信息、磁盘、审计统计
- 分析问答：支持异常登录、Top 用户、Top 资产、单机“谁在使用”和 `uptime`
- 模板补全：支持 `doc` / `docx` / `pdf` 巡检模板回填
- 推送与定时：支持生成飞书载荷和本地定时计划
- 配置复用：追问得到的参数可写回 env/profile，后续问答直接复用

## 安装

1. 安装 Python 依赖：

```bash
python3 scripts/jms_inspection.py bootstrap --profile prod
```

2. 如需额外安装 PDF 模板补全依赖：

```bash
python3 scripts/jms_inspection.py bootstrap --profile prod --include-pdf
```

## 首次接入最少配置

编辑 `runtime/profiles/prod.env`，至少补齐以下 5 项：

```ini
JUMPSERVER_URL=https://jumpserver.example.com
JUMPSERVER_USERNAME=admin
JUMPSERVER_PASSWORD=change_me
JumpServer_IP=10.1.12.46
JMS_EXEC_ACCOUNT_NAME=root
```

说明：

- `JumpServer_IP` 应指向 JumpServer 部署服务器的资产名或 IP
- `JMS_EXEC_ACCOUNT_NAME` 是连接该服务器的账号名，未说明时通常用 `root`
- 默认 `JMS_REPORT_STYLE=legacy`，表示正式巡检完整版
- 数据库查询默认使用 `PyMySQL[rsa]`；若目标库启用 MySQL 8 的 `caching_sha2_password` / `sha256_password`，还需要 `cryptography`
- `bootstrap` 输出里会给出 `pending_profile_keys`，表示当前 profile 里还需要你补齐的关键项
- 旧字段 `JMS_EXEC_ASSET_NAME` 仍兼容，但新接入建议统一改用 `JumpServer_IP`

## 快速验证

先确认组织和基础连通性，再生成报告：

```bash
python3 scripts/jms_inspection.py list-orgs --profile prod
python3 scripts/jms_inspection.py self-test --profile prod --date 2026-03-20 --org-name 生产组织
python3 scripts/jms_inspection.py self-test --profile prod --date 2026-03-20
bin/jms-report prod 2026-03-20 html
```

如果补问到组织、节点或数据库配置，可以直接写回 profile：

```bash
python3 scripts/jms_inspection.py save-config --profile prod JMS_DEFAULT_ORG_NAME=Default JumpServer_IP=10.1.12.46 JMS_EXEC_ACCOUNT_NAME=root
```

## 常用场景

正式 HTML 报告：

```bash
bin/jms-report prod 2026-03-20 html
python3 scripts/jms_inspection.py report prod 2026-03-20 html --org-name 生产组织
python3 scripts/jms_inspection.py report prod 2026-03-20 html --all-orgs
python3 scripts/jms_inspection.py report prod 2026-03-20 html --style modern
python3 scripts/jms_inspection.py report prod 2026-03-23 html --from 2026-02-23 --to 2026-03-23
```

分析问答：

```bash
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-01 --to 2026-03-20 --type login-anomalies --org-name 生产组织
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-01 --to 2026-03-20 --type top-users --all-orgs
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-20 --to 2026-03-20 --type host-usage --host 10.1.12.46 --org-name 生产组织
```

模板补全：

```bash
python3 scripts/jms_inspection.py fill-template --profile prod --from 2026-03-01 --to 2026-03-20 --input-file /path/to/report.docx --org-name 生产组织
```

依赖与定时：

```bash
python3 scripts/jms_inspection.py ensure-deps all
python3 scripts/jms_inspection.py setup-daily-push --profile prod --org-name 生产组织 --hour 8 --minute 0 --template-file daily
```

## 默认行为

- 正式报告默认推荐 `html`，且默认样式为 `legacy` 正式完整版
- `legacy` 风格优先读取 `JMS_SYSTEM_TARGETS`；未配置时会先复用 `JumpServer_IP / JMS_EXEC_ACCOUNT_NAME`
- `modern` 风格输出控制台摘要版，适合移动端或简报场景
- 如果用户提供的是 IP 且命中多台资产，脚本会优先按 Host/Linux、URL 主机名线索、账号存在性和连通状态择优
- 多组织输出默认先总览，再按组织拆分
- `report ... --from ... --to ...` 仍只生成一份区间汇总报告
- “这台服务器有谁在使用”默认只看 JumpServer 审计 / 活跃会话，负载来自 `uptime`

## 依赖说明

`requirements.txt` 默认预装以下 Python 依赖，减少 skill 安装后首次问答时的临时补装干扰：

- `PyMySQL[rsa]`
- `cryptography`
- `playwright`
- `python-docx`
- `pypdf`

说明：

- 若启用了 `JMS_AUTO_INSTALL=true`，脚本仍会尝试自动补装缺失依赖
- 即使 OpenClaw 安装 skill 时没有预装依赖，脚本也会优先自恢复 `runtime/.venv` 中的 `pip` 再继续补装
- 自动安装补充的 Python 依赖会落到 `runtime/.venv`
- Playwright 浏览器缓存默认落到 `runtime/.playwright-browsers`
- fresh install 的依赖安装会自动带重试和更长下载超时，减少 Chromium 一次性下载抖动导致的失败
- `.doc` 转 `.docx` 仍依赖系统侧 `libreoffice/soffice`
- fresh install 推荐优先执行 `python3 scripts/jms_inspection.py bootstrap --profile <name>`，不要默认直接跑 `ensure-deps all`

## 文档入口

- Skill 路由：`SKILL.md`
- 运行与环境：`references/runtime.md`
- 模板补全：`references/templates.md`
- 触发样例：`references/intent-routing.md`
- 推送与定时：`references/delivery.md`
- 故障排查：`references/troubleshooting.md`
- 目录与元数据：`references/metadata/repo-layout.md`
