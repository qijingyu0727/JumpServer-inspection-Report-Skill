# JumpServer Inspection Toolbox

[English](README.en.md)

`jumpserver-inspection-report` 现在是一个面向团队使用的 JumpServer 巡检工具箱，不再只处理固定三参数 HTML 报告。它覆盖正式巡检报告、异常登录与 Top 10 分析、单机负载与会话查询、Word/PDF 模板补全、飞书载荷与本地定时计划；默认 HTML 报告走 `legacy`，按旧版巡检报告的数据面从 JumpServer 服务器本机和数据库生成字段级对齐的完整 HTML，需要显式指定 `--style modern` 才会走新版控制台样式。首次接入默认先提供 5 项：`JUMPSERVER_URL`、`JUMPSERVER_USERNAME`、`JUMPSERVER_PASSWORD`、JumpServer 部署服务器的资产名或 IP，以及连接该服务器的账号名；确认后写回 env/profile 复用。

## 快速开始

1. 复制环境模板并创建 profile：

```bash
python3 -m pip install -r requirements.txt
mkdir -p runtime/profiles
cp .env.example runtime/profiles/prod.env
```

如需命令巡检能力，首次环境还需要安装 Playwright 浏览器：

```bash
python3 -m playwright install chromium
```

2. 编辑 `runtime/profiles/prod.env`，至少补齐：

```ini
JUMPSERVER_URL=https://jumpserver.example.com
JUMPSERVER_USERNAME=admin
JUMPSERVER_PASSWORD=change_me
JMS_EXEC_ASSET_NAME=10.1.12.46
JMS_EXEC_ACCOUNT_NAME=root
```

3. 先看组织列表，确认后再执行：

```bash
python3 scripts/jms_inspection.py list-orgs --profile prod
python3 scripts/jms_inspection.py self-test --profile prod --date 2026-03-20 --org-name 生产组织
python3 scripts/jms_inspection.py self-test --profile prod --date 2026-03-20

如果补问到组织、节点或数据库配置，可以直接写回 profile：

```bash
python3 scripts/jms_inspection.py save-config --profile prod JMS_DEFAULT_ORG_NAME=Default JMS_EXEC_ASSET_NAME=10.1.12.46 JMS_EXEC_ACCOUNT_NAME=root
```
```

4. 生成正式 HTML 报告：

```bash
bin/jms-report prod 2026-03-20 html
python3 scripts/jms_inspection.py report prod 2026-03-20 html --org-name 生产组织
python3 scripts/jms_inspection.py report prod 2026-03-20 html --all-orgs
python3 scripts/jms_inspection.py report prod 2026-03-20 html --style legacy
python3 scripts/jms_inspection.py report prod 2026-03-23 html --from 2026-02-23 --to 2026-03-23
```

## 主要能力

- 正式报告：按 `profile + date + format` 生成 HTML/Markdown 巡检报告，`html` 默认输出 `legacy`
- 旧版报告对齐：默认 `report ... html` 即会从 JumpServer 节点本机采集系统信息，并优先读取远端 `/opt/jumpserver/config/config.txt` 获取 DB 配置后执行 SQL 统计
- 多组织：支持按组织名称解析，或对全部组织输出“先总览再分组织”的结果
- 分析问答：支持异常登录、Top 10 用户/资产排行、单机使用情况
- 模板补全：支持 `doc/docx/pdf` 巡检模板回填，默认回传 `docx`
- 安装体验：`requirements.txt` 预置 `PyMySQL[rsa]`、`cryptography`、`playwright`、`python-docx`、`pypdf`，降低首次问答时的临时补装干扰
- 依赖自恢复：仍支持自动补装缺失的浏览器、文档处理依赖和必要系统工具
- 配置复用：追问得到的参数可通过 `save-config` 直接写回 env/profile
- 区间汇总：`report`/`generate` 支持 `--from/--to`，长时间范围仍只生成一份汇总报告

## 常用命令

```bash
python3 scripts/jms_inspection.py list-orgs --profile prod
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-01 --to 2026-03-20 --type login-anomalies --org-name 生产组织
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-01 --to 2026-03-20 --type top-users --all-orgs
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-20 --to 2026-03-20 --type host-usage --host 10.1.12.46 --org-name 生产组织
python3 scripts/jms_inspection.py fill-template --profile prod --from 2026-03-01 --to 2026-03-20 --input-file /path/to/report.docx --org-name 生产组织
python3 scripts/jms_inspection.py report prod 2026-03-20 html --style legacy
python3 scripts/jms_inspection.py ensure-deps all
python3 scripts/jms_inspection.py setup-daily-push --profile prod --org-name 生产组织 --hour 8 --minute 0 --template-file daily
```

## 运行说明

- 正式报告默认推荐 `html`，且默认样式为 `legacy`
- `legacy` 风格优先读取 `JMS_SYSTEM_TARGETS`；未配置时会先复用 `JMS_EXEC_ASSET_NAME/JMS_EXEC_ACCOUNT_NAME`
- 数据库查询默认使用 `PyMySQL[rsa]`；若目标库启用 MySQL 8 的 `caching_sha2_password` / `sha256_password` 鉴权，还需要 `cryptography`
- 如果用户提供的是 IP 且命中多台资产，脚本会优先按 Host/Linux、URL 主机名线索、账号存在性和连通状态择优
- 分析类默认直接返回结构化结果，不强制落文件
- 用户说组织名称时，脚本按名称精确匹配或唯一模糊匹配；多条命中时需要追问
- “这台服务器有谁在使用”默认只看 JumpServer 审计 / 会话数据
- `requirements.txt` 会在 skill 安装阶段预装 Python 依赖；自动安装仍会把补充依赖放进 `runtime/.venv`

## 文档入口

- Skill 路由：`SKILL.md`
- 运行与环境：`references/runtime.md`
- 模板补全：`references/templates.md`
- 触发样例：`references/intent-routing.md`
- 推送与定时：`references/delivery.md`
- 故障排查：`references/troubleshooting.md`
