# 推送载荷与定时计划

## 快速概览

- 当前 skill 能生成飞书消息载荷，但不直接承诺真实发送成功。
- `setup-daily-push` 只写入本地计划文件；真正的常驻执行依赖 `daemon` 或外部进程守护。
- 所有运行态文件统一写入 `runtime/`，避免污染 skill 根目录。

## 飞书载荷

```bash
python3 scripts/jms_inspection.py send-payload --report-file runtime/last_report.md --open-id ou_xxx
python3 scripts/jms_inspection.py send-payload --group-id chat_xxx
```

输出字段包括：

- `action`
- `target_type`
- `target`
- `title`
- `markdown`

规则：

- 未提供 `open_id` / `group_id` 时，目标默认为当前会话
- `send-payload` 输出的是可供上层系统继续消费的 JSON，不是最终送达回执

## 定时计划

### 写入计划

```bash
python3 scripts/jms_inspection.py setup-daily-push --hour 8 --minute 0 --template-file daily
```

计划文件写入：

- `runtime/scheduler_state.json`

### 启动守护进程

```bash
python3 scripts/jms_inspection.py daemon --hour 8 --minute 0 --template-file runtime/template.md
```

规则：

- `daemon` 需要前台常驻；宿主进程退出后计划不会自动恢复
- 若需要跨重启保活，必须由 systemd、supervisor、容器编排或其他外部守护拉起
- 出现临时接口异常时，守护进程按固定退避等待后重试
