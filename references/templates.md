# 模板与补全规则

模板能力仍保留，但它是显式高级能力，不是正式巡检报告默认路径。

## 何时允许使用模板能力

- 只有用户明确提到以下关键词时，才允许走模板链路：
  - `模板`
  - `Word`
  - `PDF`
  - `doc`
  - `docx`
  - `补全文档`
- 用户只是说 `巡检报告/日报/月报/legacy 报告` 时，不要默认走模板。
- 默认正式报告路径仍应是 official `legacy` HTML。

## Markdown 模板

| 来源 | 路径 | 用途 |
|---|---|---|
| 用户模板 | `runtime/template.md` | `save-template` 默认写入位置 |
| 内置日报模板 | `assets/templates/daily.md` | 显式 Markdown 日报模板 |
| 内置管理摘要模板 | `assets/templates/executive.md` | 显式管理摘要模板 |

默认优先级：

```text
runtime/template.md -> assets/templates/daily.md
```

## 文档模板补全

`fill-template` 支持：

- `docx`：优先保留原结构并回传 `docx`
- `doc`：先转成 `docx` 再回填
- `pdf`：提取文本结构后重建 `docx`

规则：

- 先替换占位符，如 `{{ report_date }}`、`{{ executive_summary }}`
- 新内置模板默认还会使用 `{{ report_range }}`、`{{ scope_name }}`、`{{ command_summary }}`、`{{ report_notices }}`
- 模板已有关键章节时，优先在原位置补内容
- 缺少的标准章节追加到文末
- 默认输出目录：`runtime/filled_templates/`

## 标准章节

- 管理摘要
- 巡检概览
- 系统命令巡检
- 关键发现
- 登录情况
- 活跃会话
- 资产状态
- 操作审计
- 安全风险摘要
- 巡检说明
- 处置建议

## 推荐命令

```bash
python3 scripts/jms_inspection.py fill-template --profile prod --from 2026-03-01 --to 2026-03-20 --input-file /path/to/report.docx --org-name 生产组织
python3 scripts/jms_inspection.py fill-template --profile prod --from 2026-03-01 --to 2026-03-20 --input-file /path/to/report.doc --output-file /tmp/report_filled.docx
python3 scripts/jms_inspection.py fill-template --profile prod --from 2026-03-01 --to 2026-03-20 --input-file /path/to/report.pdf --all-orgs
python3 scripts/jms_inspection.py generate --profile prod --date 2026-03-20 --format markdown --template-file daily
```
