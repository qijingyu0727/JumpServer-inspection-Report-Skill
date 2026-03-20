# 常见问题与排查

## 配置缺失

现象：

- `generate` 或 `self-test` 直接返回 `API 调用失败，请检查配置`

优先检查：

- `JUMPSERVER_URL` 是否存在
- Bearer 或 Signature 凭据是否成对存在
- 目标环境是否允许当前 Token/Key 访问审计与资产接口

## 模板找不到

现象：

- 报告生成前提示模板文件不存在

处理：

- 不传 `--template-file` 时，脚本默认查找 `runtime/template.md`
- 若用户模板不存在，会自动回退到 `assets/templates/daily.md`
- 传了显式路径时，必须确保路径真实存在

## 数据为空或接口字段变化

现象：

- 报告能生成，但某章节显示“未查询到数据”或“接口不可用”

处理：

- 先运行 `self-test` 看各接口的 `*_error` 字段
- 如果只是单个接口异常，保留降级输出，不要让整份报告失败
- 若 JumpServer 字段名变化，优先补充 `extract_first(...)` 的兼容键

## 定时任务误解

现象：

- 用户以为执行 `setup-daily-push` 后就已经开始后台推送

处理：

- 明确说明 `setup-daily-push` 只写本地状态
- 真正常驻需要执行 `daemon`，并由外部守护保持进程存活
