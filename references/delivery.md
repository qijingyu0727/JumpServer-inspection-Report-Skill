# 推送载荷与定时计划

## 飞书载荷

```bash
python3 scripts/jms_inspection.py send-payload --report-file runtime/last_report.md --open-id ou_xxx
python3 scripts/jms_inspection.py send-payload --group-id chat_xxx
```

说明：

- `send-payload` 只输出 JSON 载荷
- 不承诺已经真实发送
- 可搭配 `fill-template` 或 `report` 的产物继续由上层系统处理

## 定时计划

```bash
python3 scripts/jms_inspection.py setup-daily-push --profile prod --org-name 生产组织 --hour 8 --minute 0 --template-file daily
python3 scripts/jms_inspection.py daemon --profile prod --org-name 生产组织 --hour 8 --minute 0 --template-file runtime/template.md
```

规则：

- `setup-daily-push` 只写本地计划文件
- `daemon` 需要前台常驻
- 定时计划会继承 `profile` 与组织范围参数
