---
name: jumpserver-inspection-report
description: 作为 JumpServer 巡检工具箱处理“巡检报告/日报/月报”“legacy 正式巡检完整版”“异常登录与 Top 10 分析”“单机负载与谁在使用”“按 Word/PDF 模板补全巡检报告”“飞书载荷与定时巡检”等请求。首次默认要求用户先提供 JUMPSERVER_URL、JUMPSERVER_USERNAME、JUMPSERVER_PASSWORD、JumpServer 部署服务器的资产名或 IP、连接该服务器的账号名，以及 official 巡检所需的 SSH 用户名和密码；确认后写回 env/profile 复用。
---

# JumpServer Inspection Toolbox

## 路由原则

- 先判断请求属于哪一类，再决定是否执行：
  - 报告生成：`巡检报告`、`巡检日报`、`昨天的巡检日报`、`上个月巡检报告`
  - 摘要分析：`昨天有哪些异常登录`、`最近哪些用户和资产登录比较多`
  - 单机巡检：`10.1.12.46 这台服务器的负载如何，有谁在使用`
  - 模板补全：`按这个 Word/PDF 模板补全巡检报告`
  - 附属能力：`输出飞书载荷`、`设置每天 08:00 定时巡检`
- 命中后优先补齐高价值参数：
  - `组织范围`：某个组织还是全部组织
  - `profile`
  - `日期/时间范围`
  - `输出格式`
- 首次接入默认先收齐这 7 项：
  - `JUMPSERVER_URL`
  - `JUMPSERVER_USERNAME`
  - `JUMPSERVER_PASSWORD`
  - `JumpServer_IP`：JumpServer 部署服务器的资产名或 IP
  - `JMS_EXEC_ACCOUNT_NAME`：连接该服务器的账号名，用户未说明时默认 `root`
  - `JMS_OFFICIAL_SSH_USERNAME`
  - `JMS_OFFICIAL_SSH_PASSWORD`
- 理想执行链路固定为一条：
  - 先用账号密码登录
  - 若 profile 中已存在 `JUMPSERVER_KEY_ID/JUMPSERVER_SECRET_ID`，直接复用，不重复创建
  - 若缺失则尝试创建 access key 并写回 env/profile
  - 若环境不允许继续创建 access key，则回退 Bearer token 完成当前任务
  - 拿到这些项后立即写回 env/profile
  - `legacy` 报告默认再通过 official 引擎 SSH 到 JumpServer 主机，上传 `jms_inspect` 二进制、读取 `/opt/jumpserver/config/config.txt` 并远程完成数据库/Redis/服务巡检
- 其他缺少的运行信息必须追问，不做隐式猜测。问到后立即写回 env/profile，供后续问答直接复用：
  - `JUMPSERVER_ORG` / `JMS_DEFAULT_ORG_NAME`
  - `JumpServer_IP` / `JMS_EXEC_ACCOUNT_NAME`
  - `JMS_OFFICIAL_SSH_USERNAME` / `JMS_OFFICIAL_SSH_PASSWORD`
  - `JMS_SYSTEM_TARGETS`
  - `DB_*` / `JMS_DB_*`
- 如果用户要求的是“正式巡检报告 / 旧模版风格报告 / 带系统信息和磁盘命令内容的报告”，而当前还没有 JumpServer 服务器资产/IP 与账号映射：
  - 必须先补齐 JumpServer 部署服务器的资产名或 IP
  - 必须继续补齐连接账号，用户未说明时按 `root` 追认
  - 在这些信息补齐前，不要把残缺版 API 摘要当成完整巡检报告直接交付
- 写回环境时优先使用：
  - `python3 scripts/jms_inspection.py save-config --profile <profile> KEY=VALUE ...`
  - 若当前 turn 直接编辑 env 文件更合适，也可以直接更新对应 profile 文件
  - 新接入统一使用 `JumpServer_IP`；旧字段 `JMS_EXEC_ASSET_NAME` 仅作兼容
- 组织名称优先按名称解析；唯一命中直接继续，0 条或多条命中时列候选并追问。
- 用户明确要“全部组织”时，输出默认先总览，再给分组织结果。
- 正式报告仍优先走 `html`，默认按 `legacy` 输出新版正式巡检完整版；`modern` 作为控制台摘要版按需切换。分析类请求默认直接返回结构化内容，不强制落文件。
- 用户要求正式巡检报告、`legacy` 完整巡检报告、带系统信息和数据库统计的完整报告时，默认走 `report ... html`（即 `legacy` 正式完整版）：
  - 默认 `JMS_LEGACY_PROVIDER=official`
  - 由 skill 通过 SSH 把 official `jms_inspect` 二进制上传到 JumpServer 节点远程执行
  - 数据库统计默认先读取远端 `/opt/jumpserver/config/config.txt`
  - 若本地显式提供 `DB_* / JMS_DB_*`，则本地覆盖远端配置
  - 若明确给的是 IP 且命中多台资产，优先按 Host/Linux、URL 主机名线索、账号存在性和连通状态择优；仍无法唯一确定时再追问
  - 用户明确要求控制台摘要版、手机端简报版时，再追加 `--style modern`
- 不伪造实时数据。单机“谁在使用”只看 JumpServer 审计 / 活跃会话；负载来自 `uptime`。

## 主入口

- 正式巡检报告：
  - `bin/jms-report <profile> <date> <format>`
  - `python3 scripts/jms_inspection.py report <profile> <date> <format> [--from <YYYY-MM-DD>] [--to <YYYY-MM-DD>] [--style modern|legacy] [--org-name <名称> | --all-orgs]`
- 首次安装自举：
  - `python3 scripts/jms_inspection.py bootstrap --profile <profile>`
  - `python3 scripts/jms_inspection.py bootstrap --profile <profile> --include-pdf`
- 组织列表：
  - `python3 scripts/jms_inspection.py list-orgs --profile <profile>`
- 分析问答：
  - `python3 scripts/jms_inspection.py analyze --profile <profile> --from <YYYY-MM-DD> --to <YYYY-MM-DD> --type login-anomalies|top-users|top-assets|host-usage [--host <资产/IP>] [--top <N>] [--org-name <名称> | --all-orgs]`
- 模板补全：
  - `python3 scripts/jms_inspection.py fill-template --profile <profile> --from <YYYY-MM-DD> --to <YYYY-MM-DD> --input-file <doc|docx|pdf> [--output-file ...] [--org-name <名称> | --all-orgs]`
- 自动安装依赖：
  - `python3 scripts/jms_inspection.py ensure-deps db|exec|docx|official|pdf|all`
- 写回配置：
  - `python3 scripts/jms_inspection.py save-config --profile <profile> KEY=VALUE [KEY=VALUE ...]`

## 关键行为

- 自然时间口径固定：
  - `昨天` = 前一自然日
  - `上个月` = 上一自然月
  - `最近` = 最近 7 天
- 用户问“近一个月 / 最近三个月 / 上个月 / 一段时间”时，只生成一份区间汇总报告：
  - 先把自然语言落成明确 `from/to`
  - 然后执行单次 `report` 或 `generate`
  - 不要拆成多个日报/月报分别输出
- `Top N` 默认读取 `JMS_DEFAULT_TOP_N`，未设置时为 `10`。
- 分析类默认“先表格后摘要”；若表格不适合，则退化为自然语言摘要。
- 模板补全规则：
  - `docx`：优先保留原结构并回传 `docx`
  - `doc`：自动转成 `docx` 后回传
  - `pdf`：优先提取结构；无法稳定保留原版式时回退为 `docx`
  - 模板已有章节优先补齐；缺少的关键章节追加到文末
- 能力缺失时优先尝试自动安装：
  - fresh install 优先执行 `bootstrap`，不要默认先跑 `ensure-deps all`
  - skill 安装阶段应先安装 `requirements.txt` 中声明的 `PyMySQL[rsa]`、`cryptography`、`playwright`、`paramiko`、`python-docx`、`pypdf`
  - Python 依赖安装到 `runtime/.venv`
  - `playwright` 缺失时补装浏览器，并默认写到 `runtime/.playwright-browsers`
  - official 巡检二进制默认从 `assets/bin/linux_amd64/jms_inspect` 准备到 `runtime/bin/jms_inspect`
  - fresh install 的补装流程自带 pip 恢复、重试和更长浏览器下载超时
  - 文档处理依赖按需安装
  - `legacy` 数据库采集依赖 `PyMySQL[rsa]`；MySQL 8 默认鉴权场景还依赖 `cryptography`
  - 检测到系统包管理器时允许安装如 `libreoffice`

## 边界与禁止事项

- 没有 `profile`、组织范围、时间范围这类关键参数时，不要模糊执行。
- 不要把一次性 `setup-daily-push` 说成已经在后台常驻运行。
- 不要声称已经真实发送飞书消息；`send-payload` 只输出载荷。
- 不要在输出中回显 Token / Secret / Password 原文。
- 遇到多组织命中冲突、鉴权缺失、文档转换失败或依赖安装失败时，要返回明确阻塞点和下一步动作。

## 文档入口

- 运行方式与环境：`references/runtime.md`
- 模板与补全规则：`references/templates.md`
- 推送与定时：`references/delivery.md`
- 触发样例与追问规则：`references/intent-routing.md`
- 常见问题：`references/troubleshooting.md`
- 目录与元数据：`references/metadata/repo-layout.md`
