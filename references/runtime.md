# 运行入口与环境

## 快速概览

- 正式入口固定为 `python3 scripts/jms_inspection.py ...`。
- 运行前必须先满足 `JUMPSERVER_URL`，并二选一提供 `JUMPSERVER_TOKEN` 或 `JUMPSERVER_KEY_ID + JUMPSERVER_SECRET_ID`。
- 所有敏感信息只做存在性判断与脱敏提示，不在输出中回显原文。
- `self-test` 用于验证关键接口是否可连通；`update-token` 只输出标准化更新指引。

## 环境变量

| 变量 | 要求 | 说明 |
|---|---|---|
| `JUMPSERVER_URL` | 必填 | JumpServer 基础地址，脚本会自动去掉末尾 `/` |
| `JUMPSERVER_TOKEN` | Bearer 模式必填 | 直接访问 API 的 Token |
| `JUMPSERVER_KEY_ID` | Signature 模式必填 | API Key ID |
| `JUMPSERVER_SECRET_ID` | Signature 模式必填 | API Key Secret |

规则：

- Bearer 和 Signature 只允许命中一种模式；脚本优先使用 Bearer。
- 地址缺失、凭据缺失或接口报错时，对用户只返回统一友好错误，不暴露 traceback。
- 如果用户说“更新 Token”，固定引导其更新环境变量并重启宿主进程。

## 标准检查顺序

```text
检查 JUMPSERVER_URL
  -> 检查 Bearer 或 Signature 凭据
  -> 执行 self-test 或 generate
  -> 失败时返回统一错误 + 下一步建议
```

## 正式命令

```bash
python3 scripts/jms_inspection.py self-test --date 2026-03-20
python3 scripts/jms_inspection.py generate --date 2026-03-20
python3 scripts/jms_inspection.py update-token
```

## 输出约定

- `generate` 默认把报告写到 `runtime/last_report.md`
- `self-test` 输出 JSON 摘要，包含计数、错误字段和样例数据
- `setup-daily-push` 把计划写到 `runtime/scheduler_state.json`
- `self-improve` 把待办写到 `runtime/self_improve.todo.md`
