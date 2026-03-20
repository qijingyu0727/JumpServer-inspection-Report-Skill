#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_ERROR_MESSAGE = "API 调用失败，请检查配置"
DEFAULT_TEMPLATE_NAME = "daily"
SKILL_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = SKILL_DIR / "assets"
TEMPLATE_DIR = ASSETS_DIR / "templates"
RUNTIME_DIR = SKILL_DIR / "runtime"
BUILTIN_DAILY_TEMPLATE_FILE = TEMPLATE_DIR / "daily.md"
BUILTIN_EXECUTIVE_TEMPLATE_FILE = TEMPLATE_DIR / "executive.md"
USER_TEMPLATE_FILE = RUNTIME_DIR / "template.md"
DEFAULT_STATE_FILE = RUNTIME_DIR / "scheduler_state.json"
DEFAULT_OUTPUT_FILE = RUNTIME_DIR / "last_report.md"


class JumpServerApiError(RuntimeError):
    pass


def ensure_parent_dir(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def resolve_default_template_file() -> Path:
    if USER_TEMPLATE_FILE.exists():
        return USER_TEMPLATE_FILE
    return BUILTIN_DAILY_TEMPLATE_FILE


def resolve_template_file(template_file: Optional[str]) -> Path:
    if not template_file:
        return resolve_default_template_file()

    alias = template_file.strip().lower()
    if alias in ("daily", "default"):
        return BUILTIN_DAILY_TEMPLATE_FILE
    if alias in ("executive", "leader"):
        return BUILTIN_EXECUTIVE_TEMPLATE_FILE

    return Path(template_file).expanduser().resolve()


def resolve_output_file(output_file: Optional[str]) -> Path:
    if not output_file:
        return DEFAULT_OUTPUT_FILE
    return Path(output_file).expanduser().resolve()


def get_env_config() -> Dict[str, str]:
    base_url = os.getenv("JUMPSERVER_URL", "").strip()
    token = os.getenv("JUMPSERVER_TOKEN", "").strip()
    key_id = os.getenv("JUMPSERVER_KEY_ID", "").strip()
    secret_id = os.getenv("JUMPSERVER_SECRET_ID", "").strip()

    if not base_url:
        raise JumpServerApiError(DEFAULT_ERROR_MESSAGE)

    if token:
        auth_mode = "bearer"
    elif key_id and secret_id:
        auth_mode = "signature"
    else:
        raise JumpServerApiError(DEFAULT_ERROR_MESSAGE)

    return {
        "base_url": base_url.rstrip("/"),
        "token": token,
        "key_id": key_id,
        "secret_id": secret_id,
        "auth_mode": auth_mode,
    }


def normalize_response_data(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("results", "data", "items", "rows"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        return [data]
    return []


def build_signature_headers(endpoint: str, params: Optional[Dict[str, Any]], key_id: str, secret_id: str) -> Dict[str, str]:
    accept = "application/json"
    date = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
    query = urllib.parse.urlencode(params or {}, doseq=True)
    path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    if query:
        path = f"{path}?{query}"
    signing_text = f"(request-target): get {path}\naccept: {accept}\ndate: {date}"
    signature = base64.b64encode(hmac.new(secret_id.encode(), signing_text.encode(), hashlib.sha256).digest()).decode()
    return {
        "Accept": accept,
        "Date": date,
        "Authorization": f'Signature keyId="{key_id}",algorithm="hmac-sha256",headers="(request-target) accept date",signature="{signature}"',
    }


def http_get_json(url: str, headers: Dict[str, str], timeout: int = 15) -> Any:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "ignore")
        return json.loads(body)


def fetch_jumpserver_data(endpoint: str, params: Optional[Dict[str, Any]] = None, timeout: int = 15) -> List[Dict[str, Any]]:
    cfg = get_env_config()
    query = urllib.parse.urlencode(params or {}, doseq=True)
    url = f"{cfg['base_url']}{endpoint}"
    if query:
        url = f"{url}?{query}"

    if cfg["auth_mode"] == "bearer":
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {cfg['token']}",
        }
    else:
        headers = build_signature_headers(endpoint, params, cfg["key_id"], cfg["secret_id"])

    last_error = None
    for attempt in range(3):
        try:
            payload = http_get_json(url, headers=headers, timeout=timeout)
            return normalize_response_data(payload)
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in (429, 500, 502, 503, 504):
                break
            time.sleep(min(2 ** attempt, 5))
        except Exception as exc:
            last_error = exc
            time.sleep(min(2 ** attempt, 5))
    raise JumpServerApiError(DEFAULT_ERROR_MESSAGE) from last_error


def humanize_value(value: Any, default: str = "-") -> str:
    if value in (None, ""):
        return default
    if isinstance(value, dict):
        for key in ("label", "name", "value", "title"):
            if value.get(key) not in (None, ""):
                return str(value[key])
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        if not value:
            return default
        return ", ".join(humanize_value(v, default=default) for v in value)
    return str(value)


def is_success_status(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, dict):
        if "value" in value:
            return is_success_status(value.get("value"))
        if "label" in value:
            return str(value.get("label", "")).strip().lower() in ("success", "successful", "ok", "passed")
        return False
    text = str(value).strip().lower()
    return text in ("1", "true", "success", "successful", "ok", "passed")


def extract_first(data: Dict[str, Any], *keys: str, default: Any = "-") -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


def parse_date(value: Optional[str] = None) -> datetime:
    if value:
        return datetime.strptime(value, "%Y-%m-%d")
    return datetime.now()


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_template(template_file: Path) -> str:
    if not template_file.exists():
        raise FileNotFoundError(f"模板文件不存在：{template_file}")
    return template_file.read_text(encoding="utf-8")


def save_template(content: str, template_file: Path = USER_TEMPLATE_FILE) -> Path:
    ensure_parent_dir(template_file)
    template_file.write_text(content, encoding="utf-8")
    return template_file


def detect_template_mode(template_text: str) -> str:
    if re.search(r"\{\{\s*[a-zA-Z0-9_]+\s*\}\}", template_text):
        return "placeholder"
    return "natural"


def get_login_logs(report_date: str) -> List[Dict[str, Any]]:
    target_date = parse_date(report_date)
    today = datetime.now().date()
    days = max((today - target_date.date()).days, 0)
    return fetch_jumpserver_data("/api/v1/audits/login-logs/", params={"days": days, "limit": 100})


def get_assets() -> List[Dict[str, Any]]:
    return fetch_jumpserver_data("/api/v1/assets/assets/", params={"limit": 100})


def get_active_sessions() -> List[Dict[str, Any]]:
    try:
        return fetch_jumpserver_data("/api/v1/audits/user-sessions/", params={"is_active": "true", "limit": 100})
    except JumpServerApiError:
        return fetch_jumpserver_data("/api/v1/terminal/sessions/", params={"is_finished": "false", "limit": 100})


def get_operate_logs() -> List[Dict[str, Any]]:
    return fetch_jumpserver_data("/api/v1/audits/operate-logs/", params={"days": 1, "limit": 100})


def safe_fetch(fetcher, fallback_message: str):
    try:
        return fetcher(), None
    except Exception:
        return [], fallback_message


def build_data_bundle(report_date: str) -> Dict[str, Any]:
    login_logs, login_error = safe_fetch(lambda: get_login_logs(report_date), "登录日志接口不可用")
    assets, assets_error = safe_fetch(get_assets, "资产接口不可用")
    active_sessions, sessions_error = safe_fetch(get_active_sessions, "活跃会话接口不可用")
    operate_logs, operate_error = safe_fetch(get_operate_logs, "操作审计接口不可用")

    operate_logs_text = summarize_operate_logs(operate_logs)
    if operate_error:
        operate_logs_text = f"{operate_error}。\n{operate_logs_text}"

    context = {
        "report_date": report_date,
        "today_login_logs_raw": login_logs,
        "assets_raw": assets,
        "active_sessions_raw": active_sessions,
        "operate_logs_raw": operate_logs,
        "today_login_logs": summarize_login_logs(login_logs) if not login_error else f"{login_error}。\n{summarize_login_logs(login_logs)}",
        "asset_status": summarize_assets(assets) if not assets_error else f"{assets_error}。\n{summarize_assets(assets)}",
        "active_sessions": summarize_active_sessions(active_sessions) if not sessions_error else f"{sessions_error}。\n{summarize_active_sessions(active_sessions)}",
        "operate_logs": operate_logs_text,
        "security_risk_summary": summarize_security_risks(login_logs, active_sessions, operate_logs),
    }
    context["risk_level"] = build_risk_level(context)
    context["executive_summary"] = build_executive_summary(context)
    context["key_findings"] = build_key_findings(context)
    context["recommendations"] = build_recommendations(context)
    return context


def summarize_login_logs(logs: List[Dict[str, Any]]) -> str:
    if not logs:
        return "今日未查询到登录日志。"
    total = len(logs)
    failures = []
    success = 0
    by_user = Counter()
    by_ip = Counter()
    for item in logs:
        username = humanize_value(extract_first(item, "username", "user", "user_display", default="未知用户"), default="未知用户")
        ip = humanize_value(extract_first(item, "ip", "remote_addr", "client_ip", default="未知IP"), default="未知IP")
        status_value = extract_first(item, "status", "is_success", "success", default="未知")
        message = str(extract_first(item, "reason", "message", "detail", default=""))
        is_success = is_success_status(status_value)
        if is_success:
            success += 1
        else:
            failures.append({
                "username": username,
                "ip": ip,
                "message": message,
                "time": extract_first(item, "datetime", "date_start", "timestamp", "created_at", default="-"),
            })
            by_user[username] += 1
            by_ip[ip] += 1
    lines = [f"- 登录日志总数：{total}", f"- 登录成功：{success}", f"- 登录失败：{len(failures)}"]
    if failures:
        lines.append("- 失败用户 TOP：")
        for username, cnt in by_user.most_common(5):
            lines.append(f"  - {username}：{cnt} 次")
        lines.append("- 失败来源 IP TOP：")
        for ip, cnt in by_ip.most_common(5):
            lines.append(f"  - {ip}：{cnt} 次")
        lines.append("- 失败明细（最多 10 条）：")
        for item in failures[:10]:
            msg = f"，原因：{item['message']}" if item["message"] else ""
            lines.append(f"  - [{item['time']}] 用户 {item['username']} 来自 {item['ip']}{msg}")
    else:
        lines.append("- 今日未发现登录失败记录。")
    return "\n".join(lines)


def summarize_assets(assets: List[Dict[str, Any]]) -> str:
    if not assets:
        return "未查询到资产数据。"
    total = len(assets)
    enabled = 0
    disabled = 0
    suspicious = 0
    platform_counter = Counter()
    for item in assets:
        platform = humanize_value(extract_first(item, "platform", "platform_display", "os", default="未知平台"), default="未知平台")
        platform_counter[platform] += 1
        is_active = extract_first(item, "is_active", "active", default=True)
        if str(is_active).lower() in ("false", "0", "disabled", "inactive") or is_active is False:
            disabled += 1
        else:
            enabled += 1
        status = str(extract_first(item, "status", "connectivity", "health_status", default="")).lower()
        if any(k in status for k in ["error", "fail", "offline", "unknown", "abnormal"]):
            suspicious += 1
    lines = [f"- 资产总数：{total}", f"- 启用资产：{enabled}", f"- 禁用资产：{disabled}", f"- 疑似异常资产：{suspicious}", "- 资产平台分布："]
    for name, cnt in platform_counter.most_common(10):
        lines.append(f"  - {name}：{cnt}")
    return "\n".join(lines)


def summarize_active_sessions(sessions: List[Dict[str, Any]]) -> str:
    if not sessions:
        return "当前无活跃会话。"
    total = len(sessions)
    user_counter = Counter()
    asset_counter = Counter()
    risky_items = []
    for item in sessions:
        username = humanize_value(extract_first(item, "user", "username", "user_display", default="未知用户"), default="未知用户")
        asset = humanize_value(extract_first(item, "asset", "asset_display", "asset_name", "host", default="未知资产"), default="未知资产")
        remote_addr = humanize_value(extract_first(item, "remote_addr", "ip", "client_ip", default="未知IP"), default="未知IP")
        login_from = humanize_value(extract_first(item, "login_from", "protocol", "type", default="未知方式"), default="未知方式")
        user_counter[username] += 1
        asset_counter[asset] += 1
        if remote_addr in ("未知IP", "127.0.0.1"):
            risky_items.append(f"- 用户 {username} 的会话来源地址异常：{remote_addr}")
        if login_from.lower() in ("telnet",):
            risky_items.append(f"- 用户 {username} 使用高风险协议：{login_from}")
    lines = [f"- 当前活跃会话数：{total}", "- 在线用户 TOP："]
    for name, cnt in user_counter.most_common(5):
        lines.append(f"  - {name}：{cnt} 个会话")
    lines.append("- 会话目标资产 TOP：")
    for name, cnt in asset_counter.most_common(5):
        lines.append(f"  - {name}：{cnt} 个会话")
    if risky_items:
        lines.append("- 风险提示：")
        lines.extend(risky_items[:10])
    else:
        lines.append("- 暂未发现明显高风险活跃会话。")
    return "\n".join(lines)


def summarize_operate_logs(logs: List[Dict[str, Any]]) -> str:
    if not logs:
        return "未查询到操作审计日志。"
    total = len(logs)
    user_counter = Counter()
    action_counter = Counter()
    for item in logs:
        username = humanize_value(extract_first(item, "user", "username", "operator", default="未知用户"), default="未知用户")
        action = humanize_value(extract_first(item, "action", "resource", "operate", "type", default="未知动作"), default="未知动作")
        user_counter[username] += 1
        action_counter[action] += 1
    lines = [f"- 操作审计记录数：{total}", "- 高频操作用户："]
    for name, cnt in user_counter.most_common(5):
        lines.append(f"  - {name}：{cnt} 次")
    lines.append("- 高频操作类型：")
    for name, cnt in action_counter.most_common(10):
        lines.append(f"  - {name}：{cnt} 次")
    return "\n".join(lines)


def summarize_security_risks(login_logs: List[Dict[str, Any]], active_sessions: List[Dict[str, Any]], operate_logs: List[Dict[str, Any]]) -> str:
    failure_by_ip = Counter()
    failure_by_user = Counter()
    risky_protocols = 0
    for item in login_logs:
        status_value = extract_first(item, "status", "is_success", "success", default="未知")
        is_success = is_success_status(status_value)
        if not is_success:
            failure_by_ip[humanize_value(extract_first(item, "ip", "remote_addr", "client_ip", default="未知IP"), default="未知IP")] += 1
            failure_by_user[humanize_value(extract_first(item, "username", "user", default="未知用户"), default="未知用户")] += 1
    for item in active_sessions:
        protocol = str(extract_first(item, "login_from", "protocol", "type", default="")).lower()
        if protocol in ("telnet",):
            risky_protocols += 1
    risk_lines = []
    blast_ips = [f"{ip}({cnt})" for ip, cnt in failure_by_ip.items() if cnt >= 5]
    blast_users = [f"{user}({cnt})" for user, cnt in failure_by_user.items() if cnt >= 5]
    if blast_ips:
        risk_lines.append(f"- 疑似爆破来源 IP：{', '.join(sorted(blast_ips))}")
    if blast_users:
        risk_lines.append(f"- 高频失败账号：{', '.join(sorted(blast_users))}")
    if risky_protocols:
        risk_lines.append(f"- 检测到高风险协议会话：{risky_protocols} 个")
    dangerous_actions = 0
    for item in operate_logs:
        action = str(extract_first(item, "action", "resource", "operate", "type", default="")).lower()
        if any(k in action for k in ["delete", "remove", "drop", "force", "destroy"]):
            dangerous_actions += 1
    if dangerous_actions:
        risk_lines.append(f"- 高风险操作审计记录：{dangerous_actions} 条")
    return "\n".join(risk_lines) if risk_lines else "- 今日未识别出显著安全风险。"


def render_placeholder_template(template_text: str, context: Dict[str, Any]) -> str:
    def repl(match: re.Match) -> str:
        key = match.group(1).strip()
        if key not in context:
            raise JumpServerApiError(DEFAULT_ERROR_MESSAGE)
        return str(context[key])
    return re.sub(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", repl, template_text)


def split_markdown_sections(template_text: str) -> List[Dict[str, str]]:
    lines = template_text.splitlines()
    sections = []
    current_title = "未命名章节"
    current_body: List[str] = []
    def flush() -> None:
        nonlocal current_body, current_title
        body = "\n".join(current_body).strip()
        if body:
            sections.append({"title": current_title, "body": body})
        current_body = []
    for line in lines:
        if re.match(r"^#{1,6}\s+", line):
            flush()
            current_title = re.sub(r"^#{1,6}\s+", "", line).strip()
        else:
            current_body.append(line)
    flush()
    return sections


def answer_natural_language_block(title: str, instruction: str, context: Dict[str, Any]) -> str:
    text = instruction.strip()
    if any(k in text for k in ["登录失败", "登录异常", "爆破风险", "登录记录"]):
        return summarize_login_logs(context["today_login_logs_raw"])
    if any(k in text for k in ["资产状态", "资产总数", "禁用资产", "异常资产"]):
        return summarize_assets(context["assets_raw"])
    if any(k in text for k in ["在线会话", "活跃会话", "当前会话"]):
        return summarize_active_sessions(context["active_sessions_raw"])
    if any(k in text for k in ["操作审计", "审计日志", "危险操作"]):
        return summarize_operate_logs(context["operate_logs_raw"])
    if any(k in text for k in ["风险", "安全风险", "风险统计"]):
        return summarize_security_risks(context["today_login_logs_raw"], context["active_sessions_raw"], context["operate_logs_raw"])
    return f"未匹配到明确的数据映射规则，以下为默认巡检摘要：\n\n{build_default_report(context)}"


def render_natural_language_template(template_text: str, context: Dict[str, Any]) -> str:
    sections = split_markdown_sections(template_text)
    if not sections:
        return build_default_report(context)
    output: List[str] = []
    first_nonempty_line = next((line for line in template_text.splitlines() if line.strip()), "")
    if first_nonempty_line and not first_nonempty_line.startswith("#"):
        output.append(first_nonempty_line)
        output.append("")
    for section in sections:
        output.append(f"## {section['title']}")
        output.append(answer_natural_language_block(section["title"], section["body"], context))
        output.append("")
    return "\n".join(output).strip() + "\n"


def build_risk_level(context: Dict[str, Any]) -> str:
    login_logs = context.get("today_login_logs_raw", [])
    assets = context.get("assets_raw", [])
    active_sessions = context.get("active_sessions_raw", [])
    operate_logs = context.get("operate_logs_raw", [])

    failure_count = 0
    failure_by_ip = Counter()
    for item in login_logs:
        if not is_success_status(extract_first(item, "status", "is_success", "success", default=False)):
            failure_count += 1
            failure_by_ip[humanize_value(extract_first(item, "ip", "remote_addr", "client_ip", default="未知IP"), default="未知IP")] += 1

    abnormal_assets = 0
    for item in assets:
        conn = str(humanize_value(extract_first(item, "connectivity", "status", "health_status", default=""))).lower()
        if any(k in conn for k in ["error", "fail", "invalid", "offline", "unknown"]):
            abnormal_assets += 1

    risky_sessions = 0
    for item in active_sessions:
        protocol = str(extract_first(item, "login_from", "protocol", "type", default="")).lower()
        if protocol in ("telnet",):
            risky_sessions += 1

    dangerous_actions = 0
    for item in operate_logs:
        action = str(extract_first(item, "action", "resource", "operate", "type", default="")).lower()
        if any(k in action for k in ["delete", "remove", "drop", "force", "destroy"]):
            dangerous_actions += 1

    if failure_count >= 20 or abnormal_assets >= 5 or risky_sessions > 0 or dangerous_actions > 0 or any(v >= 10 for v in failure_by_ip.values()):
        return "高"
    if failure_count >= 5 or abnormal_assets >= 1:
        return "中"
    return "低"


def build_executive_summary(context: Dict[str, Any]) -> str:
    assets = context.get("assets_raw", [])
    active_sessions = context.get("active_sessions_raw", [])
    login_logs = context.get("today_login_logs_raw", [])
    operate_logs = context.get("operate_logs_raw", [])

    abnormal_assets = 0
    for item in assets:
        conn = str(humanize_value(extract_first(item, "connectivity", "status", "health_status", default=""))).lower()
        if any(k in conn for k in ["error", "fail", "invalid", "offline", "unknown"]):
            abnormal_assets += 1

    failure_count = 0
    for item in login_logs:
        if not is_success_status(extract_first(item, "status", "is_success", "success", default=False)):
            failure_count += 1

    risk_level = build_risk_level(context)
    return "\n".join([
        f"- 巡检日期：{context['report_date']}",
        f"- 风险等级：{risk_level}",
        f"- 资产总数：{len(assets)}",
        f"- 活跃会话：{len(active_sessions)}",
        f"- 登录失败：{failure_count}",
        f"- 异常资产：{abnormal_assets}",
        f"- 操作审计：{'已获取' if operate_logs else '未获取/接口异常'}",
    ])


def build_key_findings(context: Dict[str, Any]) -> str:
    findings = []
    login_logs = context.get("today_login_logs_raw", [])
    assets = context.get("assets_raw", [])
    active_sessions = context.get("active_sessions_raw", [])
    operate_logs = context.get("operate_logs_raw", [])

    failure_by_ip = Counter()
    failure_by_user = Counter()
    for item in login_logs:
        if not is_success_status(extract_first(item, "status", "is_success", "success", default=False)):
            failure_by_ip[humanize_value(extract_first(item, "ip", "remote_addr", "client_ip", default="未知IP"), default="未知IP")] += 1
            failure_by_user[humanize_value(extract_first(item, "username", "user", default="未知用户"), default="未知用户")] += 1

    if failure_by_ip:
        ip, cnt = failure_by_ip.most_common(1)[0]
        findings.append(f"- 登录失败最集中来源 IP：{ip}（{cnt} 次）")
    if failure_by_user:
        user, cnt = failure_by_user.most_common(1)[0]
        findings.append(f"- 登录失败最高账号：{user}（{cnt} 次）")

    abnormal_assets = []
    for item in assets:
        conn = humanize_value(extract_first(item, "connectivity", "status", "health_status", default="-"))
        conn_l = conn.lower()
        if any(k in conn_l for k in ["error", "fail", "invalid", "offline", "unknown"]):
            abnormal_assets.append(f"{humanize_value(extract_first(item, 'name', 'address', default='未知资产'))}（{conn}）")
    if abnormal_assets:
        findings.append(f"- 资产异常/待核查：{', '.join(abnormal_assets[:5])}")

    if active_sessions:
        findings.append(f"- 当前存在 {len(active_sessions)} 个活跃会话，需关注敏感时段访问与来源 IP。")

    if not operate_logs:
        findings.append("- 操作审计接口当前未返回有效数据，审计链路待补查。")

    return "\n".join(findings) if findings else "- 本次巡检未发现需要重点升级处理的异常。"


def build_recommendations(context: Dict[str, Any]) -> str:
    items = []
    if "接口异常" in context.get("operate_logs", ""):
        items.append("- 修复 `/api/v1/audits/operate-logs/` 接口异常，补全操作审计数据。")
    if "疑似爆破来源 IP" in context.get("security_risk_summary", ""):
        items.append("- 对高频失败来源 IP 与账号做封禁/限速/验证码/告警联动。")
    if "异常资产" in context.get("asset_status", ""):
        items.append("- 复核连通性异常与 Unknown 状态资产，排查凭据、网络或采集任务问题。")
    if not items:
        items.append("- 当前建议保持日巡检与异常告警联动，持续观察。")
    return "\n".join(items)


def build_default_report(context: Dict[str, Any]) -> str:
    return (
        f"# JumpServer 巡检报告\n\n"
        f"**报告日期：** {context['report_date']}\n\n"
        f"## 一、管理摘要\n{build_executive_summary(context)}\n\n"
        f"## 二、关键发现\n{build_key_findings(context)}\n\n"
        f"## 三、登录情况\n{context['today_login_logs']}\n\n"
        f"## 四、资产状态\n{context['asset_status']}\n\n"
        f"## 五、活跃会话\n{context['active_sessions']}\n\n"
        f"## 六、操作审计\n{context['operate_logs']}\n\n"
        f"## 七、安全风险摘要\n{context['security_risk_summary']}\n\n"
        f"## 八、处置建议\n{build_recommendations(context)}\n"
    )


def generate_report(template_text: str, report_date: Optional[str] = None) -> str:
    report_date_str = parse_date(report_date).strftime("%Y-%m-%d")
    context = build_data_bundle(report_date_str)
    mode = detect_template_mode(template_text)
    if mode == "placeholder":
        return render_placeholder_template(template_text, context)
    return render_natural_language_template(template_text, context)


def send_message(content: str, open_id: Optional[str] = None, group_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "action": "send_message",
        "target_type": "open_id" if open_id else ("group_id" if group_id else "current_chat"),
        "target": open_id or group_id,
        "msg_type": "text",
        "content": content,
    }


def send_rich_text(markdown: str, title: str = "JumpServer 巡检报告", open_id: Optional[str] = None, group_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "action": "send_rich_text",
        "target_type": "open_id" if open_id else ("group_id" if group_id else "current_chat"),
        "target": open_id or group_id,
        "title": title,
        "markdown": markdown,
    }


def output_report(report_markdown: str, output_file: Path = DEFAULT_OUTPUT_FILE, print_stdout: bool = True) -> Path:
    ensure_parent_dir(output_file)
    output_file.write_text(report_markdown, encoding="utf-8")
    if print_stdout:
        print(report_markdown)
    return output_file


def load_state(state_file: Path = DEFAULT_STATE_FILE) -> Dict[str, Any]:
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(data: Dict[str, Any], state_file: Path = DEFAULT_STATE_FILE) -> None:
    ensure_parent_dir(state_file)
    state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def setup_daily_push(hour: int = 8, minute: int = 0, template: str = DEFAULT_TEMPLATE_NAME, template_file: Path = USER_TEMPLATE_FILE, open_id: Optional[str] = None, group_id: Optional[str] = None, output_file: Path = DEFAULT_OUTPUT_FILE) -> Dict[str, Any]:
    state = {
        "hour": hour,
        "minute": minute,
        "template": template,
        "template_file": str(template_file),
        "open_id": open_id,
        "group_id": group_id,
        "output_file": str(output_file),
        "updated_at": datetime.now().isoformat(),
    }
    save_state(state)
    return {"status": "scheduled", **state}


def seconds_until(hour: int, minute: int) -> int:
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return max(int((target - now).total_seconds()), 1)


def run_once(template_file: Path, open_id: Optional[str] = None, group_id: Optional[str] = None) -> Dict[str, Any]:
    template_text = load_template(template_file)
    report = generate_report(template_text, report_date=today_str())
    output_report(report, output_file=DEFAULT_OUTPUT_FILE, print_stdout=False)
    payload = send_rich_text(report, open_id=open_id, group_id=group_id)
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    return payload


def run_daemon(hour: int, minute: int, template_file: Path, open_id: Optional[str] = None, group_id: Optional[str] = None) -> None:
    print(json.dumps({"status": "daemon_started", "hour": hour, "minute": minute, "template_file": str(template_file), "open_id": open_id, "group_id": group_id}, ensure_ascii=False), flush=True)
    while True:
        wait_seconds = seconds_until(hour, minute)
        time.sleep(wait_seconds)
        try:
            run_once(template_file, open_id=open_id, group_id=group_id)
        except Exception:
            print(DEFAULT_ERROR_MESSAGE, flush=True)
            time.sleep(60)


def self_improve(instruction: str, skill_dir: Path = SKILL_DIR) -> Dict[str, Any]:
    note_file = ensure_parent_dir(skill_dir / "runtime" / "self_improve.todo.md")
    history = []
    if note_file.exists():
        history.append(note_file.read_text(encoding="utf-8"))
    history.append(f"## {datetime.now().isoformat()}\n- 指令：{instruction}\n- 状态：待修改 scripts/jms_inspection.py 并在下一个 turn 重新加载 Skill。\n")
    note_file.write_text("\n".join(history), encoding="utf-8")
    return {"status": "queued", "message": "已记录优化需求，请继续修改 scripts/jms_inspection.py。", "instruction": instruction, "note_file": str(note_file)}


def update_token_instruction() -> str:
    return "请在运行环境中重新设置 JUMPSERVER_TOKEN，或重新设置 JUMPSERVER_KEY_ID / JUMPSERVER_SECRET_ID，然后重启对应 Gateway / 容器 / 进程使环境变量生效。"


def cmd_generate(args: argparse.Namespace) -> int:
    try:
        template_file = resolve_template_file(args.template_file)
        template_text = load_template(template_file)
        report = generate_report(template_text, report_date=args.date)
        output_report(report, output_file=resolve_output_file(args.output_file), print_stdout=True)
        return 0
    except Exception:
        print(DEFAULT_ERROR_MESSAGE, file=sys.stderr)
        return 1


def cmd_save_template(args: argparse.Namespace) -> int:
    try:
        content = args.content
        if not content and args.content_file:
            content = Path(args.content_file).expanduser().read_text(encoding="utf-8")
        if not content:
            raise ValueError("模板内容为空")
        path = save_template(content, Path(args.template_file).expanduser().resolve() if args.template_file else USER_TEMPLATE_FILE)
        print(str(path))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


def cmd_setup_daily_push(args: argparse.Namespace) -> int:
    try:
        result = setup_daily_push(
            hour=args.hour,
            minute=args.minute,
            template=args.template,
            template_file=resolve_template_file(args.template_file),
            open_id=args.open_id,
            group_id=args.group_id,
            output_file=resolve_output_file(args.output_file),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("注意：真正的定时运行请使用 daemon 子命令并保持进程常驻。")
        return 0
    except Exception:
        print(DEFAULT_ERROR_MESSAGE, file=sys.stderr)
        return 1


def cmd_daemon(args: argparse.Namespace) -> int:
    try:
        run_daemon(hour=args.hour, minute=args.minute, template_file=resolve_template_file(args.template_file), open_id=args.open_id, group_id=args.group_id)
        return 0
    except Exception:
        print(DEFAULT_ERROR_MESSAGE, file=sys.stderr)
        return 1


def cmd_send_payload(args: argparse.Namespace) -> int:
    payload = send_rich_text(markdown=resolve_output_file(args.report_file).read_text(encoding="utf-8"), title=args.title, open_id=args.open_id, group_id=args.group_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_self_improve(args: argparse.Namespace) -> int:
    print(json.dumps(self_improve(args.instruction), ensure_ascii=False, indent=2))
    return 0


def cmd_update_token(args: argparse.Namespace) -> int:
    print(update_token_instruction())
    return 0


def cmd_self_test(args: argparse.Namespace) -> int:
    try:
        get_env_config()
        assets, assets_error = safe_fetch(get_assets, "资产接口不可用")
        sessions, sessions_error = safe_fetch(get_active_sessions, "活跃会话接口不可用")
        logins, logins_error = safe_fetch(lambda: get_login_logs(args.date or today_str()), "登录日志接口不可用")
        operates, operates_error = safe_fetch(get_operate_logs, "操作审计接口不可用")
        result = {
            "date": args.date or today_str(),
            "assets_count": len(assets),
            "active_sessions_count": len(sessions),
            "login_logs_count": len(logins),
            "operate_logs_count": len(operates),
            "assets_error": assets_error,
            "active_sessions_error": sessions_error,
            "login_logs_error": logins_error,
            "operate_logs_error": operates_error,
            "sample_asset": assets[0] if assets else None,
            "sample_session": sessions[0] if sessions else None,
            "sample_login": logins[0] if logins else None,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not any([assets_error, sessions_error, logins_error]) else 1
    except Exception:
        print(DEFAULT_ERROR_MESSAGE, file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JumpServer 巡检报告生成与定时推送工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p_generate = sub.add_parser("generate", help="生成巡检报告")
    p_generate.add_argument("--date", help="报告日期，格式 YYYY-MM-DD")
    p_generate.add_argument("--template-file", help="模板文件路径；留空时优先使用 runtime/template.md，否则使用内置 daily 模板")
    p_generate.add_argument("--output-file", help="输出 Markdown 文件路径；留空时写入 runtime/last_report.md")
    p_generate.set_defaults(func=cmd_generate)

    p_save = sub.add_parser("save-template", help="保存模板")
    p_save.add_argument("--content", help="模板原文")
    p_save.add_argument("--content-file", help="从文件读取模板原文")
    p_save.add_argument("--template-file", help="模板写入路径；留空时写入 runtime/template.md")
    p_save.set_defaults(func=cmd_save_template)

    p_setup = sub.add_parser("setup-daily-push", help="写入每日推送配置")
    p_setup.add_argument("--hour", type=int, default=8)
    p_setup.add_argument("--minute", type=int, default=0)
    p_setup.add_argument("--template", default=DEFAULT_TEMPLATE_NAME)
    p_setup.add_argument("--template-file", help="模板文件路径或内置别名 daily/executive")
    p_setup.add_argument("--open-id")
    p_setup.add_argument("--group-id")
    p_setup.add_argument("--output-file", help="输出 Markdown 文件路径；留空时写入 runtime/last_report.md")
    p_setup.set_defaults(func=cmd_setup_daily_push)

    p_daemon = sub.add_parser("daemon", help="启动每日推送守护进程")
    p_daemon.add_argument("--hour", type=int, default=8)
    p_daemon.add_argument("--minute", type=int, default=0)
    p_daemon.add_argument("--template-file", help="模板文件路径或内置别名 daily/executive")
    p_daemon.add_argument("--open-id")
    p_daemon.add_argument("--group-id")
    p_daemon.set_defaults(func=cmd_daemon)

    p_payload = sub.add_parser("send-payload", help="输出飞书发送载荷")
    p_payload.add_argument("--report-file", help="报告文件路径；留空时读取 runtime/last_report.md")
    p_payload.add_argument("--title", default="JumpServer 巡检报告")
    p_payload.add_argument("--open-id")
    p_payload.add_argument("--group-id")
    p_payload.set_defaults(func=cmd_send_payload)

    p_improve = sub.add_parser("self-improve", help="记录自优化需求")
    p_improve.add_argument("instruction")
    p_improve.set_defaults(func=cmd_self_improve)

    p_token = sub.add_parser("update-token", help="输出更新 Token 的操作提示")
    p_token.set_defaults(func=cmd_update_token)

    p_self_test = sub.add_parser("self-test", help="自测 JumpServer 接口连通性与关键字段")
    p_self_test.add_argument("--date", help="报告日期，格式 YYYY-MM-DD")
    p_self_test.set_defaults(func=cmd_self_test)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
