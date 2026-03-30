# 意图路由与追问规则

## 默认意图

| 意图 | 典型问法 | 首选动作 |
|---|---|---|
| 正式报告 | 给我来个巡检报告 / 给我生成昨天的巡检日报 / 发下上个月的巡检报告 / 我想获取近一个月的巡检报告 / 给我 legacy 正式报告 | 补齐组织范围、profile、日期区间后执行 `report <profile> <date> html` |
| 摘要分析 | 昨天有哪些异常登录 / 最近哪些用户和资产登录比较多 | 仅在用户明确要分析时执行 `analyze` |
| 单机巡检 | 10.1.12.46 这台服务器的负载如何，有谁在使用 | 仅在用户明确要单机分析时执行 `host-usage` |
| 模板补全 | 按这个 Word 模板补全巡检报告 / 根据这个 PDF 模板回填 / 按 docx 文档补全文档 | 仅在用户明确提到 `模板/Word/PDF/doc/docx` 时执行 `fill-template` |
| 附属能力 | 输出飞书载荷 / 设置每天 08:00 定时巡检 | 执行 `send-payload` / `setup-daily-push` / `daemon` |

## 正式报告强制规则

- 用户只要是在要 `巡检报告/日报/月报/正式报告/legacy 报告`，默认就视为正式报告。
- 默认报告路径固定为：
  - `bin/jms-report <profile> <date> html`
  - 或 `python3 scripts/jms_inspection.py report <profile> <date> html`
- 不要把以下路径当成正式报告默认入口：
  - `generate --format markdown`
  - `fill-template`
  - `runtime/template.md`
  - 任意旧 Markdown 模板文件
- 成功时优先返回官方 HTML 报告路径；如存在 `_official_bundle/`，同时返回 bundle 目录。

## 必追问项

- 首次接入默认先收齐：
  - `JUMPSERVER_URL`
  - `JUMPSERVER_USERNAME`
  - `JUMPSERVER_PASSWORD`
  - JumpServer 部署服务器的资产名或 IP，对应 `JumpServer_IP`
  - 连接该服务器的账号名，对应 `JMS_EXEC_ACCOUNT_NAME`，未说明时默认 `root`
  - official 巡检 SSH 用户名，对应 `JMS_OFFICIAL_SSH_USERNAME`
  - official 巡检 SSH 密码，对应 `JMS_OFFICIAL_SSH_PASSWORD`
- 组织范围：`哪个组织` 还是 `全部组织`
- profile：运行哪个环境
- 时间：`昨天 / 上个月 / 最近` 要落成明确日期范围
- 如果用户明确提到“巡检报告”“月度巡检报告”“legacy 正式报告”“带数据库和系统信息的完整报告”：
  - 缺服务器资产/IP 和 official SSH 时必须追问
  - 不能跳过系统巡检部分就交付最终版
  - 不能退回 Markdown 模板冒充正式报告

## 追问后落盘

- 用户回答了缺失配置后，不要只在当前 turn 里记住
- 应把结果写回当前 env/profile，供后续问答直接复用
- 推荐写法：
  - `python3 scripts/jms_inspection.py save-config --profile <profile> KEY=VALUE [KEY=VALUE ...]`
- 常见落盘项：
  - 默认组织：`JUMPSERVER_ORG`、`JMS_DEFAULT_ORG_NAME`
  - 正式报告节点：`JumpServer_IP`、`JMS_EXEC_ACCOUNT_NAME`
  - official 巡检 SSH：`JMS_OFFICIAL_SSH_USERNAME`、`JMS_OFFICIAL_SSH_PASSWORD`、`JMS_OFFICIAL_SSH_PORT`
  - 数据库覆盖：`DB_*` 或 `JMS_DB_*`
  - 首次确认 `JumpServer_IP` 和 `JMS_EXEC_ACCOUNT_NAME` 后，也可以同步写一份 `JMS_SYSTEM_TARGETS`

## 报告输出规则

- 用户询问长时间范围时，只输出一份汇总报告
- 不把“近一个月”拆成多个日报
- 正式报告默认输出 official `legacy` HTML
- 用户明确要求控制台简报版、移动端简版时，才切到 `--style modern`
- 用户明确提供历史 Word/PDF/doc/docx 模板时，才进入模板补全链路

## 组织解析

- 用户输入组织名称时，先执行 `list-orgs`
- 唯一命中：直接继续
- 0 条命中：提示未找到组织
- 多条命中：列候选组织并追问更精确名称

## 自然时间默认口径

- `昨天` = 前一自然日
- `上个月` = 上一自然月
- `最近` = 最近 7 天

## 默认输出

- 报告类：优先 `html`
- 分析类：先表格后摘要，`Top N` 默认 `10`
- 模板类：`docx` 原样回传；`doc/pdf` 统一回 `docx`
- 服务器资产如果用户给的是 IP：
  - 先按 Host/Linux 类型、URL 主机名线索、账号存在性和连通状态自动择优
  - 仍然多命中时再列候选追问

## 不应触发

- 非 JumpServer 的通用 Linux 运维问答
- 与堡垒机无关的文档润色、纯文档翻译
- 用户只是想看说明文档，不希望执行任何脚本
