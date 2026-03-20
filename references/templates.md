# 模板与报告结构

## 模板来源

| 来源 | 路径 | 用途 |
|---|---|---|
| 用户模板 | `runtime/template.md` | `save-template` 默认写入位置 |
| 内置日报模板 | `assets/templates/daily.md` | 默认巡检日报 |
| 内置管理摘要模板 | `assets/templates/executive.md` | 面向领导或汇报场景 |

默认模板选择顺序：

```text
runtime/template.md 存在 -> 使用用户模板
否则 -> 使用 assets/templates/daily.md
```

也可以显式传入：

- `--template-file daily`
- `--template-file executive`
- `--template-file /abs/path/to/template.md`

## 模板模式

### 1. 占位符模式

出现 `{{ field_name }}` 时走轻量渲染。当前稳定字段包括：

- `report_date`
- `today_login_logs`
- `asset_status`
- `active_sessions`
- `operate_logs`
- `security_risk_summary`
- `risk_level`
- `executive_summary`
- `key_findings`
- `recommendations`

### 2. 自然语言模式

模板不含占位符时，脚本按 Markdown 章节拆分，并根据段落中的关键词自动路由到：

- 登录异常/爆破风险
- 资产状态/禁用资产/异常资产
- 活跃会话/在线会话
- 操作审计/危险操作
- 风险统计/安全风险

## 推荐命令

```bash
python3 scripts/jms_inspection.py save-template --content-file /path/to/template.md
python3 scripts/jms_inspection.py generate --template-file daily
python3 scripts/jms_inspection.py generate --template-file executive --date 2026-03-20
```

## 维护规则

- 用户自定义模板默认只写入 `runtime/`，不覆盖 `assets/templates/`
- 如果需要新增占位符，优先更新 `scripts/jms_inspection.py` 和本文件中的字段清单
- 如果自然语言模板映射不足，优先增强章节识别逻辑，而不是让用户重写模板
