# JumpServer Formal Inspection Report

[English](README.en.md)

`jumpserver-inspection-report` 默认面向正式巡检报告场景。用户只要是在要 `巡检报告/日报/月报/legacy 报告`，并且参数齐全，默认就直接走 official `jms-inspect-go` 远程巡检链路，输出 `legacy` HTML 正式报告。

模板补全、Markdown 报告和分析能力仍然保留，但它们已经降级为显式高级能力，只有用户明确提到 `模板/Word/PDF/doc/docx` 或明确说只做分析时才应该使用。

## 小龙虾 / OpenClaw 直接照抄

安装：

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
JMS_OFFICIAL_SSH_USERNAME=root
JMS_OFFICIAL_SSH_PASSWORD=change_me
JMS_REPORT_STYLE=legacy
JMS_LEGACY_PROVIDER=official
JMS_AUTO_INSTALL=true
```

网络受限环境可选补充：

```ini
HTTPS_PROXY=http://127.0.0.1:7890
HTTP_PROXY=http://127.0.0.1:7890
PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=180000
PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST=https://storage.googleapis.com/chrome-for-testing-public
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

安装后先验收 official 链路，再交互使用：

```bash
python3 scripts/jms_inspection.py self-test --profile prod --date 2026-03-20
bin/jms-report prod 2026-03-20 html
```

成功标准：

- `official_binary_ready = true`
- `official_ssh_ready = true`
- `official_check_only_ready = true`
- 最终拿到的是 official HTML 正式报告，不是模板 Markdown

## 默认行为

- 正式报告默认入口：
  - `bin/jms-report <profile> <date> html`
  - `python3 scripts/jms_inspection.py report <profile> <date> html`
- HTML 默认样式是 `legacy`
- `legacy` 默认 provider 是 `official`
- official 链路会通过 SSH 把 `jms_inspect` 上传到 JumpServer 主机远程执行，并回收 HTML/JSON/Excel
- `generate` 兼容入口现在也默认输出 `html`，避免误落回旧模板 Markdown
- `modern` 仅作为控制台摘要版或手机端简报版
- 只有用户明确提到 `模板/Word/PDF/doc/docx` 时，才走 `fill-template` 或 Markdown 模板链路
- 只有用户明确说要分析而不是正式报告时，才走 `analyze`

## 正式报告最短路径

1. 执行 `bootstrap`
2. 写入 profile 最少配置
3. 跑 `self-test`
4. 执行正式报告

```bash
python3 scripts/jms_inspection.py bootstrap --profile prod
python3 scripts/jms_inspection.py save-config --profile prod JUMPSERVER_URL=https://jumpserver.example.com JUMPSERVER_USERNAME=admin JUMPSERVER_PASSWORD=change_me JumpServer_IP=10.1.12.46 JMS_EXEC_ACCOUNT_NAME=root JMS_OFFICIAL_SSH_USERNAME=root JMS_OFFICIAL_SSH_PASSWORD=change_me
python3 scripts/jms_inspection.py self-test --profile prod --date 2026-03-20
bin/jms-report prod 2026-03-20 html
```

## 常用命令

正式报告：

```bash
bin/jms-report prod 2026-03-20 html
python3 scripts/jms_inspection.py report prod 2026-03-20 html --org-name 生产组织
python3 scripts/jms_inspection.py report prod 2026-03-20 html --all-orgs
python3 scripts/jms_inspection.py report prod 2026-03-20 html --style modern
python3 scripts/jms_inspection.py report prod 2026-03-23 html --from 2026-02-23 --to 2026-03-23
python3 scripts/jms_inspection.py generate --profile prod --date 2026-03-20
```

分析：

```bash
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-01 --to 2026-03-20 --type login-anomalies --org-name 生产组织
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-01 --to 2026-03-20 --type top-users --all-orgs
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-20 --to 2026-03-20 --type host-usage --host 10.1.12.46 --org-name 生产组织
```

显式模板场景：

```bash
python3 scripts/jms_inspection.py fill-template --profile prod --from 2026-03-01 --to 2026-03-20 --input-file /path/to/report.docx --org-name 生产组织
python3 scripts/jms_inspection.py generate --profile prod --date 2026-03-20 --format markdown --template-file daily
```

依赖与诊断：

```bash
python3 scripts/jms_inspection.py list-orgs --profile prod
python3 scripts/jms_inspection.py self-test --profile prod --date 2026-03-20
python3 scripts/jms_inspection.py ensure-deps official
python3 scripts/jms_inspection.py ensure-deps all
```

## 依赖说明

`requirements.txt` 默认预装以下 Python 依赖，减少 skill 安装后首次问答时的临时补装干扰：

- `PyMySQL[rsa]`
- `cryptography`
- `playwright`
- `paramiko`
- `python-docx`
- `pypdf`

说明：

- `bootstrap` 默认安装 `db + exec + docx + official`
- fresh install 推荐先跑 `bootstrap`，不要上来就跑 `ensure-deps all`
- `runtime/.venv` 缺少 `pip` 时会先自动恢复
- Playwright 浏览器缓存默认落到 `runtime/.playwright-browsers`
- `exec` 优先复用系统 Chrome/Chromium；本机没有可用浏览器时才尝试下载
- official 巡检远程执行依赖 `paramiko`，本地预编译二进制资产位于 `assets/bin/linux_amd64/jms_inspect`

## 文档入口

- Skill 路由：`SKILL.md`
- 运行与环境：`references/runtime.md`
- 意图路由：`references/intent-routing.md`
- 模板补全：`references/templates.md`
- 推送与定时：`references/delivery.md`
- 故障排查：`references/troubleshooting.md`
- 目录与元数据：`references/metadata/repo-layout.md`
