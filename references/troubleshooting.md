# 常见问题与排查

## 组织解析失败

现象：

- 指定 `--org-name` 后提示未找到或命中多个组织

处理：

- 先执行 `list-orgs --profile <profile>`
- 改用更精确的组织名称
- 如果确实要全量统计，改用 `--all-orgs`

## 缺少命令执行能力

现象：

- `host-usage` 或 `exec-commands` 提示缺少 `playwright`
- OpenClaw 安装 skill 后，`runtime/.venv` 里只有 Python 没有 pip

处理：

- fresh install 先执行 `python3 scripts/jms_inspection.py bootstrap --profile prod`
- 先执行 `python3 scripts/jms_inspection.py ensure-deps exec`
- 或执行 `python3 scripts/jms_inspection.py ensure-deps all`
- 或执行 `python3 -m playwright install chromium`
- 若开启了 `JMS_AUTO_INSTALL=true`，脚本会先尝试恢复 `runtime/.venv` 里的 pip，再自动补装依赖
- 脚本会优先复用系统 Chrome/Chromium；若本机没有浏览器，才会下载 Playwright Chromium
- Chromium 默认下载到 `runtime/.playwright-browsers`
- 若浏览器下载超时，优先在 profile 中补 `HTTPS_PROXY/HTTP_PROXY` 或 `PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST` 后重新执行 `bootstrap`

## 数据库连接失败

现象：

- `legacy` 报告或数据库统计提示缺少 `cryptography`
- MySQL 8 使用 `caching_sha2_password` / `sha256_password` 时无法连接

处理：

- 先执行 `python3 -m pip install -r requirements.txt`
- 或执行 `python3 scripts/jms_inspection.py ensure-deps db`
- 若仍失败，重点检查 DB 账号鉴权方式和 `DB_* / JMS_DB_*` 配置

## official legacy 巡检失败

现象：

- `report ... html --style legacy` 提示缺少 `JMS_OFFICIAL_SSH_USERNAME` / `JMS_OFFICIAL_SSH_PASSWORD`
- `self-test` 中 `official_binary_ready`、`official_ssh_ready` 或 `official_check_only_ready` 为 `false`
- 报告能生成但没有官方 HTML/JSON/Excel bundle

处理：

- fresh install 先执行 `python3 scripts/jms_inspection.py bootstrap --profile prod`
- 单独补装 official 依赖时执行 `python3 scripts/jms_inspection.py ensure-deps official`
- 确认 profile 中至少补齐 `JumpServer_IP`、`JMS_OFFICIAL_SSH_USERNAME`、`JMS_OFFICIAL_SSH_PASSWORD`
- 再执行 `python3 scripts/jms_inspection.py self-test --profile prod --date 2026-03-26`
- 若 `official_check_only_error` 提示远端配置文件不存在，检查 `JMS_OFFICIAL_REMOTE_CONFIG_PATH`
- 若目标环境暂时无法走 official 远程巡检，可临时设置 `JMS_LEGACY_PROVIDER=python` 回退旧链路

## 模板补全失败

现象：

- `.doc` 无法转换
- `.pdf` 输出不是原格式

处理：

- `.doc` 依赖 `libreoffice/soffice`
- `.pdf` 默认允许回退为 `docx`
- 先执行 `python3 scripts/jms_inspection.py ensure-deps pdf`

## 数据为空或接口字段变化

现象：

- 报告或分析能生成，但章节为空

处理：

- 先跑 `self-test`
- 关注 `assets_error` / `login_logs_error` / `operate_logs_error`
- 单个接口失败时脚本会降级，不应直接把整份报告打断

## 单机“谁在使用”为空

现象：

- `host-usage` 返回了 `uptime`，但没有会话记录

处理：

- 该结果只依赖 JumpServer 审计 / 活跃会话
- 没有活跃连接时，应视为“当前未发现会话”，不是脚本错误
