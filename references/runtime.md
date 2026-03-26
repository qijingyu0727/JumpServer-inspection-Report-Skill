# 运行入口与环境

## 推荐入口

- 首次接入建议先收齐：
  - `JUMPSERVER_URL`
  - `JUMPSERVER_USERNAME`
  - `JUMPSERVER_PASSWORD`
  - `JumpServer_IP`
  - `JMS_EXEC_ACCOUNT_NAME`，未说明时默认 `root`
- 首次把追问得到的配置写回 env/profile：
  - `python3 scripts/jms_inspection.py save-config --profile <profile> KEY=VALUE [KEY=VALUE ...]`
- 正式报告：
  - `bin/jms-report <profile> <date> <format>`
  - `python3 scripts/jms_inspection.py report <profile> <date> <format> [--from <YYYY-MM-DD>] [--to <YYYY-MM-DD>] [--style modern|legacy] [--org-name <名称> | --all-orgs]`
- Fresh install 自举：
  - `python3 scripts/jms_inspection.py bootstrap --profile <profile>`
  - `python3 scripts/jms_inspection.py bootstrap --profile <profile> --include-pdf`
- 组织列表：
  - `python3 scripts/jms_inspection.py list-orgs --profile <profile>`
- 分析：
  - `python3 scripts/jms_inspection.py analyze --profile <profile> --from <YYYY-MM-DD> --to <YYYY-MM-DD> --type login-anomalies|top-users|top-assets|host-usage [--host <资产/IP>] [--top <N>] [--org-name <名称> | --all-orgs]`
- 模板补全：
  - `python3 scripts/jms_inspection.py fill-template --profile <profile> --from <YYYY-MM-DD> --to <YYYY-MM-DD> --input-file <doc|docx|pdf> [--output-file ...]`
- 依赖安装：
  - `python3 scripts/jms_inspection.py ensure-deps db|exec|docx|pdf|all`
  - fresh install 更推荐先执行 `python3 scripts/jms_inspection.py bootstrap --profile <profile>`

## 组织范围规则

- 用户说组织名称时，先执行 `list-orgs`
- 唯一命中则继续
- 多条命中或未命中都要返回候选 / 明确错误
- `--all-orgs` 默认先输出总览，再按组织拆分
- 未显式指定组织时，兼容读取 `JUMPSERVER_ORG`

## 鉴权优先级

1. `JUMPSERVER_TOKEN`
2. `JUMPSERVER_KEY_ID + JUMPSERVER_SECRET_ID`
3. `JUMPSERVER_USERNAME + JUMPSERVER_PASSWORD`

账号密码模式会尝试自举 access key，并在可写 profile 文件中回写。
如果当前环境无法继续创建 access key，会自动回退为 Bearer token 继续执行。

## 可选能力

- `JMS_AUTO_INSTALL=true` 时，脚本会优先尝试自动安装缺失依赖
- Python 依赖安装到 `runtime/.venv`
- 命令巡检依赖 `playwright`
- Playwright 浏览器缓存默认安装到 `runtime/.playwright-browsers`
- `.doc` 转 `.docx` 依赖 `libreoffice/soffice`
- `legacy` 报告依赖 `JMS_SYSTEM_TARGETS`
- 数据库查询依赖 `PyMySQL[rsa]`；若目标库使用 MySQL 8 默认鉴权，还依赖 `cryptography`
- `bootstrap` 默认安装 `db + exec + docx`，避免第一次就因 `pdf/libreoffice` 卡住
- fresh install 的依赖恢复默认带重试和更长浏览器下载超时；若环境出网受限，可在 profile 里补 `HTTPS_PROXY/HTTP_PROXY/PLAYWRIGHT_DOWNLOAD_HOST`
- `JMS_SYSTEM_TARGETS` 为 JSON 数组，每项至少包含 `name`、`asset_name`、`account_name`、`role`
- 未配置 `JMS_SYSTEM_TARGETS` 时，会优先复用 `JumpServer_IP / JMS_EXEC_ACCOUNT_NAME`
- 仍未配置时，才会从 `JUMPSERVER_URL` 解析域名/IP，并尝试把该服务 IP 当作默认巡检节点
- 如果提供的是 IP 且命中多台资产，脚本会优先按 Host/Linux、URL 主机名线索、账号存在性和连通状态择优
- 数据库连接优先级：本地显式 `DB_* / JMS_DB_*` 覆盖 > 远端 `/opt/jumpserver/config/config.txt`
- 远端配置默认读取 `DB_ENGINE / DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME`

## 结果输出

- `report ... html` 写到 `runtime/reports/<profile>/JumpServer巡检报告_<timestamp>.html`
- `report ... markdown` 写到 `runtime/reports/<profile>/JumpServer巡检报告_<timestamp>.md`
- `report ... html` 默认输出新版正式巡检完整版 HTML
- `report ... html --style modern` 输出新版控制台摘要版
- `report ... --from ... --to ...` 仍只生成一份汇总报告，不拆成多份
- `fill-template` 默认写到 `runtime/filled_templates/`
- `analyze` 默认直接输出 Markdown；`--format json` 时输出结构化 JSON
