#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import base64
import hashlib
import hmac
import importlib
import json
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_ERROR_MESSAGE = "API 调用失败，请检查配置"
DEFAULT_TEMPLATE_NAME = "daily"
DEFAULT_REPORT_TITLE = "JumpServer 堡垒机巡检报告"
DEFAULT_REPORT_STYLE = "legacy"
DEFAULT_COMMAND_TIMEOUT = 20
DEFAULT_COMMAND_MAX_OUTPUT = 12000
DEFAULT_TOP_N = 10
DEFAULT_INSTALL_RETRIES = 3
DEFAULT_PIP_TIMEOUT = 120
DEFAULT_PLAYWRIGHT_DOWNLOAD_TIMEOUT_MS = 180000
DEFAULT_PLAYWRIGHT_CFT_DOWNLOAD_HOST = "https://storage.googleapis.com/chrome-for-testing-public"
DEFAULT_PLAYWRIGHT_CFT_CDN_HOST = "https://cdn.playwright.dev/chrome-for-testing-public"
ROOT_ORG_ID = "00000000-0000-0000-0000-000000000000"
ANSI_CSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
ANSI_OSC_RE = re.compile(r"\x1B\][^\x07]*(?:\x07|\x1B\\)")
PROBE_SECTION_BEGIN_RE = re.compile(r"^__JMS_BEGIN__\s+([A-Za-z0-9_.-]+)\s*$")
PROBE_SECTION_END_RE = re.compile(r"^__JMS_END__\s+([A-Za-z0-9_.-]+)\s*$")
DEFAULT_CONNECT_OPTIONS: Dict[str, Any] = {
    "charset": "default",
    "disableautohash": False,
    "token_reusable": False,
    "resolution": "1920x1080",
    "backspaceAsCtrlH": False,
    "appletConnectMethod": "web",
    "virtualappConnectMethod": "web",
    "reusable": False,
    "rdp_connection_speed": "auto",
}

SKILL_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = SKILL_DIR / "assets"
COMMANDS_DIR = ASSETS_DIR / "commands"
SQL_DIR = ASSETS_DIR / "sql" / "mysql" / "v4"
TEMPLATE_DIR = ASSETS_DIR / "templates"
RUNTIME_DIR = SKILL_DIR / "runtime"
PROFILE_DIR = RUNTIME_DIR / "profiles"
REPORT_DIR = RUNTIME_DIR / "reports"
EXAMPLE_ENV_FILE = SKILL_DIR / ".env.example"
THIRD_PARTY_DIR = SKILL_DIR / "third_party"
OFFICIAL_SRC_DIR = THIRD_PARTY_DIR / "jms-inspect-go"

BUILTIN_DAILY_TEMPLATE_FILE = TEMPLATE_DIR / "daily.md"
BUILTIN_EXECUTIVE_TEMPLATE_FILE = TEMPLATE_DIR / "executive.md"
USER_TEMPLATE_FILE = RUNTIME_DIR / "template.md"
DEFAULT_STATE_FILE = RUNTIME_DIR / "scheduler_state.json"
DEFAULT_OUTPUT_FILE = RUNTIME_DIR / "last_report.md"
DEFAULT_HTML_OUTPUT_FILE = RUNTIME_DIR / "last_report.html"
RUNTIME_VENV_DIR = RUNTIME_DIR / ".venv"
RUNTIME_BIN_DIR = RUNTIME_DIR / "bin"
RUNTIME_OFFICIAL_BINARY = RUNTIME_BIN_DIR / "jms_inspect"
PLAYWRIGHT_BROWSERS_DIR = RUNTIME_DIR / ".playwright-browsers"
FILLED_TEMPLATE_DIR = RUNTIME_DIR / "filled_templates"
LEGACY_COMMAND_FILE = COMMANDS_DIR / "legacy_system.txt"
DEFAULT_REMOTE_CONFIG_FILE = "/opt/jumpserver/config/config.txt"
MISSING_COMMAND_OUTPUT = "未采集到命令输出。"
OFFICIAL_BINARY_ASSET = ASSETS_DIR / "bin" / "linux_amd64" / "jms_inspect"
DEFAULT_LEGACY_PROVIDER = "official"
OFFICIAL_REMOTE_SYSTEM = "linux"
OFFICIAL_REMOTE_ARCHES = {"x86_64", "amd64"}

RUNTIME_PROFILE: Dict[str, Any] = {
    "name": "shell",
    "source": None,
    "values": {},
    "auth_config": None,
    "command_target_state": None,
}

OPTIONAL_DEPENDENCIES: Dict[str, Dict[str, Any]] = {
    "db": {
        "python": ["PyMySQL[rsa]"],
        "post_install": [],
        "system": [],
    },
    "exec": {
        "python": ["playwright"],
        "post_install": [],
        "system": [],
    },
    "docx": {
        "python": ["python-docx"],
        "post_install": [],
        "system": [],
    },
    "official": {
        "python": ["paramiko"],
        "post_install": [],
        "system": [],
    },
    "pdf": {
        "python": ["pypdf", "python-docx"],
        "post_install": [],
        "system": ["libreoffice"],
    },
}


def get_runtime_site_packages() -> List[Path]:
    candidates = sorted(RUNTIME_VENV_DIR.glob("lib/python*/site-packages"))
    if not candidates:
        candidates = sorted(RUNTIME_VENV_DIR.glob("Lib/site-packages"))
    return [path.resolve() for path in candidates if path.exists()]


def bootstrap_runtime_site_packages() -> None:
    for path in get_runtime_site_packages():
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


bootstrap_runtime_site_packages()


def apply_runtime_env_defaults() -> None:
    PLAYWRIGHT_BROWSERS_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PLAYWRIGHT_BROWSERS_DIR))
    os.environ.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    os.environ.setdefault("PIP_DEFAULT_TIMEOUT", str(DEFAULT_PIP_TIMEOUT))
    os.environ.setdefault("PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT", str(DEFAULT_PLAYWRIGHT_DOWNLOAD_TIMEOUT_MS))


def build_runtime_process_env(extra: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    apply_runtime_env_defaults()
    env = {str(key): str(value) for key, value in os.environ.items()}
    for key, value in (RUNTIME_PROFILE.get("values") or {}).items():
        if value is None:
            continue
        env[str(key)] = str(value)
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PLAYWRIGHT_BROWSERS_DIR))
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    env.setdefault("PIP_DEFAULT_TIMEOUT", str(DEFAULT_PIP_TIMEOUT))
    env.setdefault("PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT", str(DEFAULT_PLAYWRIGHT_DOWNLOAD_TIMEOUT_MS))
    if extra:
        for key, value in extra.items():
            if value is None:
                continue
            env[str(key)] = str(value)
    return env


def supports_playwright_cft_download_host() -> bool:
    system_name = platform.system().lower()
    machine = platform.machine().lower()
    if system_name == "darwin":
        return machine in {"arm64", "x86_64"}
    if system_name == "linux":
        return machine in {"x86_64", "amd64"}
    if system_name == "windows":
        return machine in {"x86_64", "amd64"}
    return False


def find_system_chromium_executable() -> Optional[str]:
    candidates: List[str] = []
    for binary in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        "msedge",
    ):
        path = shutil.which(binary)
        if path:
            candidates.append(path)
    candidates.extend([
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ])
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if Path(normalized).exists():
            return normalized
    return None


def get_playwright_download_host_candidates(env: Dict[str, str]) -> List[str]:
    explicit_hosts: List[str] = []
    for key in ("PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST", "PLAYWRIGHT_DOWNLOAD_HOST"):
        value = str(env.get(key) or "").strip().rstrip("/")
        if value and value not in explicit_hosts:
            explicit_hosts.append(value)
    if explicit_hosts:
        return explicit_hosts
    hosts: List[str] = []
    if supports_playwright_cft_download_host():
        hosts.extend([
            DEFAULT_PLAYWRIGHT_CFT_DOWNLOAD_HOST,
            DEFAULT_PLAYWRIGHT_CFT_CDN_HOST,
        ])
    hosts.append("")
    ordered: List[str] = []
    for host in hosts:
        if host in ordered:
            continue
        ordered.append(host)
    return ordered


def install_playwright_chromium_runtime(python_path: Path, install_env: Dict[str, str]) -> List[str]:
    system_browser = find_system_chromium_executable()
    if system_browser:
        return [f"reuse-system-chromium {system_browser}"]

    attempted_hosts: List[str] = []
    last_error: Optional[Exception] = None
    for host in get_playwright_download_host_candidates(install_env):
        env = dict(install_env)
        label = host or "playwright-default"
        if host:
            env["PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST"] = host
            env.pop("PLAYWRIGHT_DOWNLOAD_HOST", None)
        description = f"执行 `exec` 后置安装（Chromium 下载源：{label}）"
        try:
            run_subprocess(
                [str(python_path), "-m", "playwright", "install", "chromium"],
                description,
                retries=1,
                env=env,
            )
            return [f"python -m playwright install chromium @ {label}"]
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            attempted_hosts.append(label)

    attempted_text = ", ".join(attempted_hosts) if attempted_hosts else "无"
    raise JumpServerApiError(
        "执行 `exec` 后置安装失败，已尝试这些 Chromium 下载源："
        f"{attempted_text}。可优先安装系统 Chrome/Chromium，或在 profile 中设置 "
        "`PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST` / `HTTPS_PROXY` 后重试。"
    ) from last_error


def run_subprocess(command: List[str], description: str, retries: int = 1, env: Optional[Dict[str, str]] = None) -> None:
    attempts = max(int(retries or 1), 1)
    last_error: Optional[subprocess.CalledProcessError] = None
    for attempt in range(1, attempts + 1):
        try:
            subprocess.run(command, check=True, env=env)
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            if attempt >= attempts:
                command_text = " ".join(command)
                raise JumpServerApiError(
                    f"{description} 失败（已尝试 {attempts} 次，退出码 {exc.returncode}）：{command_text}"
                ) from exc
            time.sleep(min(2 ** (attempt - 1), 5))
    if last_error is not None:
        raise JumpServerApiError(str(last_error))


apply_runtime_env_defaults()


class JumpServerApiError(RuntimeError):
    pass


def ensure_parent_dir(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def slugify(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z._-]+", "-", value.strip())
    return text.strip("-") or "default"


def format_timestamp(value: Optional[datetime] = None, fmt: str = "%Y%m%d_%H%M%S") -> str:
    return (value or datetime.now()).strftime(fmt)


def parse_env_file(path: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(f"环境文件不存在：{path}")

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        data[key.strip()] = value
    return data


def resolve_profile_file(profile: str) -> Tuple[Path, str]:
    raw = profile.strip()
    direct_path = Path(raw).expanduser()
    if direct_path.is_absolute() or raw.startswith(".") or "/" in raw:
        return direct_path.resolve(), direct_path.stem

    candidates = [
        PROFILE_DIR / f"{raw}.env",
        SKILL_DIR / f".env.{raw}",
        SKILL_DIR / f"{raw}.env",
    ]
    if raw in ("default", "local"):
        candidates.append(SKILL_DIR / ".env.local")

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve(), raw

    raise FileNotFoundError(f"未找到 profile `{profile}` 对应的环境文件，默认查找 {PROFILE_DIR / f'{raw}.env'}")


def activate_profile(profile: Optional[str]) -> Tuple[str, Optional[str]]:
    runtime_values = dict(os.environ)
    profile_name = "shell"
    profile_source: Optional[str] = None

    if profile:
        profile_file, profile_name = resolve_profile_file(profile)
        runtime_values.update(parse_env_file(profile_file))
        profile_source = str(profile_file)
    else:
        local_env = SKILL_DIR / ".env.local"
        if local_env.exists():
            runtime_values.update(parse_env_file(local_env))
            profile_name = "local"
            profile_source = str(local_env)

    RUNTIME_PROFILE["name"] = profile_name
    RUNTIME_PROFILE["source"] = profile_source
    RUNTIME_PROFILE["values"] = runtime_values
    RUNTIME_PROFILE["auth_config"] = None
    RUNTIME_PROFILE["command_target_state"] = None
    return profile_name, profile_source


def get_runtime_env(key: str, default: str = "") -> str:
    value = RUNTIME_PROFILE.get("values", {}).get(key)
    if value is None:
        return default
    return str(value).strip()


def set_runtime_env(key: str, value: str) -> None:
    RUNTIME_PROFILE.setdefault("values", {})[key] = value


def update_env_file(path: Path, updates: Dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = dict(updates)
    output: List[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        replaced = False
        for key, value in list(pending.items()):
            if line.startswith(f"{key}=") or line.startswith(f"export {key}="):
                output.append(f"{key}={value}")
                pending.pop(key, None)
                replaced = True
                break
        if not replaced:
            output.append(raw_line)

    if pending:
        if output and output[-1].strip():
            output.append("")
        for key, value in pending.items():
            output.append(f"{key}={value}")

    ensure_parent_dir(path)
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def resolve_profile_write_file(profile: Optional[str] = None) -> Path:
    if profile:
        raw = profile.strip()
        direct_path = Path(raw).expanduser()
        if direct_path.is_absolute() or raw.startswith(".") or "/" in raw:
            return direct_path.resolve()
        try:
            resolved, _ = resolve_profile_file(profile)
            return resolved
        except FileNotFoundError:
            return (PROFILE_DIR / f"{raw}.env").resolve()
    profile_source = RUNTIME_PROFILE.get("source")
    if profile_source:
        return Path(str(profile_source)).resolve()
    raise JumpServerApiError("当前没有可写的 profile 文件，请显式传入 --profile。")


def ensure_profile_from_example(profile: str, overwrite: bool = False) -> Tuple[Path, bool]:
    path = resolve_profile_write_file(profile)
    if path.exists() and not overwrite:
        return path, False
    if not EXAMPLE_ENV_FILE.exists():
        raise FileNotFoundError(f"示例环境文件不存在：{EXAMPLE_ENV_FILE}")
    ensure_parent_dir(path)
    shutil.copyfile(EXAMPLE_ENV_FILE, path)
    return path, True


def bootstrap_required_profile_keys() -> List[str]:
    return [
        "JUMPSERVER_URL",
        "JUMPSERVER_USERNAME",
        "JUMPSERVER_PASSWORD",
        "JumpServer_IP",
        "JMS_OFFICIAL_SSH_USERNAME",
        "JMS_OFFICIAL_SSH_PASSWORD",
        "JMS_EXEC_ACCOUNT_NAME",
    ]


def detect_pending_profile_keys(path: Optional[Path]) -> List[str]:
    if not path or not path.exists():
        return bootstrap_required_profile_keys()

    values = parse_env_file(path)
    jumpserver_ip = str(values.get("JumpServer_IP") or values.get("JUMPSERVER_IP") or values.get("JMS_EXEC_ASSET_NAME") or "").strip()
    placeholder_values = {
        "JUMPSERVER_URL": {"", "https://jumpserver.example.com"},
        "JUMPSERVER_USERNAME": {"", "admin"},
        "JUMPSERVER_PASSWORD": {"", "change_me"},
        "JumpServer_IP": {"", "jumpserver-host"},
        "JMS_OFFICIAL_SSH_USERNAME": {"", "root"},
        "JMS_OFFICIAL_SSH_PASSWORD": {"", "change_me"},
        "JMS_EXEC_ACCOUNT_NAME": {"", "root"},
    }
    pending: List[str] = []
    for key in bootstrap_required_profile_keys():
        value = jumpserver_ip if key == "JumpServer_IP" else str(values.get(key, "")).strip()
        if value in placeholder_values.get(key, {""}):
            pending.append(key)
    return pending


def persist_runtime_settings(updates: Dict[str, str], profile: Optional[str] = None) -> Path:
    path = resolve_profile_write_file(profile)
    normalized = {str(key).strip(): str(value) for key, value in updates.items() if str(key).strip()}
    if not normalized:
        raise JumpServerApiError("没有可写入的配置项。")
    update_env_file(path, normalized)
    for key, value in normalized.items():
        set_runtime_env(key, value)
    return path


def parse_key_value_pairs(items: List[str]) -> Dict[str, str]:
    updates: Dict[str, str] = {}
    for item in items:
        text = str(item or "").strip()
        if not text or "=" not in text:
            raise JumpServerApiError(f"配置项格式错误：{item}，应为 KEY=VALUE")
        key, value = text.split("=", 1)
        key = key.strip()
        if not key:
            raise JumpServerApiError(f"配置项格式错误：{item}，缺少 KEY")
        updates[key] = value
    return updates


def persist_access_key(key_id: str, secret_id: str) -> Optional[str]:
    profile_source = RUNTIME_PROFILE.get("source")
    if not profile_source:
        return "当前使用的是 shell 环境变量，已在本次进程内生效，但未写回 profile 文件。"

    path = Path(profile_source)
    update_env_file(path, {
        "JUMPSERVER_KEY_ID": key_id,
        "JUMPSERVER_SECRET_ID": secret_id,
    })
    return f"已自动写回 access key 到 {path}"


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


def resolve_output_file(
    output_file: Optional[str],
    report_format: str,
    profile_name: str,
    legacy: bool = False,
) -> Path:
    if output_file:
        return Path(output_file).expanduser().resolve()

    ext = "html" if report_format == "html" else "md"
    if legacy:
        return DEFAULT_HTML_OUTPUT_FILE if ext == "html" else DEFAULT_OUTPUT_FILE

    directory = REPORT_DIR / slugify(profile_name)
    filename = f"JumpServer巡检报告_{format_timestamp()}.{ext}"
    return directory / filename


def sync_latest_output(report_text: str, report_format: str) -> None:
    latest_path = DEFAULT_HTML_OUTPUT_FILE if report_format == "html" else DEFAULT_OUTPUT_FILE
    ensure_parent_dir(latest_path)
    latest_path.write_text(report_text, encoding="utf-8")


def extract_http_error_payload(exc: urllib.error.HTTPError) -> Dict[str, Any]:
    try:
        body = exc.read().decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return {}
    try:
        return json.loads(body)
    except Exception:  # noqa: BLE001
        return {"detail": body.strip()}


def extract_access_token(data: Dict[str, Any]) -> str:
    for key in ("token", "access", "access_token"):
        value = data.get(key)
        if value:
            return str(value).strip()
    return ""


def extract_access_key_fields(data: Dict[str, Any]) -> Tuple[str, str]:
    key_id = ""
    secret_id = ""
    for candidate in ("access_key", "key_id", "public_key", "id"):
        value = data.get(candidate)
        if value:
            key_id = str(value).strip()
            break
    for candidate in ("secret_key", "secret_id", "secret", "private_key"):
        value = data.get(candidate)
        if value:
            secret_id = str(value).strip()
            break
    return key_id, secret_id


def login_with_password(base_url: str, username: str, password: str, timeout: int = 15) -> str:
    url = f"{base_url}/api/v1/authentication/auth/"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {
        "username": username,
        "password": password,
    }
    try:
        data = http_request_json(url, headers=headers, method="POST", payload=payload, timeout=timeout)
    except urllib.error.HTTPError as exc:
        error_payload = extract_http_error_payload(exc)
        detail = humanize_value(error_payload.get("detail") or error_payload.get("msg"), default="")
        text = json.dumps(error_payload, ensure_ascii=False)
        if any(keyword in text.lower() for keyword in ("mfa", "otp", "captcha", "verify", "sso")):
            raise JumpServerApiError("当前环境不支持账号密码自举，请改用 KeyID/SecretID。") from exc
        raise JumpServerApiError(detail or "账号密码登录失败，请检查用户名、密码或登录策略。") from exc

    token = extract_access_token(data if isinstance(data, dict) else {})
    if not token:
        raise JumpServerApiError("账号密码登录未返回可用 token，请改用 KeyID/SecretID。")
    return token


def create_access_key_with_token(base_url: str, bearer_token: str, timeout: int = 15) -> Tuple[str, str]:
    url = f"{base_url}/api/v1/authentication/access-keys/"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
    }
    payload_candidates = [
        {},
        {"name": f"codex-{slugify(RUNTIME_PROFILE.get('name', 'profile'))}-{format_timestamp(fmt='%Y%m%d%H%M%S')}"},
        {"name": f"codex-{slugify(RUNTIME_PROFILE.get('name', 'profile'))}", "comment": "Created by jumpserver-inspection-report"},
    ]
    last_error: Optional[Exception] = None

    for payload in payload_candidates:
        try:
            data = http_request_json(url, headers=headers, method="POST", payload=payload, timeout=timeout)
            if isinstance(data, dict):
                key_id, secret_id = extract_access_key_fields(data)
                if key_id and secret_id:
                    return key_id, secret_id
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code in (400, 409, 422):
                continue
            error_payload = extract_http_error_payload(exc)
            detail = humanize_value(error_payload.get("detail") or error_payload.get("msg"), default="")
            raise JumpServerApiError(detail or "创建 access key 失败，请检查当前账号权限。") from exc
        except Exception as exc:  # noqa: BLE001
            last_error = exc

    raise JumpServerApiError("创建 access key 失败，接口未返回 KeyID/SecretID。") from last_error


def bootstrap_access_key(base_url: str, username: str, password: str) -> Dict[str, str]:
    bearer_token = login_with_password(base_url, username, password)
    key_id, secret_id = create_access_key_with_token(base_url, bearer_token)
    set_runtime_env("JUMPSERVER_KEY_ID", key_id)
    set_runtime_env("JUMPSERVER_SECRET_ID", secret_id)
    persist_message = persist_access_key(key_id, secret_id)
    return {
        "key_id": key_id,
        "secret_id": secret_id,
        "persist_message": persist_message or "",
    }


def bootstrap_auth_config(base_url: str, username: str, password: str) -> Dict[str, str]:
    bearer_token = login_with_password(base_url, username, password)
    try:
        key_id, secret_id = create_access_key_with_token(base_url, bearer_token)
    except JumpServerApiError as exc:
        set_runtime_env("JUMPSERVER_TOKEN", bearer_token)
        return {
            "token": bearer_token,
            "key_id": "",
            "secret_id": "",
            "auth_mode": "bearer",
            "auth_source": "JUMPSERVER_USERNAME/JUMPSERVER_PASSWORD",
            "persist_message": f"账号密码登录成功，但未创建 access key，已回退到 Bearer token：{exc}",
        }

    set_runtime_env("JUMPSERVER_KEY_ID", key_id)
    set_runtime_env("JUMPSERVER_SECRET_ID", secret_id)
    persist_message = persist_access_key(key_id, secret_id)
    return {
        "token": "",
        "key_id": key_id,
        "secret_id": secret_id,
        "auth_mode": "signature",
        "auth_source": "JUMPSERVER_USERNAME/JUMPSERVER_PASSWORD",
        "persist_message": persist_message or "",
    }


def get_env_config() -> Dict[str, str]:
    cached = RUNTIME_PROFILE.get("auth_config")
    if cached:
        return cached

    base_url = get_runtime_env("JUMPSERVER_URL")
    token = get_runtime_env("JUMPSERVER_TOKEN")
    key_id = get_runtime_env("JUMPSERVER_KEY_ID")
    secret_id = get_runtime_env("JUMPSERVER_SECRET_ID")
    username = get_runtime_env("JUMPSERVER_USERNAME")
    password = get_runtime_env("JUMPSERVER_PASSWORD")

    if not base_url:
        raise JumpServerApiError("缺少 JUMPSERVER_URL，请先补齐 profile 环境。")

    auth_source = ""
    persist_message = ""
    if token:
        auth_mode = "bearer"
        auth_source = "JUMPSERVER_TOKEN"
    elif key_id and secret_id:
        auth_mode = "signature"
        auth_source = "JUMPSERVER_KEY_ID/JUMPSERVER_SECRET_ID"
    elif username and password:
        bootstrap = bootstrap_auth_config(base_url.rstrip("/"), username, password)
        token = bootstrap["token"]
        key_id = bootstrap["key_id"]
        secret_id = bootstrap["secret_id"]
        auth_mode = bootstrap["auth_mode"]
        auth_source = bootstrap["auth_source"]
        persist_message = bootstrap.get("persist_message", "")
    else:
        raise JumpServerApiError(
            "请配置 JUMPSERVER_TOKEN，或 JUMPSERVER_KEY_ID/JUMPSERVER_SECRET_ID，或 JUMPSERVER_USERNAME/JUMPSERVER_PASSWORD。"
        )

    cfg = {
        "base_url": base_url.rstrip("/"),
        "token": token,
        "key_id": key_id,
        "secret_id": secret_id,
        "auth_mode": auth_mode,
        "auth_source": auth_source,
        "persist_message": persist_message,
        "org_id": get_runtime_env("JUMPSERVER_ORG"),
    }
    RUNTIME_PROFILE["auth_config"] = cfg
    return cfg


def is_placeholder_asset_name(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {
        "",
        "demo.jumpserver.org",
        "example.jumpserver.org",
        "your.jumpserver.host",
    }


def get_jumpserver_ip_value() -> str:
    for key in ("JumpServer_IP", "JUMPSERVER_IP", "JMS_EXEC_ASSET_NAME"):
        value = get_runtime_env(key)
        if value:
            return value
    return ""


def get_legacy_provider() -> str:
    provider = (get_runtime_env("JMS_LEGACY_PROVIDER", DEFAULT_LEGACY_PROVIDER) or DEFAULT_LEGACY_PROVIDER).strip().lower()
    if provider not in ("official", "python"):
        return DEFAULT_LEGACY_PROVIDER
    return provider


def resolve_official_binary_source() -> Path:
    configured = get_runtime_env("JMS_OFFICIAL_BINARY_PATH")
    path = Path(configured).expanduser().resolve() if configured else OFFICIAL_BINARY_ASSET.resolve()
    if not path.exists():
        raise JumpServerApiError(
            f"未找到 official 巡检二进制：{path}。请先执行 `python3 scripts/jms_inspection.py bootstrap --profile <profile>`。"
        )
    return path


def prepare_official_runtime_binary() -> Dict[str, Any]:
    source = resolve_official_binary_source()
    ensure_parent_dir(RUNTIME_OFFICIAL_BINARY)
    shutil.copyfile(source, RUNTIME_OFFICIAL_BINARY)
    try:
        RUNTIME_OFFICIAL_BINARY.chmod(0o755)
    except Exception:  # noqa: BLE001
        pass
    return {
        "source": str(source),
        "runtime_path": str(RUNTIME_OFFICIAL_BINARY),
        "local_platform": f"{platform.system().lower()}/{platform.machine().lower()}",
    }


def get_official_ssh_config() -> Dict[str, Any]:
    host = get_jumpserver_ip_value()
    port = get_runtime_env("JMS_OFFICIAL_SSH_PORT", "22") or "22"
    username = get_runtime_env("JMS_OFFICIAL_SSH_USERNAME")
    password = get_runtime_env("JMS_OFFICIAL_SSH_PASSWORD")
    privilege_type = get_runtime_env("JMS_OFFICIAL_PRIVILEGE_TYPE")
    privilege_password = get_runtime_env("JMS_OFFICIAL_PRIVILEGE_PASSWORD")
    remote_config_path = get_runtime_env("JMS_OFFICIAL_REMOTE_CONFIG_PATH", DEFAULT_REMOTE_CONFIG_FILE) or DEFAULT_REMOTE_CONFIG_FILE

    missing: List[str] = []
    if not host:
        missing.append("JumpServer_IP")
    if not username:
        missing.append("JMS_OFFICIAL_SSH_USERNAME")
    if not password:
        missing.append("JMS_OFFICIAL_SSH_PASSWORD")
    if missing:
        raise JumpServerApiError(
            "当前 legacy 正式巡检已切到 official 引擎，请先补齐配置："
            + ", ".join(missing)
        )

    try:
        port_value = int(str(port).strip())
    except ValueError as exc:
        raise JumpServerApiError(f"`JMS_OFFICIAL_SSH_PORT={port}` 不是有效端口。") from exc

    if privilege_type not in ("", "su -", "sudo"):
        raise JumpServerApiError("`JMS_OFFICIAL_PRIVILEGE_TYPE` 仅支持空值、`su -` 或 `sudo`。")
    if privilege_type == "su -" and not privilege_password:
        raise JumpServerApiError("当前配置了 `JMS_OFFICIAL_PRIVILEGE_TYPE=su -`，请同时补齐 `JMS_OFFICIAL_PRIVILEGE_PASSWORD`。")

    return {
        "host": host,
        "port": port_value,
        "username": username,
        "password": password,
        "privilege_type": privilege_type,
        "privilege_password": privilege_password,
        "remote_config_path": remote_config_path,
    }


def yaml_quote(value: Any) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


def render_official_machine_config(profile_name: str, ssh_config: Dict[str, Any]) -> str:
    lines = [
        "servers:",
        f"  - name: {yaml_quote(profile_name or ssh_config['host'])}",
        "    type: JumpServer",
        f"    host: {yaml_quote(ssh_config['host'])}",
        f"    port: {ssh_config['port']}",
        f"    username: {yaml_quote(ssh_config['username'])}",
        f"    password: {yaml_quote(ssh_config['password'])}",
        '    ssh_key_path: ""',
        f"    privilege_type: {yaml_quote(ssh_config['privilege_type'])}",
        f"    privilege_password: {yaml_quote(ssh_config['privilege_password'])}",
    ]
    return "\n".join(lines) + "\n"


def resolve_service_host_info() -> Dict[str, str]:
    cfg = get_env_config()
    parsed = urllib.parse.urlparse(cfg["base_url"])
    hostname = str(parsed.hostname or "").strip()
    if not hostname:
        return {"hostname": "", "service_ip": "", "port": str(parsed.port or "")}
    service_ip = ""
    try:
        info = socket.getaddrinfo(hostname, parsed.port or 443, family=socket.AF_INET, type=socket.SOCK_STREAM)
        if info:
            service_ip = str(info[0][4][0])
    except Exception:  # noqa: BLE001
        service_ip = ""
    return {
        "hostname": hostname,
        "service_ip": service_ip,
        "port": str(parsed.port or ""),
    }


def infer_default_asset_name() -> str:
    explicit = get_jumpserver_ip_value()
    if explicit and not is_placeholder_asset_name(explicit):
        return explicit
    info = resolve_service_host_info()
    return info.get("service_ip") or info.get("hostname") or ""


def infer_default_account_name() -> str:
    return get_runtime_env("JMS_EXEC_ACCOUNT_NAME", "root") or "root"


def resolve_org_header_value(org_id: Optional[str], include_default_org: bool = True) -> str:
    if org_id is not None:
        return str(org_id).strip()
    if include_default_org:
        return str(get_env_config().get("org_id") or "").strip()
    return ""


def request_jumpserver_json(
    endpoint: str,
    method: str = "GET",
    params: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = 15,
    org_id: Optional[str] = None,
    include_default_org: bool = True,
) -> Any:
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
        if payload is not None:
            headers["Content-Type"] = "application/json"
    else:
        headers = build_signature_headers(endpoint, params, cfg["key_id"], cfg["secret_id"], method=method)
        if payload is not None:
            headers["Content-Type"] = "application/json"

    resolved_org_id = resolve_org_header_value(org_id, include_default_org=include_default_org)
    if resolved_org_id:
        headers["X-JMS-ORG"] = resolved_org_id

    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            return http_request_json(url, headers=headers, method=method, payload=payload, timeout=timeout)
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in (429, 500, 502, 503, 504):
                break
            time.sleep(min(2 ** attempt, 5))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(min(2 ** attempt, 5))
    raise JumpServerApiError(DEFAULT_ERROR_MESSAGE) from last_error


def fetch_jumpserver_data(
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 15,
    org_id: Optional[str] = None,
    include_default_org: bool = True,
) -> List[Dict[str, Any]]:
    payload = request_jumpserver_json(
        endpoint,
        method="GET",
        params=params,
        timeout=timeout,
        org_id=org_id,
        include_default_org=include_default_org,
    )
    return normalize_response_data(payload)


def fetch_jumpserver_data_paged(
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 15,
    org_id: Optional[str] = None,
    include_default_org: bool = True,
    page_size: int = 500,
    max_pages: int = 20,
) -> List[Dict[str, Any]]:
    base_params = dict(params or {})
    results: List[Dict[str, Any]] = []
    offset = 0
    seen_ids = set()

    for _ in range(max_pages):
        page_params = dict(base_params)
        page_params.setdefault("limit", page_size)
        page_params["offset"] = offset
        payload = request_jumpserver_json(
            endpoint,
            method="GET",
            params=page_params,
            timeout=timeout,
            org_id=org_id,
            include_default_org=include_default_org,
        )
        rows = normalize_response_data(payload)
        if not rows:
            break
        added = 0
        for row in rows:
            row_id = str(row.get("id") or "")
            if row_id and row_id in seen_ids:
                continue
            if row_id:
                seen_ids.add(row_id)
            results.append(row)
            added += 1
        if added == 0 or len(rows) < int(page_params["limit"]):
            break
        offset += len(rows)
    return results


def list_organizations() -> List[Dict[str, str]]:
    orgs = fetch_jumpserver_data(
        "/api/v1/orgs/orgs/",
        params={"limit": 1000},
        include_default_org=False,
    )
    rows: List[Dict[str, str]] = []
    for item in orgs:
        org_id = str(item.get("id") or "").strip()
        name = humanize_value(item.get("name"), default="")
        if not org_id or not name:
            continue
        if org_id == ROOT_ORG_ID or name.lower() == "root":
            continue
        rows.append({"id": org_id, "name": name})
    rows.sort(key=lambda item: item["name"])
    return rows


def resolve_default_org_scope(org_name: str) -> Optional[List[Dict[str, str]]]:
    needle = org_name.strip().lower()
    if needle not in ("default", "root"):
        return None
    orgs = fetch_jumpserver_data(
        "/api/v1/orgs/orgs/",
        params={"limit": 1000},
        include_default_org=False,
    )
    matches = []
    for item in orgs:
        name = humanize_value(item.get("name"), default="")
        org_id = str(item.get("id") or "").strip()
        if not name or not org_id:
            continue
        if name.strip().lower() == needle:
            matches.append({"id": org_id, "name": name})
    if len(matches) == 1:
        return matches
    return None


def resolve_org_scopes(org_name: Optional[str] = None, all_orgs: bool = False) -> List[Dict[str, str]]:
    if all_orgs:
        return list_organizations()
    if org_name:
        default_scope = resolve_default_org_scope(org_name)
        if default_scope:
            return default_scope
        needle = org_name.strip().lower()
        candidates = list_organizations()
        exact = [item for item in candidates if item["name"].strip().lower() == needle]
        if len(exact) == 1:
            return exact
        if len(exact) > 1:
            names = "，".join(item["name"] for item in exact[:10])
            raise JumpServerApiError(f"组织名称 `{org_name}` 命中多个组织，请改成更精确名称。候选：{names}")

        fuzzy = [item for item in candidates if needle in item["name"].strip().lower()]
        if len(fuzzy) == 1:
            return fuzzy
        if fuzzy:
            names = "，".join(item["name"] for item in fuzzy[:10])
            raise JumpServerApiError(f"组织名称 `{org_name}` 命中多个组织，请改成更精确名称。候选：{names}")
        raise JumpServerApiError(f"未找到组织 `{org_name}`。")

    env_org_id = get_runtime_env("JUMPSERVER_ORG")
    env_org_name = get_runtime_env("JMS_DEFAULT_ORG_NAME", env_org_id)
    if env_org_id:
        return [{"id": env_org_id, "name": env_org_name or env_org_id}]
    return []


def scope_label(org_scopes: List[Dict[str, str]]) -> str:
    if not org_scopes:
        return "当前默认组织"
    if len(org_scopes) == 1:
        return org_scopes[0]["name"]
    return "全部组织"


def get_command_execution_error(targets: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
    resolved_targets = targets
    if resolved_targets is None:
        state = get_command_target_state()
        if state.get("error"):
            return str(state["error"])
        resolved_targets = list(state.get("targets") or [])
    if not resolved_targets:
        return None
    try:
        get_env_config()
        ensure_command_runtime_ready()
        return None
    except JumpServerApiError as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001
        return str(exc)


def normalize_response_data(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("results", "data", "items", "rows"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [data]
    return []


def build_signature_headers(
    endpoint: str,
    params: Optional[Dict[str, Any]],
    key_id: str,
    secret_id: str,
    method: str = "GET",
) -> Dict[str, str]:
    accept = "application/json"
    date = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
    query = urllib.parse.urlencode(params or {}, doseq=True)
    path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    if query:
        path = f"{path}?{query}"
    signing_text = f"(request-target): {method.lower()} {path}\naccept: {accept}\ndate: {date}"
    signature = base64.b64encode(
        hmac.new(secret_id.encode(), signing_text.encode(), hashlib.sha256).digest()
    ).decode()
    return {
        "Accept": accept,
        "Date": date,
        "Authorization": (
            f'Signature keyId="{key_id}",algorithm="hmac-sha256",'
            f'headers="(request-target) accept date",signature="{signature}"'
        ),
    }


def http_request_json(
    url: str,
    headers: Dict[str, str],
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = 15,
) -> Any:
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, headers=headers, data=body, method=method.upper())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "ignore")
        return json.loads(body)


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
        return ", ".join(humanize_value(item, default=default) for item in value)
    return str(value)


def humanize_bool(value: Any) -> str:
    text = str(value).strip().lower()
    if value is True or text in ("true", "1", "yes", "enabled", "active", "valid"):
        return "是"
    if value is False or text in ("false", "0", "no", "disabled", "inactive", "invalid"):
        return "否"
    return humanize_value(value)


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


def parse_timestamp_value(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text or text in ("-", "None"):
        return None
    normalized = text.replace("Z", "+00:00")
    if re.match(r".*[+-]\d{2}:\d{2}$", normalized):
        try:
            return datetime.fromisoformat(normalized).replace(tzinfo=None)
        except ValueError:
            pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    return None


def extract_item_datetime(item: Dict[str, Any]) -> Optional[datetime]:
    for key in ("datetime", "date_start", "created_at", "timestamp", "time", "date_created"):
        result = parse_timestamp_value(item.get(key))
        if result:
            return result
    return None


def filter_records_by_date(records: List[Dict[str, Any]], date_from: str, date_to: str) -> List[Dict[str, Any]]:
    start = parse_date(date_from).date()
    end = parse_date(date_to).date()
    filtered: List[Dict[str, Any]] = []
    for item in records:
        item_time = extract_item_datetime(item)
        if not item_time:
            filtered.append(item)
            continue
        if start <= item_time.date() <= end:
            filtered.append(item)
    return filtered


def range_days(date_from: str, date_to: str) -> int:
    start = parse_date(date_from).date()
    end = parse_date(date_to).date()
    earliest = min(start, end)
    today = datetime.now().date()
    return max((today - earliest).days + 1, 1)


def parse_bool_env(key: str, default: bool = False) -> bool:
    value = get_runtime_env(key)
    if not value:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on", "enabled")


def parse_int_env(key: str, default: int) -> int:
    value = get_runtime_env(key)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def load_json_value(raw: str, default: Any) -> Any:
    text = raw.strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def normalize_command_list(commands: Any) -> List[str]:
    if commands is None:
        return []
    if isinstance(commands, list):
        items = [str(item).strip() for item in commands]
        return [item for item in items if item]
    text = str(commands).replace("\r\n", "\n").strip()
    if not text:
        return []
    separator = ";;" if ";;" in text else "\n"
    return [item.strip() for item in text.split(separator) if item.strip()]


def load_command_file(path_value: str) -> List[str]:
    if not path_value:
        return []
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = (SKILL_DIR / path).resolve()
    if not path.exists():
        return []
    return normalize_command_list(path.read_text(encoding="utf-8"))


def load_labeled_command_specs(path: Path = LEGACY_COMMAND_FILE) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"命令模板不存在：{path}")
    rows: List[Dict[str, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "::" not in line:
            continue
        label, command = line.split("::", 1)
        label = label.strip()
        command = command.strip()
        if label and command:
            rows.append({"label": label, "command": command})
    if not rows:
        raise JumpServerApiError(f"命令模板为空：{path}")
    return rows


def parse_key_value_text(text: str) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip("'\"")
    return data


def parse_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def at_day_start(value: str) -> str:
    return f"{parse_date(value).strftime('%Y-%m-%d')} 00:00:00"


def next_day_start(value: str) -> str:
    return (parse_date(value) + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")


def days_before_start(value: str, days: int) -> str:
    return (parse_date(value) - timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00:00")


def load_sql_template(name: str) -> str:
    path = SQL_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"SQL 模板不存在：{path}")
    return path.read_text(encoding="utf-8")


def render_sql_template(name: str, org_id: Optional[str] = None) -> str:
    sql = load_sql_template(name)
    replacements = {
        "/*ORG_FILTER*/": "AND org_id = %(org_id)s" if org_id else "",
        "/*ORG_FILTER_ALL*/": "AND org_id = %(org_id)s" if org_id else "",
        "/*ORG_FILTER_LOGIN*/": "",
        "/*ORG_FILTER_LOGIN_ALL*/": "",
        "/*ORG_FILTER_FTP*/": "AND org_id = %(org_id)s" if org_id else "",
        "/*ORG_FILTER_CMD*/": "AND org_id = %(org_id)s" if org_id else "",
        "/*ORG_FILTER_TICKET*/": "AND org_id = %(org_id)s" if org_id else "",
    }
    for marker, value in replacements.items():
        sql = sql.replace(marker, value)
    return sql


def normalize_name_key(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def lower_text(value: Any) -> str:
    return str(value or "").strip().lower()


def asset_platform_type(item: Dict[str, Any]) -> str:
    platform = item.get("platform") if isinstance(item.get("platform"), dict) else {}
    return lower_text(platform.get("type") or item.get("type"))


def asset_category_value(item: Dict[str, Any]) -> str:
    category = item.get("category") if isinstance(item.get("category"), dict) else {}
    return lower_text(category.get("value"))


def asset_connectivity_value(item: Dict[str, Any]) -> str:
    connectivity = item.get("connectivity")
    if isinstance(connectivity, dict):
        return lower_text(connectivity.get("value") or connectivity.get("label"))
    return lower_text(connectivity)


def asset_lookup_values(item: Dict[str, Any]) -> List[str]:
    values = [
        humanize_value(item.get("name"), default=""),
        humanize_value(item.get("address"), default=""),
        humanize_value(item.get("hostname"), default=""),
        humanize_value(item.get("ip"), default=""),
    ]
    return [str(value).strip() for value in values if str(value).strip()]


def extract_account_asset_links(item: Dict[str, Any]) -> List[str]:
    linked_values: List[str] = []
    raw_asset = item.get("asset")
    if isinstance(raw_asset, dict):
        linked_values.extend([
            str(raw_asset.get("id") or "").strip(),
            str(raw_asset.get("name") or "").strip(),
            str(raw_asset.get("address") or "").strip(),
        ])
    elif raw_asset not in (None, ""):
        linked_values.append(str(raw_asset).strip())

    asset_info = item.get("asset_info") if isinstance(item.get("asset_info"), dict) else {}
    linked_values.extend([
        str(item.get("asset_id") or "").strip(),
        str(asset_info.get("id") or "").strip(),
        str(asset_info.get("name") or "").strip(),
        str(asset_info.get("address") or "").strip(),
    ])
    return [value for value in linked_values if value]


def get_service_host_hint_tokens() -> List[str]:
    info = resolve_service_host_info()
    hostname = lower_text(info.get("hostname"))
    if not hostname:
        return []
    parts = re.split(r"[^0-9a-z]+", hostname)
    blacklist = {"com", "cn", "net", "org", "local", "jumpserver", "www"}
    return [item for item in parts if len(item) >= 3 and item not in blacklist]


def account_exists_for_asset(account_name: str, asset_id: str, org_id: Optional[str] = None) -> bool:
    try:
        matches = find_matching_accounts(account_name, asset_id=asset_id, org_id=org_id)
    except Exception:  # noqa: BLE001
        return False
    return bool(matches)


def score_asset_candidate(
    item: Dict[str, Any],
    asset_name: str,
    account_name: str = "",
    org_id: Optional[str] = None,
    prefer_host: bool = False,
) -> Tuple[int, int, int, int, int, str]:
    needle = lower_text(asset_name)
    lookup_values = asset_lookup_values(item)
    name_value = lower_text(item.get("name"))
    address_value = lower_text(item.get("address"))
    platform_type = asset_platform_type(item)
    category_value = asset_category_value(item)
    connectivity_value = asset_connectivity_value(item)
    service_hints = get_service_host_hint_tokens()

    exact_name_score = 1 if name_value == needle else 0
    exact_address_score = 1 if address_value == needle else 0
    host_score = 1 if prefer_host and (category_value == "host" or platform_type == "linux") else 0
    account_score = 1 if account_name and account_exists_for_asset(account_name, str(item.get("id") or "").strip(), org_id=org_id) else 0
    connectivity_score = 1 if connectivity_value in ("ok", "success", "successful") else 0
    hint_score = 0
    haystack = " ".join(lower_text(value) for value in lookup_values)
    for hint in service_hints:
        if hint in haystack:
            hint_score += 1
    return (
        exact_name_score,
        exact_address_score,
        host_score,
        account_score,
        connectivity_score + hint_score,
        lower_text(item.get("name")),
    )


def choose_best_asset_match(
    asset_name: str,
    matches: List[Dict[str, Any]],
    account_name: str = "",
    org_id: Optional[str] = None,
    prefer_host: bool = False,
) -> Optional[Dict[str, Any]]:
    if len(matches) <= 1:
        return matches[0] if matches else None
    scored = [(score_asset_candidate(item, asset_name, account_name=account_name, org_id=org_id, prefer_host=prefer_host), item) for item in matches]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if len(scored) == 1 or scored[0][0] > scored[1][0]:
        return scored[0][1]
    return None


def summarize_port_list(text: str) -> str:
    ports = [item.strip() for item in str(text or "").split(",") if item.strip()]
    if not ports:
        return "-"
    return ", ".join(ports[:20])


def format_seconds(seconds: Any) -> str:
    try:
        total = max(int(float(seconds)), 0)
    except (TypeError, ValueError):
        return "-"
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def find_matching_assets(asset_name: str, org_id: Optional[str] = None) -> List[Dict[str, Any]]:
    assets = fetch_jumpserver_data("/api/v1/assets/assets/", params={"limit": 1000}, org_id=org_id)
    matches = []
    needle = asset_name.strip()
    for item in assets:
        candidates = asset_lookup_values(item)
        if needle in candidates:
            matches.append(item)
    return matches


def resolve_exact_asset_id(
    asset_name: str,
    org_id: Optional[str] = None,
    account_name: str = "",
    prefer_host: bool = False,
) -> Tuple[str, str]:
    matches = find_matching_assets(asset_name, org_id=org_id)
    if not matches:
        raise JumpServerApiError(f"`JumpServer_IP={asset_name}` 未找到匹配资产。")
    if len(matches) > 1:
        picked = choose_best_asset_match(asset_name, matches, account_name=account_name, org_id=org_id, prefer_host=prefer_host)
        if picked is not None:
            return str(picked.get("id", "")).strip(), humanize_value(picked.get("name"), default=asset_name)
        names = "，".join(
            f"{humanize_value(item.get('name'), default='-')}[{humanize_value(item.get('address'), default='-')}]"
            for item in matches[:5]
        )
        raise JumpServerApiError(f"`JumpServer_IP={asset_name}` 命中多台资产，请改成更精确名称。候选：{names}")
    asset = matches[0]
    return str(asset.get("id", "")).strip(), humanize_value(asset.get("name"), default=asset_name)


def resolve_exact_asset_row(
    asset_name: str,
    org_id: Optional[str] = None,
    account_name: str = "",
    prefer_host: bool = False,
) -> Dict[str, Any]:
    matches = find_matching_assets(asset_name, org_id=org_id)
    if not matches:
        raise JumpServerApiError(f"`asset_name={asset_name}` 未找到匹配资产。")
    if len(matches) > 1:
        picked = choose_best_asset_match(asset_name, matches, account_name=account_name, org_id=org_id, prefer_host=prefer_host)
        if picked is not None:
            return picked
        names = "，".join(
            f"{humanize_value(item.get('name'), default='-')}[{humanize_value(item.get('address'), default='-')}]"
            for item in matches[:5]
        )
        raise JumpServerApiError(f"`asset_name={asset_name}` 命中多台资产，请改成更精确名称。候选：{names}")
    return matches[0]


def get_accounts(org_id: Optional[str] = None, asset_id: Optional[str] = None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {}
    if asset_id:
        params["asset"] = asset_id
    return fetch_jumpserver_data_paged("/api/v1/accounts/accounts/", params=params, org_id=org_id)


def find_matching_accounts(account_name: str, asset_id: Optional[str] = None, org_id: Optional[str] = None) -> List[Dict[str, Any]]:
    accounts = get_accounts(org_id=org_id, asset_id=asset_id)
    matches = []
    needle = account_name.strip()
    for item in accounts:
        candidates = [
            humanize_value(item.get("name"), default=""),
            humanize_value(item.get("username"), default=""),
        ]
        if needle not in candidates:
            continue
        if asset_id:
            linked_values = extract_account_asset_links(item)
            if linked_values and asset_id not in linked_values:
                continue
        matches.append(item)
    return matches


def resolve_exact_account_id(account_name: str, asset_id: Optional[str] = None, org_id: Optional[str] = None) -> Tuple[str, str]:
    matches = find_matching_accounts(account_name, asset_id=asset_id, org_id=org_id)
    if not matches:
        raise JumpServerApiError(f"`JMS_EXEC_ACCOUNT_NAME={account_name}` 未找到匹配账号。")
    if len(matches) > 1:
        names = "，".join(humanize_value(item.get("name") or item.get("username"), default="-") for item in matches[:5])
        raise JumpServerApiError(f"`JMS_EXEC_ACCOUNT_NAME={account_name}` 命中多个账号，请改成更精确名称。候选：{names}")
    account = matches[0]
    return str(account.get("id", "")).strip(), humanize_value(account.get("name") or account.get("username"), default=account_name)


def resolve_exact_account_row(account_name: str, asset_id: Optional[str] = None, org_id: Optional[str] = None) -> Dict[str, Any]:
    matches = find_matching_accounts(account_name, asset_id=asset_id, org_id=org_id)
    if not matches:
        raise JumpServerApiError(f"`account_name={account_name}` 未找到匹配账号。")
    if len(matches) > 1:
        names = "，".join(humanize_value(item.get("name") or item.get("username"), default="-") for item in matches[:5])
        raise JumpServerApiError(f"`account_name={account_name}` 命中多个账号，请改成更精确名称。候选：{names}")
    return matches[0]


def build_command_target_state() -> Dict[str, Any]:
    if not parse_bool_env("JMS_EXEC_ENABLED", True):
        return {"targets": [], "error": None, "resolution_mode": "disabled"}

    raw_targets = get_runtime_env("JMS_EXEC_TARGETS")
    global_commands = normalize_command_list(get_runtime_env("JMS_EXEC_COMMANDS"))
    global_commands.extend(load_command_file(get_runtime_env("JMS_EXEC_COMMAND_FILE")))
    if not global_commands:
        global_commands = ["df -Th"]

    raw_options = load_json_value(get_runtime_env("JMS_EXEC_CONNECT_OPTIONS"), {})
    default_options = dict(DEFAULT_CONNECT_OPTIONS)
    if isinstance(raw_options, dict):
        default_options.update(raw_options)

    shared = {
        "protocol": get_runtime_env("JMS_EXEC_PROTOCOL", "ssh") or "ssh",
        "input_username": get_runtime_env("JMS_EXEC_USERNAME", "root") or "root",
        "input_secret": get_runtime_env("JMS_EXEC_SECRET"),
        "connect_method": get_runtime_env("JMS_EXEC_CONNECT_METHOD", "web_cli") or "web_cli",
        "connect_options": default_options,
        "timeout": parse_int_env("JMS_EXEC_TIMEOUT", DEFAULT_COMMAND_TIMEOUT),
        "commands": global_commands,
        "asset_name": infer_default_asset_name(),
        "account_name": infer_default_account_name(),
    }

    targets: List[Dict[str, Any]] = []
    resolution_mode = "none"
    parsed_targets = load_json_value(raw_targets, None)
    if isinstance(parsed_targets, dict):
        parsed_targets = [parsed_targets]

    if isinstance(parsed_targets, list):
        resolution_mode = "targets_json"
        for index, item in enumerate(parsed_targets, start=1):
            if not isinstance(item, dict):
                continue
            target = dict(shared)
            target.update({
                "name": humanize_value(item.get("name") or item.get("asset_name") or f"节点{index}", default=f"节点{index}"),
                "asset": str(item.get("asset") or item.get("asset_id") or "").strip(),
                "account": str(item.get("account") or item.get("account_id") or "").strip(),
                "asset_name": str(item.get("asset_name") or item.get("asset_label") or target.get("asset_name") or "").strip(),
                "account_name": str(item.get("account_name") or item.get("account_label") or item.get("username") or target.get("account_name") or "").strip(),
            })
            target["protocol"] = str(item.get("protocol") or target["protocol"]).strip() or "ssh"
            target["input_username"] = str(item.get("input_username") or item.get("username") or target["input_username"]).strip() or "root"
            target["input_secret"] = str(item.get("input_secret") or target["input_secret"] or "").strip()
            target["connect_method"] = str(item.get("connect_method") or target["connect_method"]).strip() or "web_cli"
            item_options = item.get("connect_options")
            if isinstance(item_options, dict):
                merged_options = dict(default_options)
                merged_options.update(item_options)
                target["connect_options"] = merged_options
            item_commands = normalize_command_list(item.get("commands"))
            if item_commands:
                target["commands"] = item_commands
            targets.append(target)
    else:
        asset = get_runtime_env("JMS_EXEC_ASSET_ID") or get_runtime_env("JMS_EXEC_ASSET")
        account = get_runtime_env("JMS_EXEC_ACCOUNT_ID") or get_runtime_env("JMS_EXEC_ACCOUNT")
        target = dict(shared)
        target.update({
            "name": get_runtime_env("JMS_EXEC_TARGET_NAME"),
            "asset": asset,
            "account": account,
        })
        if asset and account:
            resolution_mode = "explicit_id"
            targets.append(target)
        elif target.get("asset_name") and target.get("account_name"):
            resolution_mode = "url_inferred" if is_placeholder_asset_name(get_jumpserver_ip_value()) else "name_match"
            targets.append(target)

    if not targets:
        return {"targets": [], "error": None, "resolution_mode": resolution_mode}

    resolved_targets: List[Dict[str, Any]] = []
    for target in targets:
        item = dict(target)
        if not item.get("asset"):
            asset_name = item.get("asset_name", "").strip()
            if not asset_name:
                raise JumpServerApiError("未配置 `JumpServer_IP`，无法自动解析命令巡检目标资产。")
            item["asset"], asset_display = resolve_exact_asset_id(
                asset_name,
                account_name=item.get("account_name", "").strip(),
                prefer_host=True,
            )
            if not item.get("name"):
                item["name"] = asset_display
        if not item.get("account"):
            account_name = item.get("account_name", "").strip()
            if not account_name:
                raise JumpServerApiError("未配置 `JMS_EXEC_ACCOUNT_NAME`，无法自动解析命令巡检目标账号。")
            item["account"], account_display = resolve_exact_account_id(account_name, asset_id=item.get("asset"))
            if item.get("input_username") in ("", "root") and account_display:
                item["input_username"] = account_display
        resolved_targets.append(item)

    return {
        "targets": resolved_targets,
        "error": None,
        "resolution_mode": resolution_mode or "none",
    }


def get_command_target_state() -> Dict[str, Any]:
    cached = RUNTIME_PROFILE.get("command_target_state")
    if cached is not None:
        return cached
    try:
        state = build_command_target_state()
    except Exception as exc:  # noqa: BLE001
        state = {
            "targets": [],
            "error": str(exc),
            "resolution_mode": "error",
        }
    RUNTIME_PROFILE["command_target_state"] = state
    return state


def get_command_targets() -> List[Dict[str, Any]]:
    return list(get_command_target_state().get("targets", []))


def build_legacy_system_target_state() -> Dict[str, Any]:
    raw_targets = get_runtime_env("JMS_SYSTEM_TARGETS")
    parsed_targets = load_json_value(raw_targets, None)
    if isinstance(parsed_targets, dict):
        parsed_targets = [parsed_targets]
    if not isinstance(parsed_targets, list) or not parsed_targets:
        inferred_asset_name = infer_default_asset_name()
        inferred_account_name = infer_default_account_name()
        if not inferred_asset_name or not inferred_account_name:
            return {"targets": [], "error": "未配置 JMS_SYSTEM_TARGETS，且无法从 JUMPSERVER_URL 自动推断巡检目标", "resolution_mode": "missing"}
        host_info = resolve_service_host_info()
        parsed_targets = [{
            "name": host_info.get("hostname") or inferred_asset_name or "JumpServer主机",
            "asset_name": inferred_asset_name,
            "account_name": inferred_account_name,
            "role": "core",
        }]
        inferred_resolution_mode = "url_inferred"
    else:
        inferred_resolution_mode = "system_targets"

    raw_options = load_json_value(get_runtime_env("JMS_EXEC_CONNECT_OPTIONS"), {})
    default_options = dict(DEFAULT_CONNECT_OPTIONS)
    if isinstance(raw_options, dict):
        default_options.update(raw_options)
    specs = load_labeled_command_specs()

    targets: List[Dict[str, Any]] = []
    for index, item in enumerate(parsed_targets, start=1):
        if not isinstance(item, dict):
            continue
        target_name = humanize_value(item.get("name") or item.get("asset_name") or f"JumpServer节点{index}", default=f"JumpServer节点{index}")
        asset_name = str(item.get("asset_name") or item.get("asset_label") or "").strip()
        account_name = str(item.get("account_name") or item.get("username") or "").strip()
        if not asset_name or not account_name:
            raise JumpServerApiError("JMS_SYSTEM_TARGETS 中每个目标都必须包含 asset_name 和 account_name。")

        asset_row = resolve_exact_asset_row(asset_name, account_name=account_name, prefer_host=True)
        account_row = resolve_exact_account_row(account_name, asset_id=str(asset_row.get("id") or "").strip())
        target = {
            "name": target_name,
            "role": humanize_value(item.get("role"), default="jumpserver"),
            "asset_name": asset_name,
            "account_name": account_name,
            "asset": str(asset_row.get("id") or "").strip(),
            "account": str(account_row.get("id") or "").strip(),
            "protocol": str(item.get("protocol") or get_runtime_env("JMS_EXEC_PROTOCOL", "ssh") or "ssh").strip() or "ssh",
            "input_username": str(item.get("input_username") or item.get("username") or humanize_value(account_row.get("name") or account_row.get("username"), default="root")).strip() or "root",
            "input_secret": str(item.get("input_secret") or get_runtime_env("JMS_EXEC_SECRET") or "").strip(),
            "connect_method": str(item.get("connect_method") or get_runtime_env("JMS_EXEC_CONNECT_METHOD", "web_cli") or "web_cli").strip() or "web_cli",
            "connect_options": dict(default_options),
            "timeout": int(item.get("timeout") or parse_int_env("JMS_EXEC_TIMEOUT", DEFAULT_COMMAND_TIMEOUT)),
            "commands": [spec["command"] for spec in specs],
            "legacy_specs": specs,
            "asset_row": asset_row,
            "account_row": account_row,
        }
        targets.append(target)

    return {"targets": targets, "error": None, "resolution_mode": inferred_resolution_mode}


def get_legacy_system_target_state() -> Dict[str, Any]:
    cache_key = "legacy_system_target_state"
    cached = RUNTIME_PROFILE.get(cache_key)
    if cached is not None:
        return cached
    try:
        state = build_legacy_system_target_state()
    except Exception as exc:  # noqa: BLE001
        state = {"targets": [], "error": str(exc), "resolution_mode": "error"}
    RUNTIME_PROFILE[cache_key] = state
    return state


def get_legacy_system_targets() -> List[Dict[str, Any]]:
    return list(get_legacy_system_target_state().get("targets", []))


def sanitize_target_preview(target: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(target, dict):
        return None
    redacted = dict(target)
    if "input_secret" in redacted and redacted["input_secret"]:
        redacted["input_secret"] = "***"
    if "legacy_specs" in redacted:
        redacted["legacy_specs"] = [{"label": item.get("label"), "command": item.get("command")} for item in redacted["legacy_specs"]]
    return redacted


def get_pymysql_module():
    try:
        return importlib.import_module("pymysql")
    except Exception as exc:  # noqa: BLE001
        try:
            maybe_auto_install("db")
            return importlib.import_module("pymysql")
        except Exception as install_exc:  # noqa: BLE001
            raise JumpServerApiError("数据库采集依赖 pymysql，请先安装可用环境后重试") from install_exc


def is_missing_pymysql_rsa_error(exc: Exception) -> bool:
    message = str(exc or "")
    hints = (
        "cryptography is required for sha256_password",
        "cryptography is required for sha256_password or caching_sha2_password",
        "caching_sha2_password",
        "sha256_password",
    )
    return any(hint in message for hint in hints)


def open_db_connection(db_config: Dict[str, Any]):
    pymysql = get_pymysql_module()
    connect_kwargs = {
        "host": db_config["host"],
        "port": int(db_config["port"]),
        "user": db_config["user"],
        "password": db_config["password"],
        "database": db_config["name"],
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "connect_timeout": 10,
        "read_timeout": 20,
        "write_timeout": 20,
    }
    try:
        return pymysql.connect(**connect_kwargs)
    except Exception as exc:  # noqa: BLE001
        if not is_missing_pymysql_rsa_error(exc):
            raise
        try:
            maybe_auto_install("db")
            pymysql = get_pymysql_module()
            connect_kwargs["cursorclass"] = pymysql.cursors.DictCursor
            return pymysql.connect(**connect_kwargs)
        except Exception as install_exc:  # noqa: BLE001
            raise JumpServerApiError(
                "数据库连接缺少 MySQL 8 鉴权依赖，请安装 `PyMySQL[rsa]` 或 `cryptography` 后重试。"
            ) from install_exc


def execute_sql_rows(
    db_config: Dict[str, Any],
    sql_name: str,
    params: Dict[str, Any],
    org_id: Optional[str] = None,
    connection: Any = None,
) -> List[Dict[str, Any]]:
    sql = render_sql_template(sql_name, org_id=org_id)
    query_params = dict(params)
    if org_id:
        query_params["org_id"] = org_id
    owned_connection = connection is None
    if owned_connection:
        connection = open_db_connection(db_config)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, query_params)
            rows = cursor.fetchall()
        return list(rows or [])
    finally:
        if owned_connection:
            connection.close()


def execute_sql_row(
    db_config: Dict[str, Any],
    sql_name: str,
    params: Dict[str, Any],
    org_id: Optional[str] = None,
    connection: Any = None,
) -> Dict[str, Any]:
    rows = execute_sql_rows(db_config, sql_name, params, org_id=org_id, connection=connection)
    return rows[0] if rows else {}


def resolve_local_db_overrides() -> Optional[Dict[str, Any]]:
    values = {
        "engine": get_runtime_env("JMS_DB_TYPE") or get_runtime_env("DB_ENGINE"),
        "host": get_runtime_env("JMS_DB_HOST") or get_runtime_env("DB_HOST"),
        "port": get_runtime_env("JMS_DB_PORT") or get_runtime_env("DB_PORT"),
        "user": get_runtime_env("JMS_DB_USERNAME") or get_runtime_env("JMS_DB_USER") or get_runtime_env("DB_USER"),
        "password": get_runtime_env("JMS_DB_PASSWORD") or get_runtime_env("DB_PASSWORD"),
        "name": get_runtime_env("JMS_DB_NAME") or get_runtime_env("DB_NAME"),
    }
    if all(values.values()):
        return values
    return None


def map_remote_db_config(values: Dict[str, str]) -> Optional[Dict[str, Any]]:
    mapped = {
        "engine": values.get("DB_ENGINE", ""),
        "host": values.get("DB_HOST", ""),
        "port": values.get("DB_PORT", ""),
        "user": values.get("DB_USER", ""),
        "password": values.get("DB_PASSWORD", ""),
        "name": values.get("DB_NAME", ""),
    }
    if all(mapped.values()):
        return mapped
    return None


def create_connection_token(target: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "asset": target["asset"],
        "account": target["account"],
        "protocol": target["protocol"],
        "input_username": target["input_username"],
        "input_secret": target.get("input_secret", ""),
        "connect_method": target["connect_method"],
        "connect_options": target["connect_options"],
    }
    result = request_jumpserver_json(
        "/api/v1/authentication/connection-token/",
        method="POST",
        payload=payload,
        timeout=target.get("timeout", DEFAULT_COMMAND_TIMEOUT),
        org_id=target.get("org_id"),
    )
    if not isinstance(result, dict) or not result.get("id"):
        raise JumpServerApiError("connection-token 接口未返回有效 token")
    return result


def runtime_python() -> Path:
    if os.name == "nt":
        return RUNTIME_VENV_DIR / "Scripts" / "python.exe"
    return RUNTIME_VENV_DIR / "bin" / "python3"


def runtime_pip_ready(python_path: Path) -> bool:
    try:
        subprocess.run(
            [str(python_path), "-m", "pip", "--version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def ensure_runtime_pip(python_path: Path) -> None:
    if runtime_pip_ready(python_path):
        return
    try:
        run_subprocess([str(python_path), "-m", "ensurepip", "--upgrade"], "恢复 runtime/.venv 中的 pip")
    except Exception as exc:  # noqa: BLE001
        raise JumpServerApiError(
            "runtime/.venv 缺少 pip，且无法通过 ensurepip 自动恢复，请检查当前 Python 是否包含 venv/ensurepip。"
        ) from exc
    if not runtime_pip_ready(python_path):
        raise JumpServerApiError("runtime/.venv 中的 pip 恢复失败，请重新初始化运行环境后重试。")


def ensure_runtime_venv() -> Path:
    python_path = runtime_python()
    if not python_path.exists():
        ensure_parent_dir(RUNTIME_VENV_DIR / ".keep")
        run_subprocess([sys.executable, "-m", "venv", str(RUNTIME_VENV_DIR)], "创建 runtime/.venv")
        python_path = runtime_python()
    ensure_runtime_pip(python_path)
    bootstrap_runtime_site_packages()
    return python_path


def detect_package_manager() -> Optional[List[str]]:
    for candidate in ("brew", "apt-get", "dnf", "yum"):
        path = shutil.which(candidate)
        if path:
            return [path]
    return None


def install_system_package(package: str) -> str:
    manager = detect_package_manager()
    if not manager:
        raise JumpServerApiError(f"缺少系统依赖 `{package}`，且未检测到可用包管理器。")

    command: List[str]
    if manager[0].endswith("brew"):
        command = manager + ["install", package]
    elif manager[0].endswith("apt-get"):
        command = manager + ["install", "-y", package]
    else:
        command = manager + ["install", "-y", package]
    subprocess.run(command, check=True)
    return f"已安装系统依赖 {package}"


def ensure_dependency_group(group: str) -> Dict[str, Any]:
    if group not in OPTIONAL_DEPENDENCIES:
        raise JumpServerApiError(f"未知依赖组：{group}")

    spec = OPTIONAL_DEPENDENCIES[group]
    python_path = ensure_runtime_venv()
    install_env = build_runtime_process_env()
    installed_python: List[str] = []
    installed_system: List[str] = []
    post_steps: List[str] = []

    if spec["python"]:
        run_subprocess(
            [str(python_path), "-m", "pip", "install", *spec["python"]],
            f"安装 `{group}` Python 依赖",
            retries=DEFAULT_INSTALL_RETRIES,
            env=install_env,
        )
        installed_python.extend(spec["python"])
    for package in spec["system"]:
        if shutil.which(package):
            continue
        installed_system.append(install_system_package(package))
    if group == "exec":
        post_steps.extend(install_playwright_chromium_runtime(python_path, install_env))
    else:
        for step in spec["post_install"]:
            run_subprocess(
                [str(python_path), *step],
                f"执行 `{group}` 后置安装",
                retries=DEFAULT_INSTALL_RETRIES,
                env=install_env,
            )
            post_steps.append(" ".join(step))

    bootstrap_runtime_site_packages()
    if group == "exec":
        RUNTIME_PROFILE["command_runtime_ready"] = None
    return {
        "group": group,
        "python_packages": installed_python,
        "system_actions": installed_system,
        "post_install": post_steps,
        "venv": str(RUNTIME_VENV_DIR),
        "playwright_browsers_path": str(PLAYWRIGHT_BROWSERS_DIR) if group == "exec" else None,
    }


def ensure_dependency_groups(groups: List[str]) -> Dict[str, Any]:
    normalized: List[str] = []
    seen: set[str] = set()
    for group in groups:
        if group not in OPTIONAL_DEPENDENCIES:
            raise JumpServerApiError(f"未知依赖组：{group}")
        if group in seen:
            continue
        seen.add(group)
        normalized.append(group)
    results = [ensure_dependency_group(group) for group in normalized]
    return {"target": ",".join(normalized), "results": results}


def bootstrap_dependency_groups(groups: List[str]) -> Dict[str, Any]:
    normalized: List[str] = []
    seen: set[str] = set()
    for group in groups:
        if group not in OPTIONAL_DEPENDENCIES:
            raise JumpServerApiError(f"未知依赖组：{group}")
        if group in seen:
            continue
        seen.add(group)
        normalized.append(group)

    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    for group in normalized:
        try:
            results.append(ensure_dependency_group(group))
        except Exception as exc:  # noqa: BLE001
            message = str(exc) or DEFAULT_ERROR_MESSAGE
            results.append({"group": group, "error": message})
            failures.append({"group": group, "error": message})
    return {
        "target": ",".join(normalized),
        "results": results,
        "failed_groups": [item["group"] for item in failures],
        "failures": failures,
    }


def ensure_dependencies(target: str) -> Dict[str, Any]:
    groups = list(OPTIONAL_DEPENDENCIES) if target == "all" else [target]
    return ensure_dependency_groups(groups)


def maybe_auto_install(target: str) -> None:
    if parse_bool_env("JMS_AUTO_INSTALL", True):
        ensure_dependencies(target)


def get_playwright_sync():
    try:
        module = importlib.import_module("playwright.sync_api")
    except Exception as exc:  # noqa: BLE001
        try:
            maybe_auto_install("exec")
            module = importlib.import_module("playwright.sync_api")
        except Exception as install_exc:  # noqa: BLE001
            raise JumpServerApiError("命令执行依赖 playwright，请先安装可用环境后重试") from install_exc
    return module.sync_playwright


def is_missing_playwright_browser_error(exc: Exception) -> bool:
    message = str(exc or "")
    hints = (
        "Executable doesn't exist",
        "Failed to launch chromium",
        "Please run the following command",
        "playwright install",
    )
    return any(hint in message for hint in hints)


def launch_chromium(playwright: Any):
    try:
        return playwright.chromium.launch(headless=True)
    except Exception as exc:  # noqa: BLE001
        if not is_missing_playwright_browser_error(exc):
            raise
        system_browser = find_system_chromium_executable()
        if system_browser:
            try:
                return playwright.chromium.launch(executable_path=system_browser, headless=True)
            except Exception:  # noqa: BLE001
                pass
        try:
            maybe_auto_install("exec")
            try:
                return playwright.chromium.launch(headless=True)
            except Exception as retry_exc:  # noqa: BLE001
                if not is_missing_playwright_browser_error(retry_exc):
                    raise
                system_browser = find_system_chromium_executable()
                if system_browser:
                    return playwright.chromium.launch(executable_path=system_browser, headless=True)
                raise
        except Exception as install_exc:  # noqa: BLE001
            raise JumpServerApiError(
                "命令执行依赖 Chromium 浏览器。脚本已优先尝试系统 Chrome/Chromium，并会自动切换 Playwright 下载源；"
                "若仍失败，请先安装系统 Chrome/Chromium，或补充 `PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST` / 代理后重试 "
                "`python3 scripts/jms_inspection.py ensure-deps exec`。"
            ) from install_exc


def ensure_command_runtime_ready() -> None:
    if RUNTIME_PROFILE.get("command_runtime_ready") is True:
        return
    sync_playwright = get_playwright_sync()
    with sync_playwright() as playwright:
        browser = launch_chromium(playwright)
        browser.close()
    RUNTIME_PROFILE["command_runtime_ready"] = True


def get_paramiko_module():
    try:
        return importlib.import_module("paramiko")
    except Exception as exc:  # noqa: BLE001
        try:
            maybe_auto_install("official")
            return importlib.import_module("paramiko")
        except Exception as install_exc:  # noqa: BLE001
            raise JumpServerApiError("official 巡检依赖 paramiko，请先安装可用环境后重试。") from install_exc


def run_remote_command(ssh_client: Any, command: str, timeout: int = 60) -> Dict[str, Any]:
    stdin, stdout, stderr = ssh_client.exec_command(command, timeout=timeout)
    exit_status = stdout.channel.recv_exit_status()
    stdout_text = stdout.read().decode("utf-8", "ignore")
    stderr_text = stderr.read().decode("utf-8", "ignore")
    return {
        "command": command,
        "exit_status": exit_status,
        "stdout": stdout_text,
        "stderr": stderr_text,
    }


def format_remote_failure(result: Dict[str, Any], summary: str) -> JumpServerApiError:
    output = "\n".join(
        part.strip()
        for part in (str(result.get("stdout") or ""), str(result.get("stderr") or ""))
        if part and part.strip()
    ).strip()
    if output:
        return JumpServerApiError(f"{summary}\n{output}")
    return JumpServerApiError(summary)


def build_official_bundle_dir(output_target: Path) -> Path:
    bundle_dir = output_target.parent / f"{output_target.stem}_official_bundle"
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    return bundle_dir


def run_official_legacy_probe(
    profile_name: str,
    output_target: Optional[Path] = None,
    check_only: bool = False,
) -> Dict[str, Any]:
    ssh_config = get_official_ssh_config()
    binary_info = prepare_official_runtime_binary()
    paramiko = get_paramiko_module()
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    remote_root = ""
    local_bundle_dir = build_official_bundle_dir(output_target) if output_target else None

    try:
        ssh_client.connect(
            hostname=ssh_config["host"],
            port=int(ssh_config["port"]),
            username=ssh_config["username"],
            password=ssh_config["password"],
            timeout=15,
            banner_timeout=15,
            auth_timeout=15,
            look_for_keys=False,
            allow_agent=False,
        )

        platform_result = run_remote_command(ssh_client, "uname -s && uname -m", timeout=15)
        if platform_result["exit_status"] != 0:
            raise format_remote_failure(platform_result, "获取远端平台信息失败。")
        platform_lines = [line.strip() for line in platform_result["stdout"].splitlines() if line.strip()]
        remote_system = platform_lines[0].lower() if platform_lines else ""
        remote_arch = platform_lines[1].lower() if len(platform_lines) > 1 else ""
        if remote_system != OFFICIAL_REMOTE_SYSTEM or remote_arch not in OFFICIAL_REMOTE_ARCHES:
            raise JumpServerApiError(
                f"official 巡检当前仅支持远端 {OFFICIAL_REMOTE_SYSTEM} amd64，检测到远端平台为 {remote_system or '-'} / {remote_arch or '-'}。"
            )

        config_path = ssh_config["remote_config_path"]
        config_check = run_remote_command(
            ssh_client,
            f"test -f {shlex.quote(config_path)} && echo __JMS_CONFIG_OK__",
            timeout=15,
        )
        config_exists = "__JMS_CONFIG_OK__" in config_check["stdout"]
        if config_check["exit_status"] != 0 or not config_exists:
            raise JumpServerApiError(f"远端未找到 JumpServer 配置文件：{config_path}")

        temp_result = run_remote_command(ssh_client, "mktemp -d /tmp/jms-official-XXXXXX", timeout=15)
        if temp_result["exit_status"] != 0:
            raise format_remote_failure(temp_result, "创建远端临时目录失败。")
        remote_root = temp_result["stdout"].strip().splitlines()[-1]
        remote_binary = f"{remote_root}/jms_inspect"
        remote_machine_file = f"{remote_root}/machine.yml"
        remote_output_dir = f"{remote_root}/output"

        sftp = ssh_client.open_sftp()
        try:
            sftp.put(binary_info["runtime_path"], remote_binary)
            with sftp.open(remote_machine_file, "w") as remote_file:
                remote_file.write(render_official_machine_config(profile_name, ssh_config))
        finally:
            sftp.close()

        chmod_result = run_remote_command(
            ssh_client,
            f"chmod 755 {shlex.quote(remote_binary)} && mkdir -p {shlex.quote(remote_output_dir)}",
            timeout=30,
        )
        if chmod_result["exit_status"] != 0:
            raise format_remote_failure(chmod_result, "准备远端 official 巡检运行目录失败。")

        command_parts = [
            shlex.quote(remote_binary),
            "-jc", shlex.quote(config_path),
            "-mt", shlex.quote(remote_machine_file),
            "-output-dir", shlex.quote(remote_output_dir),
            "-silent",
            "-auto-approve",
        ]
        if check_only:
            command_parts.append("-check-only")
        execute_result = run_remote_command(ssh_client, " ".join(command_parts), timeout=1800)
        if execute_result["exit_status"] != 0:
            raise format_remote_failure(execute_result, "执行 official 巡检失败。")

        payload: Dict[str, Any] = {
            "binary": binary_info,
            "remote_root": remote_root,
            "remote_output_dir": remote_output_dir,
            "remote_platform": {
                "system": remote_system,
                "arch": remote_arch,
            },
            "remote_config_path": config_path,
            "check_only": check_only,
            "stdout": execute_result["stdout"],
            "stderr": execute_result["stderr"],
        }
        if check_only:
            return payload

        if local_bundle_dir is None:
            raise JumpServerApiError("official 巡检缺少本地 bundle 输出目录。")

        sftp = ssh_client.open_sftp()
        downloaded_files: List[str] = []
        html_file: Optional[Path] = None
        json_file: Optional[Path] = None
        excel_file: Optional[Path] = None
        try:
            for entry in sftp.listdir_attr(remote_output_dir):
                remote_path = f"{remote_output_dir}/{entry.filename}"
                local_path = local_bundle_dir / entry.filename
                sftp.get(remote_path, str(local_path))
                downloaded_files.append(str(local_path))
                suffix = local_path.suffix.lower()
                if suffix == ".html":
                    html_file = local_path
                elif suffix == ".json":
                    json_file = local_path
                elif suffix in (".xlsx", ".xls"):
                    excel_file = local_path
        finally:
            sftp.close()

        if html_file is None or not html_file.exists():
            raise JumpServerApiError("official 巡检已执行，但未回收到 HTML 报告。")

        metadata = {
            "provider": "official",
            "profile_name": profile_name,
            "remote_host": ssh_config["host"],
            "remote_platform": payload["remote_platform"],
            "remote_config_path": config_path,
            "remote_root": remote_root,
            "downloaded_files": downloaded_files,
        }
        (local_bundle_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        payload.update({
            "bundle_dir": str(local_bundle_dir),
            "downloaded_files": downloaded_files,
            "html_file": str(html_file),
            "json_file": str(json_file) if json_file else None,
            "excel_file": str(excel_file) if excel_file else None,
            "html_text": html_file.read_text(encoding="utf-8", errors="ignore"),
        })
        return payload
    finally:
        if remote_root:
            try:
                run_remote_command(ssh_client, f"rm -rf {shlex.quote(remote_root)}", timeout=30)
            except Exception:  # noqa: BLE001
                pass
        try:
            ssh_client.close()
        except Exception:  # noqa: BLE001
            pass


def capture_terminal_text(page: Any) -> str:
    script = """
    () => {
      const selectors = [
        '.xterm-rows',
        '.xterm-screen',
        '.terminal-wrapper',
        '.terminal',
        '.xterm'
      ];
      for (const selector of selectors) {
        const node = document.querySelector(selector);
        if (node) {
          const text = (node.innerText || node.textContent || '').trim();
          if (text) return text;
        }
      }
      return (document.body && (document.body.innerText || document.body.textContent) || '').trim();
    }
    """
    return str(page.evaluate(script) or "").replace("\r\n", "\n").strip()


def focus_terminal(page: Any) -> None:
    for selector in ("textarea.xterm-helper-textarea", ".xterm-screen", ".xterm", "body"):
        locator = page.locator(selector)
        if locator.count():
            locator.first.click(force=True)
            return


def fill_first_visible(page: Any, selectors: Iterable[str], value: str) -> bool:
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count():
            try:
                locator.first.fill(value)
                return True
            except Exception:  # noqa: BLE001
                continue
    return False


def click_first_visible(page: Any, selectors: Iterable[str]) -> bool:
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count():
            try:
                locator.first.click()
                return True
            except Exception:  # noqa: BLE001
                continue
    return False


def is_login_page(page: Any) -> bool:
    return "/auth/login/" in page.url or "/core/auth/login/" in page.url


def has_terminal_surface(page: Any) -> bool:
    selectors = (
        ".xterm",
        ".xterm-screen",
        ".xterm-rows",
        "textarea.xterm-helper-textarea",
    )
    return any(page.locator(selector).count() for selector in selectors)


def login_jumpserver_web(page: Any, timeout_seconds: int) -> None:
    username = get_runtime_env("JUMPSERVER_USERNAME")
    password = get_runtime_env("JUMPSERVER_PASSWORD")
    if not username or not password:
        raise JumpServerApiError("命令巡检需要 JUMPSERVER_USERNAME 和 JUMPSERVER_PASSWORD 才能完成 Web 登录。")

    if not fill_first_visible(
        page,
        (
            "input[name='username']",
            "input[placeholder*='Username' i]",
            "input[autocomplete='username']",
            "input[type='text']",
        ),
        username,
    ):
        raise JumpServerApiError("未找到 JumpServer 登录页的用户名输入框。")
    if not fill_first_visible(
        page,
        (
            "input[name='password']",
            "input[autocomplete='current-password']",
            "input[type='password']",
        ),
        password,
    ):
        raise JumpServerApiError("未找到 JumpServer 登录页的密码输入框。")

    if not click_first_visible(
        page,
        (
            "button[type='submit']",
            "button:has-text('SIGN IN')",
            "button:has-text('Sign in')",
            "button:has-text('登录')",
        ),
    ):
        page.keyboard.press("Enter")

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        page.wait_for_timeout(600)
        if not is_login_page(page):
            return
    raise JumpServerApiError("JumpServer Web 登录未完成，请检查用户名、密码或登录策略。")


def ensure_terminal_page(page: Any, connect_url: str, timeout_seconds: int) -> None:
    page.goto(connect_url, wait_until="domcontentloaded", timeout=max(timeout_seconds, 10) * 1000)
    if is_login_page(page):
        login_jumpserver_web(page, timeout_seconds)
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        page.wait_for_timeout(800)
        if has_terminal_surface(page):
            return
    raise JumpServerApiError("终端页面未建立有效会话，请检查 token、账号授权或 Web Terminal 状态。")


def wait_for_terminal_change(page: Any, baseline: str, timeout_ms: int) -> str:
    deadline = time.time() + (timeout_ms / 1000)
    last_value = baseline
    while time.time() < deadline:
        time.sleep(0.6)
        current = capture_terminal_text(page)
        if current and current != baseline:
            last_value = current
            time.sleep(0.6)
            return capture_terminal_text(page) or last_value
    return last_value


def clean_terminal_output(text: str, command: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return "未采集到命令输出。"
    lines = [line.rstrip() for line in normalized.splitlines()]
    while lines and lines[0].strip() == command.strip():
        lines.pop(0)
    cleaned = "\n".join(lines).strip()
    if not cleaned:
        cleaned = normalized
    return cleaned[:DEFAULT_COMMAND_MAX_OUTPUT].strip()


def extract_terminal_delta(before: str, after: str, command: str) -> str:
    if after.startswith(before):
        return clean_terminal_output(after[len(before):], command)
    marker = after.rfind(command)
    if marker >= 0:
        return clean_terminal_output(after[marker + len(command):], command)
    return clean_terminal_output(after, command)


def decode_terminal_frame(payload: Any) -> str:
    if isinstance(payload, bytes):
        return payload.decode("utf-8", "ignore")
    text = str(payload or "")
    if not text:
        return ""
    if text.startswith("{") and text.endswith("}"):
        try:
            data = json.loads(text)
        except Exception:  # noqa: BLE001
            return text
        event_type = str(data.get("type") or "").strip().upper()
        if event_type in ("TERMINAL_ERROR", "CLOSE"):
            return humanize_value(data.get("err") or data.get("data"), default="")
        return ""
    return text


def normalize_terminal_stream_text(text: str) -> str:
    normalized = ANSI_OSC_RE.sub("", str(text or ""))
    normalized = ANSI_CSI_RE.sub("", normalized)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    buffer: List[str] = []
    for char in normalized:
        if char == "\x08":
            if buffer:
                buffer.pop()
            continue
        if char == "\x07":
            continue
        if ord(char) < 32 and char not in ("\n", "\t"):
            continue
        buffer.append(char)
    return "".join(buffer)


def extract_last_shell_prompt(text: str) -> str:
    matches = re.findall(r"([^\n]*@[^\n]*[#$] )", text)
    return matches[-1] if matches else ""


def clean_terminal_command_output(raw_text: str, command: str, prompt: str = "") -> str:
    normalized = normalize_terminal_stream_text(raw_text).strip()
    if not normalized:
        return MISSING_COMMAND_OUTPUT
    if prompt and normalized.endswith(prompt.strip()):
        normalized = normalized[: -len(prompt.strip())].rstrip()
    compact_normalized = re.sub(r"\s+", "", normalized)
    compact_command = re.sub(r"\s+", "", command)
    if compact_command and compact_normalized.startswith(compact_command):
        stripped_index = 0
        consumed = 0
        for index, char in enumerate(normalized):
            if not char.isspace():
                consumed += 1
            if consumed >= len(compact_command):
                stripped_index = index + 1
                break
        normalized = normalized[stripped_index:].lstrip()
    lines = [line.rstrip() for line in normalized.splitlines()]
    while lines and lines[0].strip() == command.strip():
        lines.pop(0)
    cleaned = "\n".join(line for line in lines if line.strip() or len(lines) == 1).strip()
    if not cleaned:
        return MISSING_COMMAND_OUTPUT
    return cleaned[:DEFAULT_COMMAND_MAX_OUTPUT].strip()


def get_dict_value(row: Dict[str, Any], key: str, default: Any = None) -> Any:
    target = str(key or "").strip().lower()
    for candidate_key, value in row.items():
        if str(candidate_key or "").strip().lower() == target:
            return value
    return default


def wait_for_terminal_prompt(
    frames: List[str],
    timeout_seconds: int,
    prompt_hint: str = "",
    start_index: int = 0,
    page: Any = None,
) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if page is not None:
            page.wait_for_timeout(500)
        else:
            time.sleep(0.5)
        text = normalize_terminal_stream_text("".join(frames[start_index:]))
        prompt = extract_last_shell_prompt(text) or prompt_hint
        if prompt and text.rstrip().endswith(prompt.strip()):
            return prompt
    return prompt_hint


def run_commands_via_browser(token_id: str, commands: List[str], timeout_seconds: int) -> List[Dict[str, str]]:
    cfg = get_env_config()
    connect_url = f"{cfg['base_url']}/koko/connect?token={urllib.parse.quote(token_id)}"
    sync_playwright = get_playwright_sync()
    results: List[Dict[str, str]] = []

    with sync_playwright() as playwright:
        browser = launch_chromium(playwright)
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, ignore_https_errors=True)
        ws_frames: List[str] = []

        def handle_ws(ws: Any) -> None:
            if "/koko/ws/terminal/" not in str(getattr(ws, "url", "")):
                return

            def on_frame(payload: Any) -> None:
                decoded = decode_terminal_frame(payload)
                if decoded:
                    ws_frames.append(decoded)

            ws.on("framereceived", on_frame)

        page.on("websocket", handle_ws)
        ensure_terminal_page(page, connect_url, timeout_seconds=max(timeout_seconds, 20))
        page.wait_for_timeout(1000)
        focus_terminal(page)
        prompt_hint = wait_for_terminal_prompt(ws_frames, timeout_seconds=max(timeout_seconds, 8), page=page)

        for command in commands:
            start_index = len(ws_frames)
            page.locator("textarea.xterm-helper-textarea").focus()
            page.keyboard.insert_text(command)
            page.keyboard.press("Enter")
            prompt_hint = wait_for_terminal_prompt(
                ws_frames,
                timeout_seconds=max(timeout_seconds, 8),
                prompt_hint=prompt_hint,
                start_index=start_index,
                page=page,
            )
            chunk = "".join(ws_frames[start_index:])
            output = clean_terminal_command_output(chunk, command, prompt=prompt_hint)
            if output == "未采集到命令输出。":
                baseline = capture_terminal_text(page)
                updated = wait_for_terminal_change(page, baseline, timeout_seconds * 1000)
                output = extract_terminal_delta(baseline, updated, command)
            results.append({"command": command, "output": output})
        browser.close()

    return results


def collect_command_evidence(targets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    precheck_error = get_command_execution_error(targets)
    if precheck_error:
        for target in targets:
            evidence.append({
                "target_name": target["name"],
                "asset": target["asset"],
                "account": target["account"],
                "status": "error",
                "error": precheck_error,
                "results": [],
            })
        return evidence

    for target in targets:
        try:
            token = create_connection_token(target)
            results = run_commands_via_browser(token["id"], target["commands"], target.get("timeout", DEFAULT_COMMAND_TIMEOUT))
            evidence.append({
                "target_name": target["name"],
                "asset": target["asset"],
                "account": target["account"],
                "status": "ok",
                "results": results,
            })
        except Exception as exc:  # noqa: BLE001
            evidence.append({
                "target_name": target["name"],
                "asset": target["asset"],
                "account": target["account"],
                "status": "error",
                "error": str(exc),
                "results": [],
            })
    return evidence


def extract_probe_sections(text: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    current_name = ""
    buffer: List[str] = []
    for raw_line in normalize_terminal_stream_text(text).splitlines():
        line = raw_line.rstrip()
        begin_match = PROBE_SECTION_BEGIN_RE.match(line.strip())
        if begin_match:
            current_name = begin_match.group(1)
            buffer = []
            continue
        end_match = PROBE_SECTION_END_RE.match(line.strip())
        if end_match:
            if current_name and end_match.group(1) == current_name:
                sections[current_name] = "\n".join(buffer).strip()
            current_name = ""
            buffer = []
            continue
        if current_name:
            buffer.append(line)
    if current_name:
        sections[current_name] = "\n".join(buffer).strip()
    return sections


def extract_labeled_outputs(target: Dict[str, Any], evidence_item: Dict[str, Any]) -> Dict[str, str]:
    specs = target.get("legacy_specs") or []
    outputs: Dict[str, str] = {}
    results = evidence_item.get("results", [])
    for index, spec in enumerate(specs):
        output = ""
        if index < len(results):
            output = str(results[index].get("output") or "").strip()
        outputs[str(spec.get("label"))] = output
        section_outputs = extract_probe_sections(output)
        if section_outputs:
            outputs.update(section_outputs)
    return outputs


def parse_os_release_info(text: str) -> Dict[str, str]:
    values = parse_key_value_text(text)
    return {
        "id": str(values.get("ID") or "").strip().lower(),
        "id_like": str(values.get("ID_LIKE") or "").strip().lower(),
        "pretty_name": str(values.get("PRETTY_NAME") or values.get("NAME") or "").strip(),
    }


def parse_cpuinfo_snapshot(text: str) -> Dict[str, str]:
    logical_cpus = 0
    sockets: set[str] = set()
    cores_per_socket = "-"
    model = "-"
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = [item.strip() for item in line.split(":", 1)]
        if key == "processor":
            logical_cpus += 1
        elif key == "physical id":
            sockets.add(value)
        elif key == "cpu cores" and cores_per_socket == "-":
            cores_per_socket = value or "-"
        elif key == "model name" and model == "-":
            model = value or "-"
    socket_count = len(sockets) if sockets else (1 if logical_cpus else 0)
    return {
        "sockets": str(socket_count) if socket_count else "-",
        "cores_per_socket": cores_per_socket or "-",
        "logical_cpus": str(logical_cpus) if logical_cpus else "-",
        "model": model or "-",
        "cpu_count": str(logical_cpus) if logical_cpus else "-",
    }


def parse_memory_snapshot(text: str) -> Dict[str, str]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    result = {"total": "-", "used": "-", "free": "-", "swap": "-"}
    def format_memory_value(value: str) -> str:
        clean = str(value or "").strip()
        if clean.isdigit():
            return f"{clean} MB"
        return clean or "-"
    for line in lines:
        normalized = re.split(r"\s+", line)
        if line.lower().startswith("mem:") and len(normalized) >= 4:
            result["total"] = format_memory_value(normalized[1])
            result["used"] = format_memory_value(normalized[2])
            result["free"] = format_memory_value(normalized[3])
        if line.lower().startswith("swap:") and len(normalized) >= 2:
            result["swap"] = format_memory_value(normalized[1])
    return result


def parse_mem_top_rows(text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for index, raw_line in enumerate(str(text or "").splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        if index == 0 and "%cpu" in line.lower() and "%mem" in line.lower():
            continue
        parts = re.split(r"\s+", line, maxsplit=10)
        if len(parts) < 11:
            continue
        rows.append({
            "user": parts[0],
            "pid": parts[1],
            "cpu": parts[2],
            "mem": parts[3],
            "rss": parts[5],
            "command": humanize_value(parts[10], default="-")[:140],
        })
    return rows


def parse_key_value_lines(text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        rows.append({"item": line})
    return rows


def parse_named_usage_rows(text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            rows.append({"name": parts[0].strip(), "usage": parts[1].strip()})
        else:
            rows.append({"name": line, "usage": "-"})
    return rows


def parse_large_file_rows(text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line == "-":
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2:
            size, path = parts
        else:
            split_parts = re.split(r"\s+", line, maxsplit=1)
            if len(split_parts) != 2:
                continue
            size, path = split_parts
        rows.append({"size": size.strip(), "path": path.strip()})
    return rows


def parse_jmsctl_status_rows(text: str) -> List[Dict[str, str]]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    header = lines[0]
    if not (header.startswith("NAME") and "SERVICE" in header and "STATUS" in header):
        return []
    rows: List[Dict[str, str]] = []
    for line in lines[1:]:
        parts = re.split(r"\s{2,}", line, maxsplit=6)
        if len(parts) < 6:
            continue
        name = parts[0]
        image = parts[1]
        service = parts[3] if len(parts) >= 4 else "-"
        created = parts[4] if len(parts) >= 5 else "-"
        status = parts[5] if len(parts) >= 6 else "-"
        ports = parts[6] if len(parts) >= 7 else "-"
        rows.append({
            "name": name.strip(),
            "image": image.strip(),
            "service": service.strip(),
            "created": created.strip(),
            "status": status.strip(),
            "ports": ports.strip() or "-",
        })
    return rows


def parse_container_rows(text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            parts = re.split(r"\s{2,}", line, maxsplit=2)
        if len(parts) >= 3:
            name, status, ports = parts[0], parts[1], parts[2]
        elif len(parts) == 2:
            name, status = parts
            ports = "-"
        else:
            name, status, ports = line, "-", "-"
        rows.append({"name": name.strip(), "status": status.strip(), "ports": ports.strip() or "-"})
    return rows


def map_disk_rows(text: str, target_name: str) -> List[Dict[str, Any]]:
    return parse_df_output(text, target_name)


def parse_system_target_snapshot(target: Dict[str, Any], evidence_item: Dict[str, Any]) -> Dict[str, Any]:
    outputs = extract_labeled_outputs(target, evidence_item)
    asset_row = target.get("asset_row") or {}
    os_release = parse_os_release_info(outputs.get("os_release", ""))
    cpu_info = parse_cpuinfo_snapshot(outputs.get("cpuinfo", ""))
    zombie_rows = parse_key_value_lines(outputs.get("zombie_detail", ""))
    jmsctl_rows = parse_jmsctl_status_rows(outputs.get("jmsctl_status", ""))
    replay_storage = outputs.get("replay_storage") or "-"
    if replay_storage == MISSING_COMMAND_OUTPUT:
        replay_storage = "-"
    return {
        "name": target["name"],
        "role": target.get("role", "jumpserver"),
        "asset_name": humanize_value(asset_row.get("name"), default=target.get("asset_name", target["name"])),
        "platform": humanize_value(extract_first(asset_row, "platform_display", "platform", "type", default="JumpServer"), default="JumpServer"),
        "ip": humanize_value(extract_first(asset_row, "address", "ip", "hostname", default="-")),
        "port": humanize_value(extract_first(asset_row, "port", default="-")),
        "username": humanize_value(target.get("account_name"), default="-"),
        "enabled": "是" if str(extract_first(asset_row, "is_active", default=True)).lower() not in ("false", "0", "disabled", "inactive") else "否",
        "status": humanize_value(extract_first(asset_row, "connectivity", "status", default="正常")),
        "system_info": {
            "hostname": outputs.get("sys_hostname") or humanize_value(extract_first(asset_row, "hostname", "name", default="-")),
            "lang": "-",
            "address": humanize_value(extract_first(asset_row, "address", "ip", default="-")),
            "os": os_release.get("pretty_name") or "-",
            "kernel": outputs.get("sys_kernel") or "-",
            "arch": outputs.get("sys_arch") or "-",
            "current_time": outputs.get("sys_now") or "-",
            "boot_time": "-",
            "uptime": outputs.get("sys_uptime") or "-",
            "app_version": outputs.get("app_version") or "-",
        },
        "cpu_info": {
            "sockets": cpu_info["sockets"],
            "cores_per_socket": cpu_info["cores_per_socket"],
            "logical_cpus": cpu_info["logical_cpus"],
            "model": cpu_info["model"],
        },
        "memory_info": parse_memory_snapshot(outputs.get("mem_free", "")),
        "system_params": {
            "firewall": outputs.get("firewall") or "-",
            "firewall_rules": outputs.get("firewall_rules") or "-",
            "zombie_processes": str(len(zombie_rows)) if zombie_rows and zombie_rows[0].get("item") != MISSING_COMMAND_OUTPUT else "0",
            "zombie_detail": outputs.get("zombie_detail") or "-",
            "loadavg": outputs.get("sys_uptime") or "-",
        },
        "component_rows": parse_container_rows(outputs.get("containers", "")),
        "component_status_rows": parse_key_value_lines(outputs.get("jmsctl_status", "")),
        "component_status_structured_rows": jmsctl_rows,
        "container_memory_rows": parse_named_usage_rows(outputs.get("container_mem", "")),
        "disk_rows": map_disk_rows(outputs.get("disk", ""), target["name"]),
        "top_memory_rows": parse_mem_top_rows(outputs.get("mem_top", "")),
        "large_file_rows": parse_large_file_rows(outputs.get("large_files", "")),
        "replay_storage": replay_storage,
        "cpu_count": cpu_info["cpu_count"],
        "remote_config_text": outputs.get("db_config", ""),
        "raw_outputs": outputs,
        "status_ok": evidence_item.get("status") == "ok",
        "error": evidence_item.get("error"),
    }


def build_date_series(rows: List[Dict[str, Any]], start_date: str, end_date: str, key: str = "value") -> List[Dict[str, Any]]:
    by_day = {str(row.get("day")): int(row.get(key) or 0) for row in rows}
    start = parse_date(start_date).date()
    end = parse_date(end_date).date()
    result: List[Dict[str, Any]] = []
    cursor = start
    while cursor <= end:
        day = cursor.strftime("%Y-%m-%d")
        result.append({"day": day, "value": by_day.get(day, 0)})
        cursor += timedelta(days=1)
    return result


def parse_df_output(output: str, target_name: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("filesystem"):
            continue
        parts = re.split(r"\s+", stripped)
        if len(parts) < 7:
            continue
        usage_text = next((item for item in parts if item.endswith("%")), "")
        if not usage_text:
            continue
        try:
            usage = int(usage_text.rstrip("%"))
        except ValueError:
            continue
        rows.append({
            "target_name": target_name,
            "filesystem": parts[0],
            "type": parts[1],
            "size": parts[2],
            "used": parts[3],
            "avail": parts[4],
            "usage": usage,
            "mount": parts[-1],
        })
    return rows


def build_command_stats(command_evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    command_rows: List[Dict[str, str]] = []
    filesystem_rows: List[Dict[str, Any]] = []
    anomalies: List[Dict[str, str]] = []
    success_targets = 0

    for item in command_evidence:
        target_name = item["target_name"]
        if item.get("status") == "ok":
            success_targets += 1
        else:
            anomalies.append({
                "level": "一般",
                "node": target_name,
                "description": f"系统命令采集失败：{humanize_value(item.get('error'), default='未知错误')}",
            })
        for result in item.get("results", []):
            output = result.get("output", "")
            command_rows.append({
                "target_name": target_name,
                "command": result.get("command", "-"),
                "output": output or "未采集到命令输出。",
            })
            if str(result.get("command", "")).strip().startswith("df "):
                filesystem_rows.extend(parse_df_output(output, target_name))

    for row in filesystem_rows:
        if row["usage"] >= 90:
            level = "严重"
        elif row["usage"] >= 80:
            level = "一般"
        else:
            continue
        anomalies.append({
            "level": level,
            "node": row["target_name"],
            "description": f"{row['mount']} 挂载点使用率 {row['usage']}%，文件系统 {row['filesystem']}。",
        })

    summary_items = []
    if command_evidence:
        total_commands = sum(len(item.get("results", [])) for item in command_evidence)
        summary_items.append(f"系统命令采集节点：{len(command_evidence)}")
        summary_items.append(f"命令执行成功节点：{success_targets}")
        summary_items.append(f"命令采样条数：{total_commands}")
    else:
        summary_items.append("当前 profile 未配置命令巡检目标。")

    high_usage = [row for row in filesystem_rows if row["usage"] >= 80]
    if high_usage:
        summary_items.append(f"磁盘高使用率挂载点：{len(high_usage)}")
    return {
        "targets": len(command_evidence),
        "success_targets": success_targets,
        "commands": command_rows,
        "filesystem_rows": filesystem_rows,
        "anomalies": anomalies,
        "summary_items": summary_items,
    }


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


def get_login_logs(date_from: str, date_to: Optional[str] = None, org_id: Optional[str] = None) -> List[Dict[str, Any]]:
    date_to = date_to or date_from
    logs = fetch_jumpserver_data_paged(
        "/api/v1/audits/login-logs/",
        params={"days": range_days(date_from, date_to)},
        org_id=org_id,
    )
    return filter_records_by_date(logs, date_from, date_to)


def get_assets(org_id: Optional[str] = None) -> List[Dict[str, Any]]:
    return fetch_jumpserver_data("/api/v1/assets/assets/", params={"limit": 1000}, org_id=org_id)


def get_users(org_id: Optional[str] = None) -> List[Dict[str, Any]]:
    return fetch_jumpserver_data("/api/v1/users/users/", params={"limit": 1000}, org_id=org_id)


def get_active_sessions(org_id: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        return fetch_jumpserver_data("/api/v1/audits/user-sessions/", params={"is_active": "true", "limit": 1000}, org_id=org_id)
    except JumpServerApiError:
        return fetch_jumpserver_data("/api/v1/terminal/sessions/", params={"is_finished": "false", "limit": 1000}, org_id=org_id)


def get_operate_logs(date_from: str, date_to: Optional[str] = None, org_id: Optional[str] = None) -> List[Dict[str, Any]]:
    date_to = date_to or date_from
    try:
        logs = fetch_jumpserver_data_paged(
            "/api/v1/audits/operate-logs/",
            params={"days": range_days(date_from, date_to)},
            org_id=org_id,
        )
    except JumpServerApiError:
        logs = fetch_jumpserver_data_paged(
            "/api/v1/audits/operate-logs/",
            params={},
            org_id=org_id,
        )
    return filter_records_by_date(logs, date_from, date_to)


def safe_fetch(fetcher, fallback_message: str):
    try:
        return fetcher(), None
    except Exception:  # noqa: BLE001
        return [], fallback_message


def build_login_stats(logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    failures: List[Dict[str, str]] = []
    by_user: Counter[str] = Counter()
    by_ip: Counter[str] = Counter()
    all_users: Counter[str] = Counter()
    all_assets: Counter[str] = Counter()
    success = 0
    for item in logs:
        username = humanize_value(extract_first(item, "username", "user", "user_display", default="未知用户"), default="未知用户")
        ip = humanize_value(extract_first(item, "ip", "remote_addr", "client_ip", default="未知IP"), default="未知IP")
        asset = humanize_value(extract_first(item, "asset", "asset_display", "asset_name", "host", default=""), default="")
        status_value = extract_first(item, "status", "is_success", "success", default="未知")
        message = humanize_value(extract_first(item, "reason", "message", "detail", default=""), default="")
        all_users[username] += 1
        if asset:
            all_assets[asset] += 1
        is_success = is_success_status(status_value)
        if is_success:
            success += 1
            continue
        failure = {
            "time": humanize_value(extract_first(item, "datetime", "date_start", "timestamp", "created_at", default="-")),
            "username": username,
            "ip": ip,
            "asset": asset or "-",
            "message": message or "-",
        }
        failures.append(failure)
        by_user[username] += 1
        by_ip[ip] += 1
    return {
        "total": len(logs),
        "success": success,
        "failure": len(failures),
        "failure_details": failures,
        "failure_users": by_user,
        "failure_ips": by_ip,
        "all_users": all_users,
        "all_assets": all_assets,
    }


def build_asset_stats(assets: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows: List[Dict[str, str]] = []
    platform_counter: Counter[str] = Counter()
    abnormal_rows: List[Dict[str, str]] = []
    enabled = 0
    disabled = 0
    for item in assets:
        platform = humanize_value(extract_first(item, "platform_display", "platform", "type", "os", default="未知平台"), default="未知平台")
        name = humanize_value(extract_first(item, "name", "hostname", "address", default="未知资产"), default="未知资产")
        ip = humanize_value(extract_first(item, "address", "ip", "ip_display", "hostname", default="-"))
        port = humanize_value(extract_first(item, "port", "protocol_port", default="-"))
        username = humanize_value(extract_first(item, "username", "admin_user", "account", "accounts", default="-"))
        active_value = extract_first(item, "is_active", "active", default=True)
        is_enabled = not (str(active_value).strip().lower() in ("false", "0", "disabled", "inactive") or active_value is False)
        status = humanize_value(extract_first(item, "connectivity", "status", "health_status", default="正常" if is_enabled else "停用"))
        platform_counter[platform] += 1
        if is_enabled:
            enabled += 1
        else:
            disabled += 1
        row = {
            "name": name,
            "platform": platform,
            "ip": ip,
            "port": port,
            "username": username,
            "enabled": "是" if is_enabled else "否",
            "status": status,
        }
        rows.append(row)
        status_lower = status.lower()
        if any(keyword in status_lower for keyword in ("error", "fail", "invalid", "offline", "unknown", "异常")) or not is_enabled:
            abnormal_rows.append(row)
    return {
        "total": len(assets),
        "enabled": enabled,
        "disabled": disabled,
        "abnormal": len(abnormal_rows),
        "platform_counter": platform_counter,
        "rows": rows,
        "abnormal_rows": abnormal_rows,
    }


def build_session_stats(sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    user_counter: Counter[str] = Counter()
    asset_counter: Counter[str] = Counter()
    risky_items: List[str] = []
    rows: List[Dict[str, str]] = []
    for item in sessions:
        username = humanize_value(extract_first(item, "user", "username", "user_display", default="未知用户"), default="未知用户")
        asset = humanize_value(extract_first(item, "asset", "asset_display", "asset_name", "host", default="未知资产"), default="未知资产")
        remote_addr = humanize_value(extract_first(item, "remote_addr", "ip", "client_ip", default="未知IP"), default="未知IP")
        protocol = humanize_value(extract_first(item, "login_from", "protocol", "type", default="未知方式"), default="未知方式")
        start_at = humanize_value(extract_first(item, "date_start", "created_at", "datetime", default="-"))
        user_counter[username] += 1
        asset_counter[asset] += 1
        rows.append({
            "username": username,
            "asset": asset,
            "remote_addr": remote_addr,
            "protocol": protocol,
            "start_at": start_at,
        })
        if remote_addr in ("未知IP", "127.0.0.1"):
            risky_items.append(f"用户 {username} 的会话来源地址异常：{remote_addr}")
        if protocol.strip().lower() in ("telnet",):
            risky_items.append(f"用户 {username} 使用高风险协议：{protocol}")
    return {
        "total": len(sessions),
        "user_counter": user_counter,
        "asset_counter": asset_counter,
        "rows": rows,
        "risky_items": risky_items,
    }


def build_operate_stats(logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    user_counter: Counter[str] = Counter()
    action_counter: Counter[str] = Counter()
    dangerous_rows: List[Dict[str, str]] = []
    rows: List[Dict[str, str]] = []
    for item in logs:
        username = humanize_value(extract_first(item, "user", "username", "operator", default="未知用户"), default="未知用户")
        action = humanize_value(extract_first(item, "action", "resource", "operate", "type", default="未知动作"), default="未知动作")
        target = humanize_value(extract_first(item, "resource", "object", "asset", "asset_display", default="-"))
        created_at = humanize_value(extract_first(item, "datetime", "created_at", "date_start", default="-"))
        user_counter[username] += 1
        action_counter[action] += 1
        row = {
            "time": created_at,
            "username": username,
            "action": action,
            "target": target,
        }
        rows.append(row)
        action_lower = action.lower()
        if any(keyword in action_lower for keyword in ("delete", "remove", "drop", "force", "destroy")):
            dangerous_rows.append(row)
    return {
        "total": len(logs),
        "user_counter": user_counter,
        "action_counter": action_counter,
        "rows": rows,
        "dangerous_rows": dangerous_rows,
    }


def join_bullets(items: Iterable[str], empty_text: str) -> str:
    normalized = [item.strip() for item in items if item and item.strip()]
    if not normalized:
        return f"- {empty_text}"
    return "\n".join(f"- {item}" for item in normalized)


def build_security_risk_items(login_stats: Dict[str, Any], session_stats: Dict[str, Any], operate_stats: Dict[str, Any]) -> List[str]:
    items: List[str] = []
    blast_ips = [f"{ip}（{cnt} 次）" for ip, cnt in login_stats["failure_ips"].items() if cnt >= 5]
    blast_users = [f"{user}（{cnt} 次）" for user, cnt in login_stats["failure_users"].items() if cnt >= 5]
    if blast_ips:
        items.append(f"疑似爆破来源 IP：{', '.join(sorted(blast_ips))}")
    if blast_users:
        items.append(f"高频失败账号：{', '.join(sorted(blast_users))}")
    if session_stats["risky_items"]:
        items.append(f"检测到高风险会话线索：{len(session_stats['risky_items'])} 条")
    if operate_stats["dangerous_rows"]:
        items.append(f"高风险操作审计记录：{len(operate_stats['dangerous_rows'])} 条")
    return items


def summarize_login_logs(stats: Dict[str, Any], error: Optional[str] = None) -> str:
    lines = [
        f"登录日志总数：{stats['total']}",
        f"登录成功：{stats['success']}",
        f"登录失败：{stats['failure']}",
    ]
    for username, cnt in stats["failure_users"].most_common(5):
        lines.append(f"失败用户 TOP：{username}（{cnt} 次）")
    for ip, cnt in stats["failure_ips"].most_common(5):
        lines.append(f"失败来源 IP TOP：{ip}（{cnt} 次）")
    for item in stats["failure_details"][:10]:
        reason = f"，原因：{item['message']}" if item["message"] not in ("", "-") else ""
        lines.append(f"[{item['time']}] 用户 {item['username']} 来自 {item['ip']}{reason}")
    if stats["failure"] == 0:
        lines.append("今日未发现登录失败记录。")
    if error:
        lines.insert(0, error)
    return join_bullets(lines, "今日未查询到登录日志。")


def summarize_assets(stats: Dict[str, Any], error: Optional[str] = None) -> str:
    lines = [
        f"资产总数：{stats['total']}",
        f"启用资产：{stats['enabled']}",
        f"禁用资产：{stats['disabled']}",
        f"疑似异常资产：{stats['abnormal']}",
    ]
    for platform, cnt in stats["platform_counter"].most_common(10):
        lines.append(f"平台分布：{platform}（{cnt}）")
    if error:
        lines.insert(0, error)
    return join_bullets(lines, "未查询到资产数据。")


def summarize_active_sessions(stats: Dict[str, Any], error: Optional[str] = None) -> str:
    lines = [f"当前活跃会话数：{stats['total']}"]
    for username, cnt in stats["user_counter"].most_common(5):
        lines.append(f"在线用户 TOP：{username}（{cnt} 个会话）")
    for asset, cnt in stats["asset_counter"].most_common(5):
        lines.append(f"会话目标资产 TOP：{asset}（{cnt} 个会话）")
    if stats["risky_items"]:
        lines.extend(stats["risky_items"][:10])
    else:
        lines.append("暂未发现明显高风险活跃会话。")
    if error:
        lines.insert(0, error)
    return join_bullets(lines, "当前无活跃会话。")


def summarize_operate_logs(stats: Dict[str, Any], error: Optional[str] = None) -> str:
    lines = [f"操作审计记录数：{stats['total']}"]
    for username, cnt in stats["user_counter"].most_common(5):
        lines.append(f"高频操作用户：{username}（{cnt} 次）")
    for action, cnt in stats["action_counter"].most_common(10):
        lines.append(f"高频操作类型：{action}（{cnt} 次）")
    if error:
        lines.insert(0, error)
    return join_bullets(lines, "未查询到操作审计日志。")


def get_public_settings() -> Dict[str, Any]:
    cache_key = "public_settings"
    cached = RUNTIME_PROFILE.get(cache_key)
    if isinstance(cached, dict):
        return cached
    try:
        payload = request_jumpserver_json("/api/v1/settings/public/", include_default_org=False)
        settings = payload if isinstance(payload, dict) else {}
    except Exception:  # noqa: BLE001
        settings = {}
    RUNTIME_PROFILE[cache_key] = settings
    return settings


def detect_platform_version_label() -> str:
    explicit = get_runtime_env("JMS_REPORT_VERSION") or get_runtime_env("JUMPSERVER_VERSION")
    if explicit:
        return explicit
    settings = get_public_settings()
    interface = settings.get("INTERFACE") if isinstance(settings.get("INTERFACE"), dict) else {}
    vendor = humanize_value(interface.get("vendor"), default="")
    if vendor:
        return vendor
    return "JumpServer"


def build_report_notice_items(context: Dict[str, Any]) -> List[str]:
    items: List[str] = []
    if context.get("command_target_error"):
        items.append(
            "未采集到服务器命令巡检数据：缺少 JumpServer 服务器资产/IP 与账号映射，请补充后重跑。"
        )
    if context.get("operate_error"):
        items.append(f"操作审计接口存在兼容性问题，已降级处理：{context['operate_error']}")
    if not context.get("metadata", {}).get("version") or context["metadata"]["version"] in ("未知", "JumpServer"):
        items.append("版本号未从服务器本机获取，当前仅展示接口侧可识别平台信息。")
    return items


def build_report_metadata(profile_name: str, report_date: str, generated_at: datetime, scope_name: str) -> Dict[str, str]:
    cfg = get_env_config()
    hostname = urllib.parse.urlparse(cfg["base_url"]).hostname or profile_name
    company = get_runtime_env("JMS_REPORT_COMPANY", "JumpServer Inspection")
    return {
        "title": get_runtime_env("JMS_REPORT_TITLE", DEFAULT_REPORT_TITLE),
        "profile_name": get_runtime_env("JMS_REPORT_PROFILE_NAME", profile_name),
        "customer": get_runtime_env("JMS_REPORT_CUSTOMER", hostname),
        "company": company,
        "version": detect_platform_version_label(),
        "theme_color": get_runtime_env("JMS_REPORT_THEME_COLOR", "#4b917d"),
        "report_date": report_date,
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M:%S"),
        "base_url": cfg["base_url"],
        "scope_name": scope_name,
        "profile_source": RUNTIME_PROFILE.get("source") or "shell environment",
    }


def build_anomaly_rows(context: Dict[str, Any]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    login_stats = context["login_stats"]
    asset_stats = context["asset_stats"]
    session_stats = context["session_stats"]
    operate_stats = context["operate_stats"]

    for ip, cnt in login_stats["failure_ips"].most_common(5):
        if cnt >= 5:
            rows.append({
                "level": "严重" if cnt >= 10 else "一般",
                "node": ip,
                "description": f"登录失败次数偏高，共 {cnt} 次，请复核是否存在爆破或凭据异常。",
            })

    for row in asset_stats["abnormal_rows"][:8]:
        rows.append({
            "level": "一般",
            "node": row["name"],
            "description": f"资产状态为 {row['status']}，启用状态：{row['enabled']}。",
        })

    for item in session_stats["risky_items"][:5]:
        rows.append({
            "level": "轻微",
            "node": "活跃会话",
            "description": item,
        })

    if operate_stats["dangerous_rows"]:
        rows.append({
            "level": "一般",
            "node": "操作审计",
            "description": f"检测到 {len(operate_stats['dangerous_rows'])} 条高风险操作记录。",
        })

    rows.extend(context["command_stats"]["anomalies"][:6])

    return rows[:12]


def build_risk_level(context: Dict[str, Any]) -> str:
    login_stats = context["login_stats"]
    asset_stats = context["asset_stats"]
    session_stats = context["session_stats"]
    operate_stats = context["operate_stats"]

    if (
        login_stats["failure"] >= 20
        or any(cnt >= 10 for cnt in login_stats["failure_ips"].values())
        or asset_stats["abnormal"] >= 5
        or session_stats["risky_items"]
        or operate_stats["dangerous_rows"]
        or any(item["level"] == "严重" for item in context["command_stats"]["anomalies"])
    ):
        return "高"
    if login_stats["failure"] >= 5 or asset_stats["abnormal"] >= 1 or context["command_stats"]["anomalies"]:
        return "中"
    return "低"


def build_executive_summary_items(context: Dict[str, Any]) -> List[str]:
    return [
        f"巡检日期：{context['report_date']}",
        f"组织范围：{context['metadata']['scope_name']}",
        f"风险等级：{context['risk_level']}",
        f"资产总数：{context['asset_stats']['total']}",
        f"系统命令巡检：{context['command_stats']['success_targets']}/{context['command_stats']['targets']} 节点成功",
        f"活跃会话：{context['session_stats']['total']}",
        f"登录失败：{context['login_stats']['failure']}",
        f"异常资产：{context['asset_stats']['abnormal']}",
        f"操作审计：{'已获取' if context['operate_stats']['total'] else '未获取/接口异常'}",
    ]


def build_key_finding_items(context: Dict[str, Any]) -> List[str]:
    items: List[str] = []
    login_stats = context["login_stats"]
    asset_stats = context["asset_stats"]
    session_stats = context["session_stats"]
    operate_stats = context["operate_stats"]

    if login_stats["failure_ips"]:
        ip, cnt = login_stats["failure_ips"].most_common(1)[0]
        items.append(f"登录失败最集中来源 IP：{ip}（{cnt} 次）")
    if login_stats["failure_users"]:
        user, cnt = login_stats["failure_users"].most_common(1)[0]
        items.append(f"登录失败最高账号：{user}（{cnt} 次）")
    if asset_stats["abnormal_rows"]:
        names = "，".join(row["name"] for row in asset_stats["abnormal_rows"][:5])
        items.append(f"存在待核查资产：{names}")
    if context["command_stats"]["anomalies"]:
        items.append(f"系统命令巡检发现 {len(context['command_stats']['anomalies'])} 条待处理异常。")
    if session_stats["total"]:
        items.append(f"当前存在 {session_stats['total']} 个活跃会话，需关注敏感时段访问与来源 IP。")
    if not operate_stats["total"]:
        items.append("操作审计接口当前未返回有效数据，审计链路待补查。")
    if not items:
        items.append("本次巡检未发现需要重点升级处理的异常。")
    return items


def build_recommendation_items(context: Dict[str, Any]) -> List[str]:
    items: List[str] = []
    if context["operate_error"]:
        items.append("修复 `/api/v1/audits/operate-logs/` 接口异常，补全操作审计数据。")
    if any(cnt >= 5 for cnt in context["login_stats"]["failure_ips"].values()):
        items.append("对高频失败来源 IP 与账号做封禁、限速或告警联动。")
    if context["asset_stats"]["abnormal"]:
        items.append("复核连通性异常与停用资产，排查凭据、网络或采集任务问题。")
    if any(row["usage"] >= 80 for row in context["command_stats"]["filesystem_rows"]):
        items.append("对磁盘使用率超过 80% 的挂载点做清理、扩容或日志归档。")
    if any(item.get("status") == "error" for item in context["command_evidence"]):
        items.append("排查 access key、账号授权、目标解析和终端建连链路，确保系统命令巡检可稳定执行。")
    if context["session_stats"]["risky_items"]:
        items.append("复查异常来源地址与高风险协议会话，必要时收敛访问策略。")
    if not items:
        items.append("当前建议保持日巡检与异常告警联动，持续观察。")
    return items


def finalize_context(context: Dict[str, Any]) -> Dict[str, Any]:
    login_stats = context["login_stats"]
    session_stats = context["session_stats"]
    operate_stats = context["operate_stats"]
    command_stats = context["command_stats"]
    command_target_error = context.get("command_target_error")

    context["security_risk_items"] = build_security_risk_items(login_stats, session_stats, operate_stats)
    if command_target_error:
        context["security_risk_items"].append(f"系统命令巡检目标解析失败：{command_target_error}")
    if command_stats["anomalies"]:
        context["security_risk_items"].append(f"系统命令巡检异常：{len(command_stats['anomalies'])} 条")
    context["security_risk_summary"] = join_bullets(context["security_risk_items"], "今日未识别出显著安全风险。")
    context["risk_level"] = build_risk_level(context)
    context["executive_summary_items"] = build_executive_summary_items(context)
    context["executive_summary"] = join_bullets(context["executive_summary_items"], "暂无摘要。")
    context["key_findings_items"] = build_key_finding_items(context)
    context["key_findings"] = join_bullets(context["key_findings_items"], "暂无重点发现。")
    context["recommendation_items"] = build_recommendation_items(context)
    context["recommendations"] = join_bullets(context["recommendation_items"], "暂无处置建议。")
    context["anomaly_rows"] = build_anomaly_rows(context)
    context["today_login_logs"] = summarize_login_logs(login_stats, context.get("login_error"))
    context["asset_status"] = summarize_assets(context["asset_stats"], context.get("assets_error"))
    context["active_sessions"] = summarize_active_sessions(session_stats, context.get("sessions_error"))
    context["operate_logs"] = summarize_operate_logs(operate_stats, context.get("operate_error"))
    context["report_notice_items"] = build_report_notice_items(context)
    context["scope_name"] = context["metadata"]["scope_name"]
    context["report_range"] = f"{context['date_from']} 至 {context['date_to']}"
    context["command_summary"] = join_bullets(command_stats["summary_items"], "当前未配置系统命令巡检。")
    context["report_notices"] = join_bullets(context["report_notice_items"], "本次巡检数据采集与渲染链路正常。")
    return context


def with_scope_rows(rows: List[Dict[str, Any]], org_name: str) -> List[Dict[str, Any]]:
    result = []
    for row in rows:
        cloned = dict(row)
        cloned["org_name"] = org_name
        result.append(cloned)
    return result


def build_scope_context(
    date_from: str,
    date_to: str,
    profile_name: str,
    org_scope: Optional[Dict[str, str]],
    include_commands: bool,
) -> Dict[str, Any]:
    generated_at = datetime.now()
    org_id = org_scope["id"] if org_scope else None
    org_name = org_scope["name"] if org_scope else scope_label([])
    login_logs, login_error = safe_fetch(lambda: get_login_logs(date_from, date_to, org_id=org_id), "登录日志接口不可用")
    assets, assets_error = safe_fetch(lambda: get_assets(org_id=org_id), "资产接口不可用")
    active_sessions, sessions_error = safe_fetch(lambda: get_active_sessions(org_id=org_id), "活跃会话接口不可用")
    operate_logs, operate_error = safe_fetch(lambda: get_operate_logs(date_from, date_to, org_id=org_id), "操作审计接口不可用")

    if include_commands:
        command_state = get_command_target_state()
        command_targets = command_state.get("targets", [])
        command_target_error = command_state.get("error")
        command_evidence = collect_command_evidence(command_targets) if command_targets else []
    else:
        command_state = {"targets": [], "error": None, "resolution_mode": "disabled_for_multi_org"}
        command_targets = []
        command_target_error = None
        command_evidence = []

    context: Dict[str, Any] = {
        "report_date": date_to,
        "date_from": date_from,
        "date_to": date_to,
        "generated_at": generated_at,
        "metadata": build_report_metadata(profile_name, date_to, generated_at, org_name),
        "profile_name": profile_name,
        "org_name": org_name,
        "org_id": org_id,
        "login_error": login_error,
        "assets_error": assets_error,
        "sessions_error": sessions_error,
        "operate_error": operate_error,
        "command_target_error": command_target_error,
        "today_login_logs_raw": login_logs,
        "assets_raw": assets,
        "active_sessions_raw": active_sessions,
        "operate_logs_raw": operate_logs,
        "command_targets": command_targets,
        "command_resolution_mode": command_state.get("resolution_mode"),
        "command_evidence": command_evidence,
        "login_stats": build_login_stats(login_logs),
        "asset_stats": build_asset_stats(assets),
        "session_stats": build_session_stats(active_sessions),
        "operate_stats": build_operate_stats(operate_logs),
        "command_stats": build_command_stats(command_evidence),
        "org_contexts": [],
    }
    return finalize_context(context)


def merge_scope_contexts(contexts: List[Dict[str, Any]], profile_name: str, date_from: str, date_to: str) -> Dict[str, Any]:
    generated_at = datetime.now()
    login_stats = {
        "total": 0,
        "success": 0,
        "failure": 0,
        "failure_details": [],
        "failure_users": Counter(),
        "failure_ips": Counter(),
        "all_users": Counter(),
        "all_assets": Counter(),
    }
    asset_stats = {
        "total": 0,
        "enabled": 0,
        "disabled": 0,
        "abnormal": 0,
        "platform_counter": Counter(),
        "rows": [],
        "abnormal_rows": [],
    }
    session_stats = {
        "total": 0,
        "user_counter": Counter(),
        "asset_counter": Counter(),
        "rows": [],
        "risky_items": [],
    }
    operate_stats = {
        "total": 0,
        "user_counter": Counter(),
        "action_counter": Counter(),
        "rows": [],
        "dangerous_rows": [],
    }
    command_evidence: List[Dict[str, Any]] = []
    login_errors: List[str] = []
    asset_errors: List[str] = []
    session_errors: List[str] = []
    operate_errors: List[str] = []

    for context in contexts:
        org_name = context["org_name"]
        login_stats["total"] += context["login_stats"]["total"]
        login_stats["success"] += context["login_stats"]["success"]
        login_stats["failure"] += context["login_stats"]["failure"]
        login_stats["failure_details"].extend(with_scope_rows(context["login_stats"]["failure_details"], org_name))
        login_stats["failure_users"].update(context["login_stats"]["failure_users"])
        login_stats["failure_ips"].update(context["login_stats"]["failure_ips"])
        login_stats["all_users"].update(context["login_stats"]["all_users"])
        login_stats["all_assets"].update(context["login_stats"]["all_assets"])

        asset_stats["total"] += context["asset_stats"]["total"]
        asset_stats["enabled"] += context["asset_stats"]["enabled"]
        asset_stats["disabled"] += context["asset_stats"]["disabled"]
        asset_stats["abnormal"] += context["asset_stats"]["abnormal"]
        asset_stats["platform_counter"].update(context["asset_stats"]["platform_counter"])
        asset_stats["rows"].extend(with_scope_rows(context["asset_stats"]["rows"], org_name))
        asset_stats["abnormal_rows"].extend(with_scope_rows(context["asset_stats"]["abnormal_rows"], org_name))

        session_stats["total"] += context["session_stats"]["total"]
        session_stats["user_counter"].update(context["session_stats"]["user_counter"])
        session_stats["asset_counter"].update(context["session_stats"]["asset_counter"])
        session_stats["rows"].extend(with_scope_rows(context["session_stats"]["rows"], org_name))
        session_stats["risky_items"].extend(f"[{org_name}] {item}" for item in context["session_stats"]["risky_items"])

        operate_stats["total"] += context["operate_stats"]["total"]
        operate_stats["user_counter"].update(context["operate_stats"]["user_counter"])
        operate_stats["action_counter"].update(context["operate_stats"]["action_counter"])
        operate_stats["rows"].extend(with_scope_rows(context["operate_stats"]["rows"], org_name))
        operate_stats["dangerous_rows"].extend(with_scope_rows(context["operate_stats"]["dangerous_rows"], org_name))

        command_evidence.extend(context["command_evidence"])
        if context.get("login_error"):
            login_errors.append(f"[{org_name}] {context['login_error']}")
        if context.get("assets_error"):
            asset_errors.append(f"[{org_name}] {context['assets_error']}")
        if context.get("sessions_error"):
            session_errors.append(f"[{org_name}] {context['sessions_error']}")
        if context.get("operate_error"):
            operate_errors.append(f"[{org_name}] {context['operate_error']}")

    aggregate: Dict[str, Any] = {
        "report_date": date_to,
        "date_from": date_from,
        "date_to": date_to,
        "generated_at": generated_at,
        "metadata": build_report_metadata(profile_name, date_to, generated_at, "全部组织"),
        "profile_name": profile_name,
        "org_name": "全部组织",
        "org_id": None,
        "login_error": "；".join(login_errors),
        "assets_error": "；".join(asset_errors),
        "sessions_error": "；".join(session_errors),
        "operate_error": "；".join(operate_errors),
        "command_target_error": None,
        "today_login_logs_raw": [],
        "assets_raw": [],
        "active_sessions_raw": [],
        "operate_logs_raw": [],
        "command_targets": [],
        "command_resolution_mode": "disabled_for_multi_org",
        "command_evidence": command_evidence,
        "login_stats": login_stats,
        "asset_stats": asset_stats,
        "session_stats": session_stats,
        "operate_stats": operate_stats,
        "command_stats": build_command_stats(command_evidence),
        "org_contexts": contexts,
    }
    return finalize_context(aggregate)


def build_data_bundle(
    report_date: str,
    profile_name: str,
    org_name: Optional[str] = None,
    all_orgs: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_commands: Optional[bool] = None,
) -> Dict[str, Any]:
    from_date = date_from or report_date
    to_date = date_to or report_date
    scopes = resolve_org_scopes(org_name=org_name, all_orgs=all_orgs)
    if len(scopes) <= 1:
        scope = scopes[0] if scopes else None
        include_scope_commands = include_commands if include_commands is not None else (org_name is None and not all_orgs)
        return build_scope_context(
            date_from=from_date,
            date_to=to_date,
            profile_name=profile_name,
            org_scope=scope,
            include_commands=include_scope_commands,
        )

    contexts = [
        build_scope_context(
            date_from=from_date,
            date_to=to_date,
            profile_name=profile_name,
            org_scope=scope,
            include_commands=False,
        )
        for scope in scopes
    ]
    return merge_scope_contexts(contexts, profile_name=profile_name, date_from=from_date, date_to=to_date)


def resolve_legacy_db_config(
    snapshots: List[Dict[str, Any]],
    remote_config_path: str = DEFAULT_REMOTE_CONFIG_FILE,
) -> Dict[str, Any]:
    remote_text = ""
    for snapshot in snapshots:
        remote_text = str(snapshot.get("remote_config_text") or "").strip()
        if remote_text:
            break
    if remote_text:
        remote_values = parse_key_value_text(remote_text)
        mapped = map_remote_db_config(remote_values)
        if mapped:
            mapped["source"] = "remote_config"
            mapped["source_path"] = remote_config_path
            return mapped

    local_override = resolve_local_db_overrides()
    if local_override:
        local_override["source"] = "local_override"
        local_override["source_path"] = "profile env"
        return local_override

    if remote_text:
        raise JumpServerApiError(f"{remote_config_path} 中缺少完整的数据库连接信息。")
    raise JumpServerApiError(f"未能从 JumpServer 节点读取数据库配置文件：{remote_config_path}")


def collect_legacy_system_snapshots() -> Tuple[List[Dict[str, Any]], Optional[str], List[Dict[str, Any]]]:
    state = get_legacy_system_target_state()
    targets = state.get("targets", [])
    if state.get("error"):
        return [], str(state["error"]), []
    evidence = collect_command_evidence(targets) if targets else []
    snapshots = [parse_system_target_snapshot(target, evidence_item) for target, evidence_item in zip(targets, evidence)]
    errors = [item.get("error") for item in evidence if item.get("status") != "ok" and item.get("error")]
    return snapshots, "；".join(str(item) for item in errors if item), evidence


def collect_legacy_db_metrics(
    db_config: Dict[str, Any],
    report_date: str,
    org_id: Optional[str],
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    range_end = date_to or report_date
    end_exclusive = next_day_start(range_end)
    explicit_start = at_day_start(date_from) if date_from else ""
    week_start = explicit_start or days_before_start(report_date, 7)
    month_start = explicit_start or days_before_start(report_date, 30)
    quarter_start = explicit_start or days_before_start(report_date, 90)
    common_params = {
        "db_name": db_config["name"],
        "from_date": week_start,
        "from_30": month_start,
        "from_90": quarter_start,
        "to_date_exclusive": end_exclusive,
    }
    connection = open_db_connection(db_config)
    try:
        table_sizes = execute_sql_rows(db_config, "table_sizes.sql", common_params, connection=connection)
        protocol_distribution = execute_sql_rows(db_config, "protocol_distribution.sql", common_params, org_id=org_id, connection=connection)
        weekly_user_rows = execute_sql_rows(db_config, "weekly_user_logins.sql", common_params, org_id=org_id, connection=connection)
        weekly_asset_rows = execute_sql_rows(db_config, "weekly_asset_logins.sql", common_params, org_id=org_id, connection=connection)
        active_users = execute_sql_rows(
            db_config,
            "active_users_top5.sql",
            {"from_date": quarter_start, "to_date_exclusive": end_exclusive},
            org_id=org_id,
            connection=connection,
        )
        active_assets = execute_sql_rows(
            db_config,
            "active_assets_top5.sql",
            {"from_date": quarter_start, "to_date_exclusive": end_exclusive},
            org_id=org_id,
            connection=connection,
        )
        duration_stats = execute_sql_row(
            db_config,
            "session_duration_stats.sql",
            {"from_date": quarter_start, "to_date_exclusive": end_exclusive},
            org_id=org_id,
            connection=connection,
        )
        audit_counts = execute_sql_row(db_config, "audit_counts.sql", common_params, org_id=org_id, connection=connection)
        rds_status = execute_sql_row(db_config, "rds_status.sql", {}, org_id=None, connection=connection)
    finally:
        connection.close()

    return {
        "db_config": {
            "engine": db_config["engine"],
            "host": db_config["host"],
            "port": str(db_config["port"]),
            "name": db_config["name"],
            "source": db_config.get("source", "-"),
            "source_path": db_config.get("source_path", "-"),
        },
        "rds_status_rows": [{
            "hostname": humanize_value(rds_status.get("hostname"), default="-"),
            "version": humanize_value(rds_status.get("version"), default="-"),
            "version_comment": humanize_value(rds_status.get("version_comment"), default="-"),
            "port": humanize_value(rds_status.get("port"), default="-"),
            "checked_at": humanize_value(rds_status.get("checked_at"), default="-"),
        }] if rds_status else [],
        "table_size_rows": [
            {
                "table_name": humanize_value(get_dict_value(row, "table_name"), default="-"),
                "size_mb": humanize_value(get_dict_value(row, "size_mb"), default="0"),
                "table_rows": humanize_value(get_dict_value(row, "table_rows"), default="0"),
            }
            for row in table_sizes
        ],
        "protocol_distribution": [
            {"name": humanize_value(get_dict_value(row, "name"), default="-"), "value": int(get_dict_value(row, "value") or 0)}
            for row in protocol_distribution
        ],
        "weekly_user_trend": build_date_series(weekly_user_rows, week_start.split()[0], range_end),
        "weekly_asset_trend": build_date_series(weekly_asset_rows, week_start.split()[0], range_end),
        "active_users_top5": [
            {"name": humanize_value(get_dict_value(row, "name"), default="-"), "value": int(get_dict_value(row, "value") or 0)}
            for row in active_users
        ],
        "active_assets_top5": [
            {"name": humanize_value(get_dict_value(row, "name"), default="-"), "value": int(get_dict_value(row, "value") or 0)}
            for row in active_assets
        ],
        "audit_counts": {
            "login_users_90d": int(audit_counts.get("login_users_90d") or 0),
            "asset_logins_90d": int(audit_counts.get("asset_logins_90d") or 0),
            "ftp_uploads_90d": int(audit_counts.get("ftp_uploads_90d") or 0),
            "login_users_30d": int(audit_counts.get("login_users_30d") or 0),
            "asset_logins_30d": int(audit_counts.get("asset_logins_30d") or 0),
            "ftp_uploads_30d": int(audit_counts.get("ftp_uploads_30d") or 0),
            "command_records_90d": int(audit_counts.get("command_records_90d") or 0),
            "dangerous_command_records_90d": int(audit_counts.get("dangerous_command_records_90d") or 0),
            "ticket_requests_90d": int(audit_counts.get("ticket_requests_90d") or 0),
            "max_daily_login_count": int(audit_counts.get("max_daily_login_count") or 0),
            "max_daily_asset_access_count": int(audit_counts.get("max_daily_asset_access_count") or 0),
            "max_session_seconds_90d": int(duration_stats.get("max_seconds") or 0),
            "avg_session_seconds_90d": int(duration_stats.get("avg_seconds") or 0),
        },
    }


def build_legacy_collection_context(
    report_date: str,
    profile_name: str,
    org_name: Optional[str] = None,
    all_orgs: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    from_date = date_from or report_date
    to_date = date_to or report_date
    scopes = resolve_org_scopes(org_name=org_name, all_orgs=all_orgs)
    bundle = build_data_bundle(
        report_date,
        profile_name,
        org_name=org_name,
        all_orgs=all_orgs,
        date_from=from_date,
        date_to=to_date,
        include_commands=False,
    )
    org_id = scopes[0]["id"] if len(scopes) == 1 else None
    users, users_error = safe_fetch(lambda: get_users(org_id=org_id), "用户接口不可用")
    snapshots, system_error, evidence = collect_legacy_system_snapshots()
    db_error = None
    db_metrics: Dict[str, Any] = {
        "db_config": {},
        "rds_status_rows": [],
        "table_size_rows": [],
        "protocol_distribution": [],
        "weekly_user_trend": [],
        "weekly_asset_trend": [],
        "active_users_top5": [],
        "active_assets_top5": [],
        "audit_counts": {},
    }

    try:
        db_config = resolve_legacy_db_config(snapshots)
        engine = str(db_config.get("engine") or "").strip().lower()
        if engine not in ("mysql", "mariadb"):
            raise JumpServerApiError(f"当前 legacy 报告仅支持 MySQL/MariaDB，检测到 DB_ENGINE={engine or '-'}")
        db_metrics = collect_legacy_db_metrics(db_config, report_date, org_id=org_id, date_from=from_date, date_to=to_date)
    except Exception as exc:  # noqa: BLE001
        db_error = str(exc)

    org_count = len(scopes) if scopes else 1
    asset_type_top3 = [
        {"name": name, "value": count}
        for name, count in bundle["asset_stats"]["platform_counter"].most_common(3)
    ]
    audit_counts = db_metrics.get("audit_counts", {})
    overview_targets = snapshots or [{
        "name": row["name"],
        "platform": row["platform"],
        "ip": row["ip"],
        "port": row["port"],
        "username": row["username"],
        "enabled": row["enabled"],
        "status": row["status"],
    } for row in bundle["asset_stats"]["rows"][:10]]
    legacy_version = next(
        (
            str(item.get("system_info", {}).get("app_version") or "").strip()
            for item in snapshots
            if str(item.get("system_info", {}).get("app_version") or "").strip() not in ("", "-", "unknown", MISSING_COMMAND_OUTPUT)
        ),
        "",
    )

    context = {
        "report_date": report_date,
        "date_from": from_date,
        "date_to": to_date,
        "profile_name": profile_name,
        "metadata": bundle["metadata"],
        "bundle": bundle,
        "legacy_version": legacy_version or bundle["metadata"]["version"],
        "scope_name": bundle["metadata"]["scope_name"],
        "overview_targets": overview_targets,
        "anomaly_rows": bundle["anomaly_rows"],
        "system_snapshots": snapshots,
        "system_command_evidence": evidence,
        "system_error": system_error,
        "users_error": users_error,
        "db_error": db_error,
        "db_metrics": db_metrics,
        "operations_summary": {
            "org_count": org_count,
            "user_count": len(users),
            "asset_count": bundle["asset_stats"]["total"],
            "asset_type_top3": asset_type_top3,
            "online_sessions": bundle["session_stats"]["total"],
            "max_daily_login_count": audit_counts.get("max_daily_login_count", 0),
            "max_daily_asset_access_count": audit_counts.get("max_daily_asset_access_count", 0),
            "login_users_90d": audit_counts.get("login_users_90d", 0),
            "asset_logins_90d": audit_counts.get("asset_logins_90d", 0),
            "ftp_uploads_90d": audit_counts.get("ftp_uploads_90d", 0),
            "login_users_30d": audit_counts.get("login_users_30d", 0),
            "asset_logins_30d": audit_counts.get("asset_logins_30d", 0),
            "ftp_uploads_30d": audit_counts.get("ftp_uploads_30d", 0),
            "command_records_90d": audit_counts.get("command_records_90d", 0),
            "dangerous_command_records_90d": audit_counts.get("dangerous_command_records_90d", 0),
            "ticket_requests_90d": audit_counts.get("ticket_requests_90d", 0),
            "max_session_seconds_90d": audit_counts.get("max_session_seconds_90d", 0),
            "avg_session_seconds_90d": audit_counts.get("avg_session_seconds_90d", 0),
        },
        "operate_stats": bundle["operate_stats"],
        "operate_error": bundle.get("operate_error"),
    }
    return context


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


def answer_natural_language_block(instruction: str, context: Dict[str, Any]) -> str:
    text = instruction.strip()
    if any(keyword in text for keyword in ("巡检概览", "管理摘要", "总体态势", "概览")):
        return context["executive_summary"]
    if any(keyword in text for keyword in ("系统命令", "命令巡检", "命令证据", "主机巡检")):
        return context["command_summary"]
    if any(keyword in text for keyword in ("登录失败", "登录异常", "爆破风险", "登录记录")):
        return context["today_login_logs"]
    if any(keyword in text for keyword in ("资产状态", "资产总数", "禁用资产", "异常资产")):
        return context["asset_status"]
    if any(keyword in text for keyword in ("在线会话", "活跃会话", "当前会话")):
        return context["active_sessions"]
    if any(keyword in text for keyword in ("操作审计", "审计日志", "危险操作")):
        return context["operate_logs"]
    if any(keyword in text for keyword in ("关键发现", "重点发现")):
        return context["key_findings"]
    if any(keyword in text for keyword in ("风险", "安全风险", "风险统计")):
        return context["security_risk_summary"]
    if any(keyword in text for keyword in ("处置建议", "整改建议", "建议")):
        return context["recommendations"]
    if any(keyword in text for keyword in ("巡检说明", "采集说明", "说明", "注意事项")):
        return context["report_notices"]
    return build_default_report(context)


def render_natural_language_template(template_text: str, context: Dict[str, Any]) -> str:
    sections = split_markdown_sections(template_text)
    if not sections:
        return build_default_report(context)
    output: List[str] = []
    for section in sections:
        output.append(f"## {section['title']}")
        output.append(answer_natural_language_block(section["body"], context))
        output.append("")
    return "\n".join(output).strip() + "\n"


def build_default_report(context: Dict[str, Any]) -> str:
    sections = (
        f"# JumpServer 巡检报告\n\n"
        f"**报告日期：** {context['report_date']}\n"
        f"**统计区间：** {context['report_range']}\n"
        f"**环境 Profile：** {context['metadata']['profile_name']}\n\n"
        f"**组织范围：** {context['metadata']['scope_name']}\n\n"
        f"**风险等级：** {context['risk_level']}\n\n"
        f"## 一、巡检概览\n{context['executive_summary']}\n\n"
        f"## 二、系统命令巡检\n{context['command_summary']}\n\n"
        f"## 三、登录情况\n{context['today_login_logs']}\n\n"
        f"## 四、活跃会话\n{context['active_sessions']}\n\n"
        f"## 五、资产状态\n{context['asset_status']}\n\n"
        f"## 六、操作审计\n{context['operate_logs']}\n\n"
        f"## 七、安全风险摘要\n{context['security_risk_summary']}\n\n"
        f"## 八、关键发现\n{context['key_findings']}\n\n"
        f"## 九、处置建议\n{context['recommendations']}\n\n"
        f"## 十、巡检说明\n{context['report_notices']}\n"
    )
    if context["org_contexts"]:
        org_chunks = []
        for org_context in context["org_contexts"]:
            org_chunks.append(
                f"### {org_context['org_name']}\n"
                f"- 登录失败：{org_context['login_stats']['failure']}\n"
                f"- 资产总数：{org_context['asset_stats']['total']}\n"
                f"- 活跃会话：{org_context['session_stats']['total']}\n"
                f"- 风险等级：{org_context['risk_level']}"
            )
        sections += "\n\n## 十一、分组织概览\n" + "\n\n".join(org_chunks) + "\n"
    return sections


def generate_markdown_report(template_text: str, report_date: str, profile_name: str) -> str:
    context = build_data_bundle(report_date, profile_name)
    mode = detect_template_mode(template_text)
    if mode == "placeholder":
        return render_placeholder_template(template_text, context)
    return render_natural_language_template(template_text, context)


def normalize_bullets(text: str) -> List[str]:
    items = []
    for line in text.splitlines():
        clean = line.strip()
        if clean.startswith("- "):
            items.append(clean[2:].strip())
    return items


def render_html_table(headers: List[Tuple[str, str]], rows: List[Dict[str, Any]], empty_text: str = "无内容") -> str:
    head = "".join(f"<th>{escape(label)}</th>" for label, _ in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{escape(str(row.get(key, '-')))}</td>" for _, key in headers)
        body_rows.append(f"<tr>{cells}</tr>")
    if not body_rows:
        body_rows.append(f'<tr><td colspan="{len(headers)}" class="empty">{escape(empty_text)}</td></tr>')
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def render_html_list(items: List[str], empty_text: str = "无内容") -> str:
    normalized = [item.strip() for item in items if item and item.strip()]
    if not normalized:
        normalized = [empty_text]
    return "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in normalized) + "</ul>"


def render_html_table_block(headers: List[Tuple[str, str]], rows: List[Dict[str, Any]], empty_text: str = "无内容") -> str:
    return f'<div class="table-shell">{render_html_table(headers, rows, empty_text)}</div>'


def render_notice_block(items: List[str]) -> str:
    normalized = [item.strip() for item in items if item and item.strip()]
    if not normalized:
        return ""
    return '<div class="notice-block">' + "".join(f"<p>{escape(item)}</p>" for item in normalized) + "</div>"


def render_command_cards(rows: List[Dict[str, str]], empty_text: str = "未配置系统命令巡检。") -> str:
    if not rows:
        return f'<div class="empty-panel">{escape(empty_text)}</div>'
    cards = []
    for row in rows:
        cards.append(
            "<article class=\"command-card\">"
            f"<div class=\"command-target\">{escape(row['target_name'])}</div>"
            f"<div class=\"command-line\">{escape(row['command'])}</div>"
            f"<pre>{escape(row['output'])}</pre>"
            "</article>"
        )
    return "".join(cards)


def render_metric_cards(cards: List[Tuple[str, Any]]) -> str:
    return "".join(
        f'<div class="metric-card"><div class="metric-label">{escape(label)}</div><div class="metric-value">{escape(str(value))}</div></div>'
        for label, value in cards
    )


def render_anchor_nav(items: List[Tuple[str, str]]) -> str:
    normalized = [(anchor.strip(), label.strip()) for anchor, label in items if anchor and label]
    if not normalized:
        return ""
    links = "".join(
        f'<a class="anchor-link" href="#{escape(anchor)}">{escape(label)}</a>'
        for anchor, label in normalized
    )
    return f'<nav class="anchor-nav" aria-label="报告导航">{links}</nav>'


def render_summary_callouts(items: List[Tuple[str, str]]) -> str:
    normalized = [(label.strip(), copy.strip()) for label, copy in items if label and copy]
    if not normalized:
        return ""
    cards = []
    for label, copy in normalized:
        cards.append(
            '<article class="summary-card">'
            f'<div class="summary-label">{escape(label)}</div>'
            f'<div class="summary-copy">{escape(copy)}</div>'
            '</article>'
        )
    return '<div class="summary-board">' + "".join(cards) + "</div>"


def render_risk_badge(level: str) -> str:
    normalized = str(level or "").strip()
    class_name = {
        "高": "risk-high",
        "中": "risk-medium",
        "低": "risk-low",
    }.get(normalized, "risk-low")
    return (
        f'<span class="risk-badge {class_name}">'
        '<span class="risk-dot"></span>'
        f'风险等级 {escape(normalized or "低")}'
        "</span>"
    )


def make_field_rows(pairs: List[Tuple[str, Any]]) -> List[Dict[str, str]]:
    return [{"field": label, "value": humanize_value(value)} for label, value in pairs]


def render_bar_list(items: List[Dict[str, Any]], label_key: str = "name", value_key: str = "value", empty_text: str = "无数据") -> str:
    if not items:
        return f'<div class="empty-panel">{escape(empty_text)}</div>'
    max_value = max(int(item.get(value_key) or 0) for item in items) or 1
    rows = []
    for item in items:
        label = humanize_value(item.get(label_key), default="-")
        value = int(item.get(value_key) or 0)
        width = max(int(value / max_value * 100), 1) if value else 0
        rows.append(
            "<div class=\"bar-row\">"
            f"<div class=\"bar-label\">{escape(label)}</div>"
            f"<div class=\"bar-track\"><span style=\"width:{width}%\"></span></div>"
            f"<div class=\"bar-value\">{value}</div>"
            "</div>"
        )
    return "".join(rows)


def render_line_series(items: List[Dict[str, Any]], empty_text: str = "无数据") -> str:
    if not items:
        return f'<div class="empty-panel">{escape(empty_text)}</div>'
    max_value = max(int(item.get("value") or 0) for item in items) or 1
    rows = []
    for item in items:
        day = humanize_value(item.get("day"), default="-")
        value = int(item.get("value") or 0)
        width = max(int(value / max_value * 100), 1) if value else 0
        rows.append(
            "<div class=\"line-row\">"
            f"<div class=\"line-label\">{escape(day)}</div>"
            f"<div class=\"line-track\"><span style=\"width:{width}%\"></span></div>"
            f"<div class=\"line-value\">{value}</div>"
            "</div>"
        )
    return "".join(rows)


def render_legacy_html_report(
    report_date: str,
    profile_name: str,
    org_name: Optional[str] = None,
    all_orgs: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> str:
    context = build_legacy_collection_context(
        report_date,
        profile_name,
        org_name=org_name,
        all_orgs=all_orgs,
        date_from=date_from,
        date_to=date_to,
    )
    metadata = context["metadata"]
    bundle = context["bundle"]
    report_version = context.get("legacy_version") or metadata["version"]
    operations = context["operations_summary"]
    db_metrics = context["db_metrics"]
    snapshots = context["system_snapshots"]
    risk_level = bundle["risk_level"]
    asset_type_text = "、".join(f"{item['name']}（{item['value']}）" for item in operations["asset_type_top3"]) or "无"
    explicit_range = context["date_from"] != context["date_to"]
    period_short_label = "查询区间" if explicit_range else "近一月"
    period_long_label = "查询区间" if explicit_range else "近三月"
    trend_label = "按时间区间" if explicit_range else "按周"
    dispatch_message = {
        "高": "本次完整版巡检已识别出高优先级风险，建议立即复核节点状态、异常来源与高危操作链路。",
        "中": "平台存在需要持续跟进的异常项，建议按登录、节点健康和数据库指标逐项收敛。",
        "低": "整体运行态较为平稳，建议保持日报归档、抽样复核与告警联动。",
    }.get(risk_level, "请结合本次巡检结果继续完成后续复核与处置。")
    coverage_summary = (
        f"本次正式巡检覆盖 {escape(metadata['scope_name'])}，统计区间 {escape(context['date_from'])} 至 {escape(context['date_to'])}。"
        f"已纳管资产 {operations['asset_count']} 台，在线会话 {operations['online_sessions']} 条，"
        f"JumpServer 版本 {escape(report_version)}，节点角色覆盖 {escape('、'.join(sorted({str(item.get('role') or '-') for item in snapshots}) or ['jumpserver']))}。"
    )

    operation_rows = [
        {"metric": "软件版本", "value": report_version},
        {"metric": f"{period_long_label}登录用户数", "value": operations["login_users_90d"]},
        {"metric": f"{period_long_label}登录资产数", "value": operations["asset_logins_90d"]},
        {"metric": f"{period_long_label}文件上传数", "value": operations["ftp_uploads_90d"]},
        {"metric": f"{period_short_label}登录用户数", "value": operations["login_users_30d"]},
        {"metric": f"{period_short_label}登录资产数", "value": operations["asset_logins_30d"]},
        {"metric": f"{period_short_label}文件上传次数", "value": operations["ftp_uploads_30d"]},
        {"metric": f"{period_long_label}命令记录数", "value": operations["command_records_90d"]},
        {"metric": f"{period_long_label}高危命令记录数", "value": operations["dangerous_command_records_90d"]},
        {"metric": f"{period_long_label}最大会话时长", "value": format_seconds(operations["max_session_seconds_90d"])},
        {"metric": f"{period_long_label}平均会话时长", "value": format_seconds(operations["avg_session_seconds_90d"])},
        {"metric": f"{period_long_label}工单申请数", "value": operations["ticket_requests_90d"]},
    ]
    overview_cards = [
        ("风险等级", risk_level),
        ("纳管资产", operations["asset_count"]),
        ("在线会话", operations["online_sessions"]),
        ("组织数", operations["org_count"]),
        ("用户数", operations["user_count"]),
        ("巡检节点", len(context["overview_targets"])),
        ("最大单日登录", operations["max_daily_login_count"]),
        ("高危命令", operations["dangerous_command_records_90d"]),
    ]

    notice_items = list(bundle.get("report_notice_items", []))
    if context.get("system_error"):
        notice_items.append(f"系统命令采集异常：{context['system_error']}")
    if context.get("users_error"):
        notice_items.append(f"用户接口异常：{context['users_error']}")
    if context.get("db_error"):
        notice_items.append(f"数据库统计采集失败：{context['db_error']}")
    section_nav = [
        ("overview", "总览与态势"),
        ("ops", "数据库与运营"),
        ("nodes", "节点巡检"),
        ("audit", "审计与建议"),
    ]
    summary_callouts = [
        ("建议先看", dispatch_message),
        ("首个异常", context["anomaly_rows"][0]["description"] if context["anomaly_rows"] else "当前未发现需要升级处理的异常。"),
        ("建议动作", bundle["recommendation_items"][0] if bundle["recommendation_items"] else "当前建议保持日巡检与异常联动。"),
    ]

    system_blocks = []
    for index, snapshot in enumerate(snapshots, start=1):
        component_status_block = (
            render_html_table_block(
                [("组件", "name"), ("服务", "service"), ("状态", "status"), ("端口", "ports"), ("镜像", "image")],
                snapshot["component_status_structured_rows"],
                "未采集到 jmsctl 状态。",
            )
            if snapshot["component_status_structured_rows"]
            else render_html_table_block([("状态明细", "item")], snapshot["component_status_rows"], "未采集到 jmsctl 状态。")
        )
        component_rows_block = (
            ""
            if snapshot["component_status_structured_rows"]
            else f"""
              <section class="subpanel">
                <h3>JumpServer 服务组件状态</h3>
                <p class="subpanel-summary">当未获取到结构化 `jmsctl` 结果时，回退展示容器状态概览。</p>
                {render_html_table_block([("组件", "name"), ("状态", "status"), ("端口", "ports")], snapshot["component_rows"], "未采集到容器状态。")}
              </section>
            """
        )
        system_blocks.append(
            f"""
            <article class="panel panel-strong span-12 legacy-node-card">
              <div class="panel-body">
                <div class="node-header">
                  <div>
                    <p class="panel-kicker">Node {index:02d}</p>
                    <h2>{escape(snapshot['name'])} 节点巡检</h2>
                    <p class="panel-summary">覆盖主机基础信息、组件状态、磁盘、容器内存、高内存进程和大文件检查，适合正式巡检归档。</p>
                  </div>
                  <div class="runtime-list">
                    <span class="runtime-pill">角色：{escape(humanize_value(snapshot.get('role'), default='-'))}</span>
                    <span class="runtime-pill">主机名：{escape(humanize_value(snapshot['system_info']['hostname'], default='-'))}</span>
                    <span class="runtime-pill">系统：{escape(humanize_value(snapshot['system_info']['os'], default='-'))}</span>
                    <span class="runtime-pill">版本：{escape(humanize_value(snapshot['system_info']['app_version'], default='-'))}</span>
                  </div>
                </div>
                <div class="legacy-grid">
                  <section class="subpanel">
                  <h3>系统信息</h3>
                  <p class="subpanel-summary">节点当前基础信息、内核版本与运行时长。</p>
                  {render_html_table_block([("字段", "field"), ("值", "value")], make_field_rows([
                    ("主机名", snapshot["system_info"]["hostname"]),
                    ("系统版本", snapshot["system_info"]["os"]),
                    ("JumpServer 版本", snapshot["system_info"]["app_version"]),
                    ("内核版本", snapshot["system_info"]["kernel"]),
                    ("CPU 架构", snapshot["system_info"]["arch"]),
                    ("当前时间", snapshot["system_info"]["current_time"]),
                    ("运行时长", snapshot["system_info"]["uptime"]),
                  ]))}
                  </section>
                  <section class="subpanel">
                  <h3>CPU 信息</h3>
                  <p class="subpanel-summary">用于判断节点核数、架构和 CPU 型号是否符合部署预期。</p>
                  {render_html_table_block([("字段", "field"), ("值", "value")], make_field_rows([
                    ("物理 CPU 个数", snapshot["cpu_info"]["sockets"]),
                    ("每物理 CPU 核数", snapshot["cpu_info"]["cores_per_socket"]),
                    ("逻辑 CPU 核数", snapshot["cpu_info"]["logical_cpus"]),
                    ("CPU 型号", snapshot["cpu_info"]["model"]),
                  ]))}
                  </section>
                  <section class="subpanel">
                  <h3>内存信息</h3>
                  <p class="subpanel-summary">观察物理内存、空闲量与交换空间使用情况。</p>
                  {render_html_table_block([("字段", "field"), ("值", "value")], make_field_rows([
                    ("总量", snapshot["memory_info"]["total"]),
                    ("已用", snapshot["memory_info"]["used"]),
                    ("空闲", snapshot["memory_info"]["free"]),
                    ("SWAP", snapshot["memory_info"]["swap"]),
                  ]))}
                  </section>
                  <section class="subpanel">
                  <h3>其他系统参数</h3>
                  <p class="subpanel-summary">补充展示负载、防火墙与僵尸进程等系统态势。</p>
                  {render_html_table_block([("字段", "field"), ("值", "value")], make_field_rows([
                    ("防火墙", snapshot["system_params"]["firewall"]),
                    ("平均负载", snapshot["system_params"]["loadavg"]),
                    ("CPU 数量", snapshot["cpu_count"]),
                    ("僵尸进程", snapshot["system_params"]["zombie_processes"]),
                  ]))}
                  </section>
                  <section class="subpanel full">
                    <h3>jmsctl 组件状态</h3>
                    <p class="subpanel-summary">优先展示结构化的服务状态、端口与镜像信息。</p>
                    {component_status_block}
                  </section>
                  {component_rows_block}
                  <section class="subpanel">
                    <h3>防火墙策略</h3>
                    <p class="subpanel-summary">记录节点当前防火墙配置，便于后续变更对比。</p>
                    {render_html_table_block([("策略明细", "item")], parse_key_value_lines(snapshot["system_params"]["firewall_rules"]), "未采集到防火墙策略。")}
                  </section>
                  <section class="subpanel">
                    <h3>僵尸进程明细</h3>
                    <p class="subpanel-summary">用于快速识别异常退出后未正确回收的进程。</p>
                    {render_html_table_block([("进程明细", "item")], parse_key_value_lines(snapshot["system_params"]["zombie_detail"]), "未发现僵尸进程明细。")}
                  </section>
                  <section class="subpanel">
                    <h3>容器内存占用</h3>
                    <p class="subpanel-summary">聚焦核心组件内存使用情况，适合做容量趋势对照。</p>
                    {render_html_table_block([("组件", "name"), ("内存占用", "usage")], snapshot["container_memory_rows"], "未采集到容器内存占用。")}
                  </section>
                  <section class="subpanel full">
                    <h3>磁盘信息</h3>
                    <p class="subpanel-summary">展示各文件系统容量与使用率，优先关注高水位挂载点。</p>
                    {render_html_table_block([("节点", "target_name"), ("文件系统", "filesystem"), ("类型", "type"), ("总量", "size"), ("已用", "used"), ("可用", "avail"), ("使用率", "usage"), ("挂载点", "mount")], snapshot["disk_rows"], "未采集到磁盘信息。")}
                  </section>
                  <section class="subpanel full">
                    <h3>高内存进程 Top 10</h3>
                    <p class="subpanel-summary">辅助定位内存热点进程与潜在异常占用。</p>
                    {render_html_table_block([("用户", "user"), ("PID", "pid"), ("%CPU", "cpu"), ("%MEM", "mem"), ("RSS", "rss"), ("命令", "command")], snapshot["top_memory_rows"], "未采集到高内存进程列表。")}
                  </section>
                  <section class="subpanel full">
                    <h3>大文件巡检</h3>
                    <p class="subpanel-summary">用于排查日志、缓存或临时文件异常膨胀。</p>
                    {render_html_table_block([("大小", "size"), ("路径", "path")], snapshot["large_file_rows"], "未采集到大文件列表。")}
                  </section>
                </div>
              </div>
            </article>
            """
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(metadata['title'])}</title>
  <style>
    :root {{
      --accent: {escape(metadata['theme_color'])};
      --accent-bright: #d9f0e8;
      --bg: linear-gradient(180deg, #e6eeea 0%, #eef5f2 42%, #f5f8f7 100%);
      --paper: rgba(255, 255, 255, 0.92);
      --paper-strong: rgba(248, 251, 250, 0.98);
      --paper-soft: rgba(240, 246, 243, 0.88);
      --ink: #11211c;
      --ink-soft: #50655d;
      --ink-faint: #74887f;
      --line: rgba(17, 33, 28, 0.1);
      --line-strong: rgba(17, 33, 28, 0.18);
      --hero-bg: linear-gradient(135deg, #14372d 0%, #1c4c3f 48%, #2a6757 100%);
      --hero-ink: #f4faf7;
      --shadow: 0 28px 72px rgba(15, 38, 31, 0.12);
      --warn: #ab7437;
      --danger: #b44d3d;
    }}
    * {{
      box-sizing: border-box;
    }}
    html, body {{
      margin: 0;
      padding: 0;
      font-family: "IBM Plex Sans", "PingFang SC", "Microsoft YaHei", sans-serif;
      background:
        radial-gradient(circle at 0 0, rgba(75, 145, 125, 0.12), transparent 28%),
        radial-gradient(circle at 100% 12%, rgba(75, 145, 125, 0.08), transparent 24%),
        var(--bg);
      color: var(--ink);
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    body {{
      min-height: 100vh;
      position: relative;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      opacity: 0.28;
      background:
        linear-gradient(90deg, rgba(255,255,255,0.14) 0, rgba(255,255,255,0.14) 1px, transparent 1px, transparent 100%),
        linear-gradient(rgba(255,255,255,0.14) 0, rgba(255,255,255,0.14) 1px, transparent 1px, transparent 100%);
      background-size: 32px 32px;
      mask-image: linear-gradient(180deg, rgba(0,0,0,0.48), transparent 72%);
    }}
    @keyframes rise-in {{
      from {{
        opacity: 0;
        transform: translateY(18px);
      }}
      to {{
        opacity: 1;
        transform: translateY(0);
      }}
    }}
    .report-shell {{
      width: min(100%, 1480px);
      margin: 0 auto;
      padding: 24px 14px 48px;
    }}
    .report-frame {{
      position: relative;
      overflow: hidden;
      border-radius: 34px;
      border: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(248, 251, 250, 0.98), rgba(244, 248, 246, 0.98));
      box-shadow: var(--shadow);
    }}
    .report-frame::before {{
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      background:
        radial-gradient(circle at 0 0, rgba(255,255,255,0.72), transparent 34%),
        radial-gradient(circle at 100% 24%, rgba(75, 145, 125, 0.08), transparent 24%),
        linear-gradient(180deg, transparent 0%, rgba(255,255,255,0.22) 100%);
    }}
    .top-ribbon {{
      position: relative;
      z-index: 1;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 10px 18px;
      padding: 18px 24px 0;
      color: var(--ink-faint);
      font-size: 11px;
      letter-spacing: 0.18em;
      text-transform: uppercase;
    }}
    .hero {{
      position: relative;
      z-index: 1;
      padding: 18px 24px 10px;
    }}
    .hero-grid {{
      display: grid;
      gap: 18px;
    }}
    .hero-intro {{
      position: relative;
      overflow: hidden;
      padding: 30px 24px;
      border-radius: 30px;
      background: var(--hero-bg);
      color: var(--hero-ink);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.08);
      animation: rise-in 760ms cubic-bezier(0.22, 1, 0.36, 1) both;
    }}
    .hero-intro::before {{
      content: "";
      position: absolute;
      width: 420px;
      height: 420px;
      right: -160px;
      top: -220px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(255,255,255,0.16), transparent 68%);
    }}
    .hero-intro::after {{
      content: "INSPECTION";
      position: absolute;
      right: 26px;
      bottom: 16px;
      color: rgba(255,255,255,0.08);
      font-size: clamp(34px, 7vw, 104px);
      font-weight: 700;
      letter-spacing: 0.08em;
      line-height: 1;
    }}
    .eyebrow {{
      margin: 0;
      color: var(--accent-bright);
      font-size: 12px;
      letter-spacing: 0.24em;
      text-transform: uppercase;
    }}
    .hero h1 {{
      position: relative;
      z-index: 1;
      margin: 18px 0 18px;
      max-width: 920px;
      font-family: "Iowan Old Style", "Georgia", "Songti SC", serif;
      font-size: clamp(42px, 7vw, 80px);
      line-height: 0.95;
      letter-spacing: -0.04em;
    }}
    .hero-summary {{
      position: relative;
      z-index: 1;
      margin: 0;
      max-width: 760px;
      color: rgba(244, 250, 247, 0.88);
      font-size: 16px;
      line-height: 1.86;
    }}
    .hero-lead {{
      position: relative;
      z-index: 1;
      max-width: 820px;
      margin: 18px 0 0;
      color: rgba(244, 250, 247, 0.78);
      font-size: 13px;
      line-height: 1.85;
    }}
    .hero-foot,
    .runtime-list,
    .signal-list {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
    }}
    .anchor-nav {{
      position: relative;
      z-index: 1;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
    }}
    .anchor-link {{
      display: inline-flex;
      align-items: center;
      min-height: 38px;
      padding: 8px 14px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.14);
      background: rgba(255,255,255,0.08);
      color: var(--hero-ink);
      font-size: 12px;
      line-height: 1.5;
      text-decoration: none;
      backdrop-filter: blur(12px);
    }}
    .anchor-link:hover {{
      background: rgba(255,255,255,0.14);
    }}
    .hero-chip,
    .runtime-pill,
    .signal-pill {{
      display: inline-flex;
      align-items: center;
      min-height: 38px;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.5);
      color: inherit;
      font-size: 12px;
      line-height: 1.5;
    }}
    .hero-chip {{
      border-color: rgba(255,255,255,0.14);
      background: rgba(255,255,255,0.08);
      color: var(--hero-ink);
      backdrop-filter: blur(12px);
    }}
    .hero-side {{
      display: grid;
      gap: 16px;
    }}
    .hero-side > * {{
      animation: rise-in 760ms cubic-bezier(0.22, 1, 0.36, 1) both;
      animation-delay: 120ms;
    }}
    .risk-badge {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 14px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.18);
      background: rgba(255,255,255,0.08);
      color: var(--hero-ink);
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      backdrop-filter: blur(12px);
    }}
    .risk-dot {{
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: currentColor;
      box-shadow: 0 0 16px currentColor;
    }}
    .risk-high {{
      color: var(--danger);
      background: rgba(180, 77, 61, 0.16);
    }}
    .risk-medium {{
      color: var(--warn);
      background: rgba(171, 116, 55, 0.16);
    }}
    .risk-low {{
      color: #d7f2e8;
    }}
    .meta-card,
    .panel {{
      position: relative;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 24px;
      background: var(--paper);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.48);
      backdrop-filter: blur(10px);
      transition: transform 220ms ease, box-shadow 220ms ease, border-color 220ms ease;
    }}
    .meta-card:hover,
    .panel:hover {{
      transform: translateY(-3px);
      border-color: var(--line-strong);
      box-shadow: 0 18px 40px rgba(15, 38, 31, 0.08), inset 0 1px 0 rgba(255,255,255,0.45);
    }}
    .meta-card::before,
    .panel::before {{
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      background: linear-gradient(180deg, rgba(255,255,255,0.34), rgba(255,255,255,0));
    }}
    .meta-card {{
      padding: 18px 18px 20px;
    }}
    .meta-card.featured,
    .panel-strong {{
      background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(244, 249, 246, 0.95));
    }}
    .meta-card.dark,
    .panel-dark,
    .command-card {{
      border-color: rgba(11, 26, 22, 0.18);
      background: linear-gradient(135deg, #14241f 0%, #10201b 100%);
      color: #eff7f3;
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
    }}
    .meta-card.dark::before,
    .panel-dark::before,
    .command-card::before {{
      background: linear-gradient(180deg, rgba(255,255,255,0.04), transparent 40%);
    }}
    .meta-label,
    .panel-kicker {{
      display: block;
      margin-bottom: 8px;
      color: var(--accent);
      font-size: 11px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      font-weight: 600;
    }}
    .meta-card.dark .meta-label,
    .panel-dark .panel-kicker {{
      color: #bfded4;
    }}
    .meta-value {{
      position: relative;
      z-index: 1;
      font-family: "Iowan Old Style", "Georgia", "Songti SC", serif;
      font-size: 28px;
      line-height: 1.08;
      letter-spacing: -0.03em;
      color: inherit;
    }}
    .meta-note {{
      position: relative;
      z-index: 1;
      margin-top: 12px;
      color: var(--ink-soft);
      font-size: 13px;
      line-height: 1.75;
    }}
    .meta-card.dark .meta-note,
    .panel-dark .panel-summary,
    .panel-dark p {{
      color: rgba(239, 247, 243, 0.74);
    }}
    .meta-board {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .meta-tile span {{
      display: block;
    }}
    .meta-name {{
      margin-bottom: 6px;
      color: var(--ink-faint);
      font-size: 11px;
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }}
    .meta-card.dark .meta-name {{
      color: rgba(239, 247, 243, 0.54);
    }}
    .meta-copy {{
      font-size: 14px;
      line-height: 1.55;
      color: inherit;
    }}
    .section-flow {{
      position: relative;
      z-index: 1;
      padding: 8px 24px 28px;
    }}
    .summary-board {{
      display: grid;
      gap: 14px;
      margin: 18px 0 0;
    }}
    .summary-card {{
      padding: 16px 16px 18px;
      border-radius: 20px;
      border: 1px solid var(--line);
      background: var(--paper-soft);
    }}
    .summary-label {{
      margin-bottom: 8px;
      color: var(--accent);
      font-size: 11px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      font-weight: 600;
    }}
    .summary-copy {{
      font-size: 14px;
      line-height: 1.8;
      color: var(--ink);
    }}
    .section-heading {{
      display: grid;
      gap: 8px;
      padding: 8px 4px 16px;
    }}
    .section-index {{
      color: var(--ink-faint);
      font-size: 11px;
      letter-spacing: 0.22em;
      text-transform: uppercase;
    }}
    .section-title {{
      margin: 0;
      font-family: "Iowan Old Style", "Georgia", "Songti SC", serif;
      font-size: clamp(28px, 4vw, 42px);
      line-height: 0.96;
      letter-spacing: -0.04em;
    }}
    .section-caption {{
      margin: 0;
      max-width: 820px;
      color: var(--ink-soft);
      font-size: 14px;
      line-height: 1.8;
    }}
    .panel-grid {{
      display: grid;
      gap: 18px;
    }}
    .panel-grid > * {{
      animation: rise-in 720ms cubic-bezier(0.22, 1, 0.36, 1) both;
    }}
    .panel-grid > *:nth-child(2) {{ animation-delay: 70ms; }}
    .panel-grid > *:nth-child(3) {{ animation-delay: 120ms; }}
    .panel-grid > *:nth-child(4) {{ animation-delay: 170ms; }}
    .panel-grid > *:nth-child(5) {{ animation-delay: 220ms; }}
    .panel-grid > *:nth-child(6) {{ animation-delay: 270ms; }}
    .panel-body {{
      position: relative;
      z-index: 1;
      padding: 20px 20px 22px;
    }}
    .panel h2 {{
      margin: 0;
      font-family: "Iowan Old Style", "Georgia", "Songti SC", serif;
      font-size: clamp(26px, 3vw, 34px);
      line-height: 1.05;
      letter-spacing: -0.03em;
      color: inherit;
    }}
    .panel-summary {{
      margin: 10px 0 0;
      max-width: 64ch;
      color: var(--ink-soft);
      font-size: 14px;
      line-height: 1.8;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .metric-card {{
      position: relative;
      overflow: hidden;
      padding: 18px 16px 20px;
      border-radius: 20px;
      border: 1px solid var(--line);
      background: rgba(17, 33, 28, 0.035);
    }}
    .metric-card::after {{
      content: "";
      position: absolute;
      left: 0;
      top: 0;
      width: 100%;
      height: 4px;
      background: linear-gradient(90deg, var(--accent), rgba(17, 33, 28, 0));
    }}
    .metric-label {{
      font-size: 11px;
      color: var(--ink-faint);
      margin-bottom: 12px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}
    .metric-value {{
      font-family: "Iowan Old Style", "Georgia", "Songti SC", serif;
      font-size: clamp(28px, 5vw, 40px);
      font-weight: 700;
      color: var(--ink);
      letter-spacing: -0.04em;
    }}
    .table-shell {{
      width: 100%;
      overflow-x: auto;
      margin-top: 18px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.6);
    }}
    table {{
      width: 100%;
      min-width: 680px;
      border-collapse: collapse;
      table-layout: fixed;
      background: transparent;
    }}
    th, td {{
      border: 1px solid var(--line);
      padding: 12px 13px;
      text-align: left;
      vertical-align: top;
      font-size: 13px;
      word-break: break-word;
    }}
    th {{
      background: #162722;
      color: #eef7f3;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-size: 11px;
      position: sticky;
      top: 0;
      z-index: 1;
    }}
    tbody tr:nth-child(even) td {{
      background: rgba(17, 33, 28, 0.025);
    }}
    tbody tr:hover td {{
      background: rgba(75, 145, 125, 0.08);
    }}
    td.empty {{
      text-align: center;
      color: var(--ink-soft);
      padding: 22px;
    }}
    ul {{
      margin: 0;
      padding: 0;
      list-style: none;
      line-height: 1.8;
    }}
    li {{
      position: relative;
      padding-left: 18px;
      color: inherit;
    }}
    li + li {{
      margin-top: 10px;
    }}
    li::before {{
      content: "";
      position: absolute;
      left: 0;
      top: 0.78em;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--accent);
      transform: translateY(-50%);
      box-shadow: 0 0 0 4px rgba(75, 145, 125, 0.12);
    }}
    .notice-block {{
      margin-top: 18px;
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid rgba(171, 116, 55, 0.22);
      background: rgba(171, 116, 55, 0.09);
      color: #6a4a27;
      font-size: 13px;
      line-height: 1.78;
    }}
    .notice-block p {{
      margin: 0 0 6px;
      color: inherit;
    }}
    .notice-block p:last-child {{
      margin-bottom: 0;
    }}
    .panel-dark .runtime-pill,
    .panel-dark .signal-pill,
    .meta-card.dark .runtime-pill,
    .meta-card.dark .signal-pill {{
      border-color: rgba(255,255,255,0.12);
      background: rgba(255,255,255,0.08);
      color: #eff7f3;
    }}
    .command-grid {{
      display: grid;
      gap: 14px;
      margin-top: 18px;
    }}
    .command-card {{
      position: relative;
      border-radius: 20px;
      padding: 16px;
    }}
    .command-target {{
      font-size: 11px;
      color: rgba(239, 247, 243, 0.62);
      margin-bottom: 8px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }}
    .command-line {{
      font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
      font-size: 13px;
      color: #cde9df;
      margin-bottom: 10px;
      font-weight: 600;
    }}
    pre {{
      margin: 0;
      padding: 12px;
      border-radius: 14px;
      background: rgba(255,255,255,0.05);
      color: #edf5ef;
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
      font-size: 11px;
      line-height: 1.55;
    }}
    .empty-panel {{
      padding: 16px;
      border: 1px dashed var(--line);
      border-radius: 16px;
      color: var(--ink-soft);
      background: rgba(255,255,255,0.36);
    }}
    .legacy-grid {{
      display: grid;
      gap: 16px;
      margin-top: 18px;
    }}
    .subpanel {{
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 20px;
      background: rgba(255,255,255,0.52);
    }}
    .subpanel h3 {{
      margin: 0;
      font-family: "Iowan Old Style", "Georgia", "Songti SC", serif;
      font-size: 22px;
      line-height: 1.1;
      letter-spacing: -0.03em;
    }}
    .subpanel-summary {{
      margin: 8px 0 0;
      color: var(--ink-soft);
      font-size: 13px;
      line-height: 1.75;
    }}
    .subpanel.full {{
      grid-column: 1 / -1;
    }}
    .node-header {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 14px;
    }}
    .bar-row,
    .line-row {{
      display: grid;
      grid-template-columns: minmax(120px, 220px) 1fr 70px;
      align-items: center;
      gap: 12px;
      margin: 12px 0;
    }}
    .bar-track,
    .line-track {{
      background: rgba(17, 33, 28, 0.08);
      height: 12px;
      border-radius: 999px;
      overflow: hidden;
    }}
    .bar-track span,
    .line-track span {{
      display: block;
      height: 100%;
      background: linear-gradient(90deg, var(--accent), #8fc4b1);
      border-radius: 999px;
    }}
    .bar-label,
    .line-label,
    .bar-value,
    .line-value {{
      font-size: 14px;
    }}
    .footer-bar {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 12px;
      padding: 0 24px 24px;
      color: var(--ink-faint);
      font-size: 12px;
      line-height: 1.7;
    }}
    .footer-bar strong {{
      color: var(--ink);
      font-weight: 600;
    }}
    @media (min-width: 760px) {{
      .report-shell {{ padding: 30px 20px 56px; }}
      .top-ribbon {{ padding: 22px 30px 0; }}
      .hero {{ padding: 22px 30px 12px; }}
      .section-flow {{ padding: 10px 30px 30px; }}
      .command-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .summary-board {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    }}
    @media (min-width: 980px) {{
      .hero-grid {{
        grid-template-columns: minmax(0, 1.4fr) minmax(340px, 0.72fr);
        align-items: start;
      }}
      .section-heading {{
        grid-template-columns: minmax(0, 1fr) auto;
        align-items: end;
        gap: 20px;
      }}
      .metrics {{
        grid-template-columns: repeat(4, minmax(0, 1fr));
      }}
      .panel-grid {{
        grid-template-columns: repeat(12, minmax(0, 1fr));
      }}
      .legacy-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .span-4 {{ grid-column: span 4; }}
      .span-5 {{ grid-column: span 5; }}
      .span-6 {{ grid-column: span 6; }}
      .span-7 {{ grid-column: span 7; }}
      .span-8 {{ grid-column: span 8; }}
      .span-12 {{ grid-column: span 12; }}
    }}
    @media print {{
      body {{
        background: #fff;
      }}
      body::before {{
        display: none;
      }}
      .report-shell {{
        margin: 0;
        padding: 0;
        width: 100%;
      }}
      .report-frame {{
        border: none;
        border-radius: 0;
        box-shadow: none;
      }}
      .hero-intro,
      .panel-dark,
      .meta-card.dark,
      .command-card,
      th,
      pre {{
        color: #111 !important;
        background: #fff !important;
      }}
      th {{
        position: static !important;
      }}
      .panel,
      .meta-card,
      .metric-card,
      .table-shell,
      .command-card,
      .subpanel {{
        break-inside: avoid;
      }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      .hero-intro,
      .hero-side > *,
      .panel-grid > *,
      .meta-card,
      .panel {{
        animation: none !important;
        transition: none !important;
        transform: none !important;
      }}
    }}
  </style>
</head>
<body>
  <main class="report-shell">
    <div class="report-frame">
      <div class="top-ribbon">
        <div>JumpServer / Full Inspection Dossier</div>
        <div>{escape(metadata['company'])} / Generated {escape(metadata['generated_at'])}</div>
      </div>

      <header class="hero">
        <div class="hero-grid">
          <section class="hero-intro">
            <p class="eyebrow">JumpServer Inspection Report</p>
            {render_risk_badge(risk_level)}
            <h1>{escape(metadata['title'])}</h1>
            <p class="hero-summary">{escape(dispatch_message)}</p>
            <p class="hero-lead">{coverage_summary}</p>
            <div class="hero-foot">
              <span class="hero-chip">Profile / {escape(metadata['profile_name'])}</span>
              <span class="hero-chip">Scope / {escape(context['scope_name'])}</span>
              <span class="hero-chip">Version / {escape(report_version)}</span>
              <span class="hero-chip">Window / {escape(context['date_from'])} - {escape(context['date_to'])}</span>
            </div>
            {render_anchor_nav(section_nav)}
          </section>
          <aside class="hero-side">
            <section class="meta-card featured">
              <span class="meta-label">Executive Snapshot</span>
              <div class="meta-value">正式巡检总览</div>
              <p class="meta-note">面向值班、运维和安全汇报的完整版巡检摘要，保留完整节点与数据库数据面。</p>
              {render_html_list(bundle['executive_summary_items'])}
            </section>
            <section class="meta-card dark">
              <span class="meta-label">Report Identity</span>
              <div class="meta-board">
                <div class="meta-tile">
                  <span class="meta-name">统计区间</span>
                  <span class="meta-copy">{escape(context['date_from'])} 至 {escape(context['date_to'])}</span>
                </div>
                <div class="meta-tile">
                  <span class="meta-name">生成时间</span>
                  <span class="meta-copy">{escape(metadata['generated_at'])}</span>
                </div>
                <div class="meta-tile">
                  <span class="meta-name">客户</span>
                  <span class="meta-copy">{escape(metadata['customer'])}</span>
                </div>
                <div class="meta-tile">
                  <span class="meta-name">JumpServer</span>
                  <span class="meta-copy">{escape(metadata['base_url'])}</span>
                </div>
              </div>
              <div class="runtime-list">
                <span class="runtime-pill">Company：{escape(metadata['company'])}</span>
                <span class="runtime-pill">Theme：{escape(metadata['theme_color'])}</span>
              </div>
            </section>
          </aside>
        </div>
        {render_notice_block(notice_items)}
      </header>

      <section class="section-flow" id="overview">
        <div class="section-heading">
          <div>
            <div class="section-index">01 / Executive Overview</div>
            <h2 class="section-title">总览与态势</h2>
          </div>
          <p class="section-caption">先给出风险等级、关键异常、覆盖节点和重点结论，便于值班同学快速完成晨会或交班使用。</p>
        </div>
        {render_summary_callouts(summary_callouts)}
        <div class="panel-grid">
          <article class="panel panel-strong span-12">
            <div class="panel-body">
              <p class="panel-kicker">Security Posture</p>
              <h2>核心态势指标</h2>
              <p class="panel-summary">综合平台风险、纳管规模、会话、登录和高危命令数据，形成正式巡检的摘要层。</p>
              <div class="metrics">{render_metric_cards(overview_cards)}</div>
            </div>
          </article>

          <article class="panel span-7">
            <div class="panel-body">
              <p class="panel-kicker">Target Coverage</p>
              <h2>巡检目标</h2>
              <p class="panel-summary">本次巡检以 JumpServer 节点为采集中心，覆盖 {len(context["overview_targets"])} 个节点，主要资产类型为 {escape(asset_type_text)}。</p>
              {render_html_table_block([("机器名", "asset_name"), ("机器类型", "platform"), ("机器 IP", "ip"), ("机器端口", "port"), ("SSH 用户名", "username"), ("是否有效", "enabled"), ("状态", "status")], context["overview_targets"], "未配置 JMS_SYSTEM_TARGETS。")}
            </div>
          </article>

          <article class="panel span-5">
            <div class="panel-body">
              <p class="panel-kicker">Findings</p>
              <h2>关键发现</h2>
              <p class="panel-summary">适合在日报正文或管理摘要中直接引用的重点结论。</p>
              {render_html_list(bundle['key_findings_items'])}
            </div>
          </article>

          <article class="panel span-8">
            <div class="panel-body">
              <p class="panel-kicker">Anomaly Focus</p>
              <h2>异常聚焦</h2>
              <p class="panel-summary">合并登录失败、异常资产、会话风险和命令巡检异常，作为优先排查清单。</p>
              {render_html_table_block([("异常等级", "level"), ("异常节点", "node"), ("异常描述", "description")], context["anomaly_rows"], "当前未发现需要升级处理的异常。")}
            </div>
          </article>

          <article class="panel panel-dark span-4">
            <div class="panel-body">
              <p class="panel-kicker">Risk Surface</p>
              <h2>风险摘要</h2>
              <p class="panel-summary">将安全风险项压缩到右侧，便于在手机端快速浏览。</p>
              {render_html_list(bundle['security_risk_items'], "今日未识别出显著安全风险。")}
            </div>
          </article>
        </div>
      </section>

      <section class="section-flow" id="ops">
        <div class="section-heading">
          <div>
            <div class="section-index">02 / Database And Operations</div>
            <h2 class="section-title">数据库与运营指标</h2>
          </div>
          <p class="section-caption">这一层保留正式巡检需要的数据库状态、表大小、协议分布、登录趋势与运营统计，兼顾归档和排障。</p>
        </div>
        <div class="panel-grid">
          <article class="panel span-6">
            <div class="panel-body">
              <p class="panel-kicker">Database</p>
              <h2>RDS 状态</h2>
              <p class="panel-summary">确认数据库版本、端口和检测时间，便于快速识别后端实例异常。</p>
              {render_html_table_block([("主机", "hostname"), ("版本", "version"), ("版本说明", "version_comment"), ("端口", "port"), ("检查时间", "checked_at")], db_metrics["rds_status_rows"], "未采集到数据库实例状态。")}
            </div>
          </article>

          <article class="panel span-6">
            <div class="panel-body">
              <p class="panel-kicker">Capacity</p>
              <h2>数据库表大小前 10</h2>
              <p class="panel-summary">帮助判断审计、会话或操作记录相关表是否出现异常膨胀。</p>
              {render_html_table_block([("表名", "table_name"), ("大小(MB)", "size_mb"), ("记录数", "table_rows")], db_metrics["table_size_rows"], "未采集到表大小数据。")}
            </div>
          </article>

          <article class="panel span-12">
            <div class="panel-body">
              <p class="panel-kicker">Operations Summary</p>
              <h2>运营概况</h2>
              <p class="panel-summary">当前组织数 <strong>{operations["org_count"]}</strong>，用户数 <strong>{operations["user_count"]}</strong>，资产数 <strong>{operations["asset_count"]}</strong>，资产类型前三为 <strong>{escape(asset_type_text)}</strong>，在线会话数 <strong>{operations["online_sessions"]}</strong>，最大单日访问资产数 <strong>{operations["max_daily_asset_access_count"]}</strong>。</p>
              {render_html_table_block([("指标", "metric"), ("值", "value")], operation_rows, "未采集到运营巡检指标。")}
            </div>
          </article>

          <article class="panel span-4">
            <div class="panel-body">
              <p class="panel-kicker">Protocol</p>
              <h2>协议占比</h2>
              <p class="panel-summary">按协议查看近阶段访问占比，辅助识别连接习惯变化。</p>
              {render_bar_list(db_metrics["protocol_distribution"], empty_text="未采集到协议占比。")}
            </div>
          </article>

          <article class="panel span-4">
            <div class="panel-body">
              <p class="panel-kicker">Trend</p>
              <h2>{escape(trend_label)}用户登录数</h2>
              <p class="panel-summary">用于观察用户登录趋势变化。</p>
              {render_line_series(db_metrics["weekly_user_trend"], empty_text="未采集到周用户趋势。")}
            </div>
          </article>

          <article class="panel span-4">
            <div class="panel-body">
              <p class="panel-kicker">Trend</p>
              <h2>{escape(trend_label)}资产登录数</h2>
              <p class="panel-summary">用于观察资产访问热度和波动。</p>
              {render_line_series(db_metrics["weekly_asset_trend"], empty_text="未采集到周资产趋势。")}
            </div>
          </article>

          <article class="panel span-6">
            <div class="panel-body">
              <p class="panel-kicker">Top Users</p>
              <h2>近三个月活跃用户 Top 5</h2>
              <p class="panel-summary">作为常驻账号和热点访问主体的参考。</p>
              {render_bar_list(db_metrics["active_users_top5"], empty_text="未采集到活跃用户排行。")}
            </div>
          </article>

          <article class="panel span-6">
            <div class="panel-body">
              <p class="panel-kicker">Top Assets</p>
              <h2>近三个月活跃资产 Top 5</h2>
              <p class="panel-summary">识别热点资产和需要重点盯防的连接目标。</p>
              {render_bar_list(db_metrics["active_assets_top5"], empty_text="未采集到活跃资产排行。")}
            </div>
          </article>
        </div>
      </section>

      <section class="section-flow" id="nodes">
        <div class="section-heading">
          <div>
            <div class="section-index">03 / Node Inspection</div>
            <h2 class="section-title">节点巡检明细</h2>
          </div>
          <p class="section-caption">保留正式巡检报告要求的节点级系统信息和命令证据，适合归档、审计和后续复盘。</p>
        </div>
        <div class="panel-grid">
          {''.join(system_blocks) if system_blocks else '<article class="panel span-12"><div class="panel-body"><p class="panel-kicker">Node Inspection</p><h2>节点巡检结果</h2><p class="panel-summary">当前未采集到节点级系统巡检结果。</p><div class="empty-panel">未采集到节点级系统巡检结果。</div></div></article>'}
        </div>
      </section>

      <section class="section-flow" id="audit">
        <div class="section-heading">
          <div>
            <div class="section-index">04 / Audit And Follow Up</div>
            <h2 class="section-title">审计与处置建议</h2>
          </div>
          <p class="section-caption">最后给出高风险操作、最近审计、风险摘要和后续动作，构成一份可以直接交付的巡检报告尾段。</p>
        </div>
        <div class="panel-grid">
          <article class="panel span-7">
            <div class="panel-body">
              <p class="panel-kicker">Audit</p>
              <h2>高风险操作审计</h2>
              <p class="panel-summary">提取 delete、remove、drop 等高风险动作，适合作为正式巡检里的重点审计项。</p>
              {render_html_table_block([("时间", "time"), ("用户", "username"), ("动作", "action"), ("对象", "target")], bundle["operate_stats"]["dangerous_rows"][:20], "未发现高风险操作审计记录。")}
            </div>
          </article>

          <article class="panel panel-dark span-5">
            <div class="panel-body">
              <p class="panel-kicker">Action</p>
              <h2>处置建议</h2>
              <p class="panel-summary">根据当前风险面给出可直接执行的后续动作。</p>
              {render_html_list(bundle['recommendation_items'])}
            </div>
          </article>

          <article class="panel span-7">
            <div class="panel-body">
              <p class="panel-kicker">Audit Trail</p>
              <h2>最近操作审计</h2>
              <p class="panel-summary">补充展示最近审计记录，便于回溯近期平台操作轨迹。</p>
              {render_html_table_block([("时间", "time"), ("用户", "username"), ("动作", "action"), ("对象", "target")], bundle["operate_stats"]["rows"][:20], "未获取到操作审计记录。")}
            </div>
          </article>

          <article class="panel span-5">
            <div class="panel-body">
              <p class="panel-kicker">Runtime</p>
              <h2>巡检说明</h2>
              <p class="panel-summary">记录采集来源、运行环境和输出链路，方便后续复跑或交接。</p>
              {render_html_list(notice_items, "本次巡检数据采集与渲染链路正常。")}
              <div class="runtime-list">
                <span class="runtime-pill">Profile：{escape(metadata['profile_name'])}</span>
                <span class="runtime-pill">组织范围：{escape(context['scope_name'])}</span>
                <span class="runtime-pill">环境文件：{escape(metadata['profile_source'])}</span>
                <span class="runtime-pill">报告日期：{escape(metadata['report_date'])}</span>
              </div>
            </div>
          </article>
        </div>
      </section>

      <div class="footer-bar">
        <div><strong>{escape(metadata['company'])}</strong> / JumpServer Full Inspection Report</div>
        <div>{escape(metadata['generated_at'])}</div>
      </div>
    </div>
  </main>
</body>
</html>
"""


def render_html_report(
    report_date: str,
    profile_name: str,
    org_name: Optional[str] = None,
    all_orgs: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> str:
    context = build_data_bundle(
        report_date,
        profile_name,
        org_name=org_name,
        all_orgs=all_orgs,
        date_from=date_from,
        date_to=date_to,
    )
    metadata = context["metadata"]
    accent = metadata["theme_color"]

    def scoped_headers(headers: List[Tuple[str, str]], rows: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
        if any(str(row.get("org_name") or "").strip() for row in rows):
            return [("组织", "org_name"), *headers]
        return headers

    overview_cards = [
        ("风险等级", context["risk_level"]),
        ("资产总数", context["asset_stats"]["total"]),
        ("命令巡检节点", f"{context['command_stats']['success_targets']}/{context['command_stats']['targets']}"),
        ("活跃会话", context["session_stats"]["total"]),
        ("今日登录", context["login_stats"]["total"]),
        ("登录失败", context["login_stats"]["failure"]),
        ("审计记录", context["operate_stats"]["total"]),
    ]

    asset_rows = context["asset_stats"]["rows"][:8]
    anomaly_rows = context["anomaly_rows"][:10]
    command_rows = context["command_stats"]["commands"][:4]
    filesystem_rows = context["command_stats"]["filesystem_rows"][:10]
    session_rows = context["session_stats"]["rows"][:8]
    dangerous_rows = context["operate_stats"]["dangerous_rows"][:10]
    login_failure_rows = context["login_stats"]["failure_details"][:10]
    dispatch_message = {
        "高": "风险面已进入优先处置区，建议立即复核异常来源、在线会话与高风险操作。",
        "中": "当前存在需要跟进的异常项，建议按登录、资产、命令链路逐项收敛。",
        "低": "巡检结果整体平稳，建议保持日巡检、异常告警和抽样复核联动。",
    }.get(context["risk_level"], "请结合本次巡检结果继续完成后续复核与处置。")
    coverage_summary = (
        f"本次报告覆盖 {escape(metadata['scope_name'])}，统计区间 {escape(context['report_range'])}，"
        f"已纳管资产 {context['asset_stats']['total']} 台，活跃会话 {context['session_stats']['total']} 条，"
        f"登录失败 {context['login_stats']['failure']} 次，命令巡检成功节点 "
        f"{context['command_stats']['success_targets']}/{context['command_stats']['targets']}。"
    )
    section_nav = [
        ("situation", "态势总览"),
        ("evidence", "主机证据"),
        ("audit", "访问与审计"),
    ]
    summary_callouts = [
        ("建议先看", dispatch_message),
        ("首个异常", anomaly_rows[0]["description"] if anomaly_rows else "当前未发现需要升级处理的异常。"),
        ("建议动作", context["recommendation_items"][0] if context["recommendation_items"] else "当前建议保持日巡检与异常联动。"),
    ]

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(metadata['title'])}</title>
  <style>
    :root {{
      --accent: {escape(accent)};
      --accent-bright: #d9f3eb;
      --accent-soft: rgba(75, 145, 125, 0.12);
      --paper: #edf4f1;
      --paper-strong: #f7fbf9;
      --paper-soft: rgba(244, 249, 246, 0.78);
      --ink: #14211d;
      --ink-soft: #4f645b;
      --ink-faint: #76887f;
      --line: rgba(20, 33, 29, 0.1);
      --line-strong: rgba(20, 33, 29, 0.18);
      --hero-bg: linear-gradient(135deg, #14372d 0%, #1c4c3f 48%, #2a6757 100%);
      --hero-ink: #f4faf7;
      --warn: #ab7437;
      --danger: #b44d3d;
      --shadow: 0 30px 80px rgba(15, 38, 31, 0.14);
    }}
    * {{
      box-sizing: border-box;
    }}
    html, body {{
      margin: 0;
      padding: 0;
      font-family: "IBM Plex Sans", "PingFang SC", "Microsoft YaHei", sans-serif;
      background:
        radial-gradient(circle at 12% 0%, rgba(75, 145, 125, 0.16), transparent 28%),
        radial-gradient(circle at 100% 18%, rgba(75, 145, 125, 0.08), transparent 24%),
        linear-gradient(180deg, #e6eeea 0%, #eef5f2 46%, #f5f8f7 100%);
      color: var(--ink);
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    body {{
      min-height: 100vh;
      position: relative;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      opacity: 0.42;
      background:
        linear-gradient(90deg, rgba(255,255,255,0.16) 0, rgba(255,255,255,0.16) 1px, transparent 1px, transparent 100%),
        linear-gradient(rgba(255,255,255,0.16) 0, rgba(255,255,255,0.16) 1px, transparent 1px, transparent 100%);
      background-size: 32px 32px;
      mask-image: linear-gradient(180deg, rgba(0,0,0,0.42), transparent 75%);
    }}
    a {{
      color: inherit;
    }}
    .report-shell {{
      width: min(100%, 1460px);
      margin: 0 auto;
      padding: 24px 14px 48px;
    }}
    .report-frame {{
      position: relative;
      overflow: hidden;
      border-radius: 34px;
      border: 1px solid var(--line);
      background:
        linear-gradient(180deg, rgba(248, 251, 250, 0.96) 0%, rgba(242, 247, 244, 0.98) 100%);
      box-shadow: var(--shadow);
    }}
    .report-frame::before {{
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      background:
        radial-gradient(circle at 0 0, rgba(255,255,255,0.58), transparent 34%),
        radial-gradient(circle at 100% 24%, rgba(75, 145, 125, 0.08), transparent 22%),
        linear-gradient(180deg, transparent 0%, rgba(255,255,255,0.22) 100%);
    }}
    @keyframes rise-in {{
      from {{
        opacity: 0;
        transform: translateY(18px);
      }}
      to {{
        opacity: 1;
        transform: translateY(0);
      }}
    }}
    .top-ribbon {{
      position: relative;
      z-index: 1;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 10px 18px;
      padding: 18px 24px 0;
      color: var(--ink-faint);
      font-size: 11px;
      letter-spacing: 0.18em;
      text-transform: uppercase;
    }}
    .hero {{
      position: relative;
      z-index: 1;
      padding: 18px 24px 10px;
    }}
    .hero-grid {{
      display: grid;
      gap: 18px;
    }}
    .hero-intro {{
      position: relative;
      overflow: hidden;
      padding: 28px 24px;
      border-radius: 30px;
      background: var(--hero-bg);
      color: var(--hero-ink);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.06);
      animation: rise-in 760ms cubic-bezier(0.22, 1, 0.36, 1) both;
    }}
    .hero-intro::before {{
      content: "";
      position: absolute;
      width: 360px;
      height: 360px;
      right: -120px;
      top: -180px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(255,255,255,0.14), transparent 68%);
    }}
    .hero-intro::after {{
      content: "DOSSIER";
      position: absolute;
      right: 24px;
      bottom: 12px;
      color: rgba(255,255,255,0.08);
      font-size: clamp(40px, 8vw, 110px);
      font-weight: 700;
      letter-spacing: 0.08em;
      line-height: 1;
    }}
    .eyebrow {{
      margin: 0;
      color: var(--accent-bright);
      font-size: 12px;
      letter-spacing: 0.24em;
      text-transform: uppercase;
    }}
    .hero h1 {{
      position: relative;
      z-index: 1;
      margin: 18px 0 18px;
      max-width: 860px;
      font-family: "Iowan Old Style", "Georgia", "Songti SC", serif;
      font-size: clamp(40px, 7vw, 78px);
      line-height: 0.94;
      letter-spacing: -0.04em;
    }}
    .hero-summary {{
      margin: 0;
      position: relative;
      z-index: 1;
      max-width: 720px;
      color: rgba(247, 241, 230, 0.84);
      font-size: 16px;
      line-height: 1.9;
    }}
    .hero-lead {{
      position: relative;
      z-index: 1;
      max-width: 760px;
      margin: 18px 0 0;
      color: rgba(247, 241, 230, 0.78);
      font-size: 13px;
      line-height: 1.85;
    }}
    .hero-foot {{
      position: relative;
      z-index: 1;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 22px;
    }}
    .anchor-nav {{
      position: relative;
      z-index: 1;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
    }}
    .anchor-link {{
      display: inline-flex;
      align-items: center;
      min-height: 38px;
      padding: 8px 14px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.14);
      background: rgba(255,255,255,0.08);
      color: var(--hero-ink);
      font-size: 12px;
      line-height: 1.5;
      text-decoration: none;
      backdrop-filter: blur(12px);
    }}
    .anchor-link:hover {{
      background: rgba(255,255,255,0.14);
    }}
    .hero-chip {{
      display: inline-flex;
      align-items: center;
      min-height: 38px;
      padding: 8px 14px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.14);
      background: rgba(255,255,255,0.08);
      color: var(--hero-ink);
      font-size: 12px;
      line-height: 1.5;
      backdrop-filter: blur(12px);
    }}
    .hero-side {{
      display: grid;
      gap: 16px;
    }}
    .hero-side > * {{
      animation: rise-in 760ms cubic-bezier(0.22, 1, 0.36, 1) both;
      animation-delay: 120ms;
    }}
    .hero-stack {{
      position: relative;
    }}
    .risk-badge {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 14px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.18);
      background: rgba(255,255,255,0.08);
      color: var(--hero-ink);
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      backdrop-filter: blur(12px);
    }}
    .risk-dot {{
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: currentColor;
      box-shadow: 0 0 16px currentColor;
    }}
    .risk-high {{
      color: var(--danger);
      border-color: rgba(255, 255, 255, 0.12);
      background: rgba(180, 77, 61, 0.16);
    }}
    .risk-medium {{
      color: var(--warn);
      border-color: rgba(255, 255, 255, 0.12);
      background: rgba(168, 109, 50, 0.16);
    }}
    .risk-low {{
      color: #d7f2e8;
    }}
    .meta-stack,
    .meta-board {{
      display: grid;
      gap: 12px;
    }}
    .meta-card,
    .panel {{
      position: relative;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 24px;
      background: rgba(255, 248, 239, 0.78);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.45);
      backdrop-filter: blur(10px);
      transition: transform 220ms ease, box-shadow 220ms ease, border-color 220ms ease, background-color 220ms ease;
    }}
    .meta-card:hover,
    .panel:hover {{
      transform: translateY(-3px);
      border-color: var(--line-strong);
      box-shadow: 0 18px 40px rgba(36, 32, 25, 0.1), inset 0 1px 0 rgba(255,255,255,0.42);
    }}
    .meta-card::before,
    .panel::before {{
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      background: linear-gradient(180deg, rgba(255,255,255,0.34), rgba(255,255,255,0));
    }}
    .meta-card {{
      padding: 18px 18px 20px;
    }}
    .meta-card.featured {{
      background: linear-gradient(180deg, rgba(255, 251, 245, 0.96), rgba(244, 236, 221, 0.92));
    }}
    .meta-card.dark,
    .panel-dark {{
      border-color: rgba(12, 15, 14, 0.2);
      background: linear-gradient(135deg, #17211d 0%, #101816 100%);
      color: #eff4ed;
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
    }}
    .meta-card.dark::before,
    .panel-dark::before {{
      background: linear-gradient(180deg, rgba(255,255,255,0.04), transparent 40%);
    }}
    .meta-card .meta-label,
    .panel-kicker {{
      display: block;
      margin-bottom: 8px;
      color: var(--accent);
      font-size: 11px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      font-weight: 600;
    }}
    .meta-card.dark .meta-label,
    .panel-dark .panel-kicker {{
      color: #bfded4;
    }}
    .meta-card .meta-value {{
      position: relative;
      z-index: 1;
      font-family: "Iowan Old Style", "Georgia", "Songti SC", serif;
      font-size: 28px;
      line-height: 1.08;
      letter-spacing: -0.03em;
      color: inherit;
    }}
    .meta-note {{
      position: relative;
      z-index: 1;
      margin-top: 12px;
      color: var(--ink-soft);
      font-size: 13px;
      line-height: 1.75;
    }}
    .meta-card.dark .meta-note {{
      color: rgba(239, 244, 237, 0.72);
    }}
    .meta-card.dark .meta-name {{
      color: rgba(239, 244, 237, 0.52);
    }}
    .meta-board {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .meta-tile {{
      position: relative;
      z-index: 1;
      padding-top: 2px;
    }}
    .meta-tile span {{
      display: block;
    }}
    .meta-tile .meta-name {{
      margin-bottom: 6px;
      color: var(--ink-faint);
      font-size: 11px;
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }}
    .meta-tile .meta-copy {{
      font-size: 14px;
      line-height: 1.55;
      color: inherit;
    }}
    .section-flow {{
      position: relative;
      z-index: 1;
      padding: 8px 24px 28px;
    }}
    .summary-board {{
      display: grid;
      gap: 14px;
      margin: 18px 0 0;
    }}
    .summary-card {{
      padding: 16px 16px 18px;
      border-radius: 20px;
      border: 1px solid var(--line);
      background: var(--paper-soft);
    }}
    .summary-label {{
      margin-bottom: 8px;
      color: var(--accent);
      font-size: 11px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      font-weight: 600;
    }}
    .summary-copy {{
      font-size: 14px;
      line-height: 1.8;
      color: var(--ink);
    }}
    .section-heading {{
      display: grid;
      gap: 8px;
      padding: 8px 4px 16px;
    }}
    .section-index {{
      color: var(--ink-faint);
      font-size: 11px;
      letter-spacing: 0.22em;
      text-transform: uppercase;
    }}
    .section-title {{
      margin: 0;
      font-family: "Iowan Old Style", "Georgia", "Songti SC", serif;
      font-size: clamp(28px, 4vw, 42px);
      line-height: 0.96;
      letter-spacing: -0.04em;
    }}
    .section-caption {{
      margin: 0;
      max-width: 760px;
      color: var(--ink-soft);
      font-size: 14px;
      line-height: 1.8;
    }}
    .panel-grid {{
      display: grid;
      gap: 18px;
    }}
    .panel-grid > * {{
      animation: rise-in 720ms cubic-bezier(0.22, 1, 0.36, 1) both;
    }}
    .panel-grid > *:nth-child(2) {{
      animation-delay: 70ms;
    }}
    .panel-grid > *:nth-child(3) {{
      animation-delay: 120ms;
    }}
    .panel-grid > *:nth-child(4) {{
      animation-delay: 170ms;
    }}
    .panel-grid > *:nth-child(5) {{
      animation-delay: 220ms;
    }}
    .panel-grid > *:nth-child(6) {{
      animation-delay: 270ms;
    }}
    .panel-body {{
      position: relative;
      z-index: 1;
      padding: 20px 20px 22px;
    }}
    .panel-strong {{
      background: linear-gradient(180deg, rgba(255, 252, 247, 0.98), rgba(245, 238, 226, 0.94));
    }}
    .panel h2 {{
      margin: 0;
      font-family: "Iowan Old Style", "Georgia", "Songti SC", serif;
      font-size: clamp(26px, 3vw, 34px);
      line-height: 1.05;
      letter-spacing: -0.03em;
      color: inherit;
    }}
    .panel-summary {{
      margin: 10px 0 0;
      max-width: 62ch;
      color: var(--ink-soft);
      font-size: 14px;
      line-height: 1.8;
    }}
    .panel-dark .panel-summary,
    .panel-dark p,
    .meta-card.dark p {{
      color: rgba(239, 244, 237, 0.72);
    }}
    section {{
      margin: 0;
    }}
    p {{
      margin: 0;
      line-height: 1.8;
      color: var(--ink-soft);
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .metric-card {{
      position: relative;
      overflow: hidden;
      padding: 18px 16px 20px;
      border-radius: 20px;
      border: 1px solid var(--line);
      background: rgba(23, 22, 18, 0.035);
    }}
    .metric-card::after {{
      content: "";
      position: absolute;
      left: 0;
      top: 0;
      width: 100%;
      height: 4px;
      background: linear-gradient(90deg, var(--accent), rgba(23, 22, 18, 0));
    }}
    .metric-label {{
      font-size: 11px;
      color: var(--ink-faint);
      margin-bottom: 12px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}
    .metric-value {{
      font-family: "Iowan Old Style", "Georgia", "Songti SC", serif;
      font-size: clamp(28px, 5vw, 40px);
      font-weight: 700;
      color: var(--ink);
      letter-spacing: -0.04em;
    }}
    .table-shell {{
      width: 100%;
      overflow-x: auto;
      margin-top: 18px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.56);
    }}
    table {{
      width: 100%;
      min-width: 680px;
      border-collapse: collapse;
      table-layout: fixed;
      background: transparent;
    }}
    th, td {{
      border: 1px solid var(--line);
      padding: 12px 13px;
      text-align: left;
      vertical-align: top;
      font-size: 13px;
      word-break: break-word;
    }}
    th {{
      background: #171b19;
      color: #eef4ed;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-size: 11px;
      position: sticky;
      top: 0;
      z-index: 1;
    }}
    tbody tr:nth-child(even) td {{
      background: rgba(20, 33, 29, 0.025);
    }}
    tbody tr:hover td {{
      background: rgba(75, 145, 125, 0.08);
    }}
    td.empty {{
      text-align: center;
      color: var(--ink-soft);
      padding: 22px;
    }}
    ul {{
      margin: 0;
      padding: 0;
      list-style: none;
      line-height: 1.8;
    }}
    li + li {{
      margin-top: 10px;
    }}
    li {{
      position: relative;
      padding-left: 18px;
      color: inherit;
    }}
    li::before {{
      content: "";
      position: absolute;
      left: 0;
      top: 0.78em;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--accent);
      transform: translateY(-50%);
      box-shadow: 0 0 0 4px rgba(75, 145, 125, 0.12);
    }}
    .command-grid {{
      display: grid;
      gap: 14px;
      margin-top: 18px;
    }}
    .command-card {{
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 20px;
      padding: 16px;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.01)),
        #101513;
      color: #eef4ed;
    }}
    .command-target {{
      font-size: 11px;
      color: rgba(239, 244, 237, 0.6);
      margin-bottom: 8px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }}
    .command-line {{
      font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
      font-size: 13px;
      color: #cde9df;
      margin-bottom: 10px;
      font-weight: 600;
    }}
    pre {{
      margin: 0;
      padding: 12px;
      border-radius: 14px;
      background: rgba(255,255,255,0.05);
      color: #edf5ef;
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
      font-size: 11px;
      line-height: 1.55;
    }}
    .empty-panel {{
      padding: 16px;
      border: 1px dashed var(--line);
      border-radius: 16px;
      color: var(--ink-soft);
      background: rgba(255,255,255,0.36);
    }}
    .notice-block {{
      margin-top: 18px;
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid rgba(168, 109, 50, 0.22);
      background: rgba(168, 109, 50, 0.09);
      color: #6a4a27;
      font-size: 13px;
      line-height: 1.78;
    }}
    .notice-block p {{
      margin: 0 0 6px;
      color: inherit;
    }}
    .notice-block p:last-child {{
      margin-bottom: 0;
    }}
    .runtime-list,
    .signal-list {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }}
    .runtime-pill,
    .signal-pill {{
      display: inline-flex;
      align-items: center;
      min-height: 38px;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.44);
      color: inherit;
      font-size: 12px;
      line-height: 1.5;
    }}
    .panel-dark .runtime-pill,
    .panel-dark .signal-pill,
    .meta-card.dark .runtime-pill,
    .meta-card.dark .signal-pill {{
      border-color: rgba(255,255,255,0.12);
      background: rgba(255,255,255,0.08);
      color: #eff4ed;
    }}
    .footer-bar {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 12px;
      padding: 0 24px 24px;
      color: var(--ink-faint);
      font-size: 12px;
      line-height: 1.7;
    }}
    .footer-bar strong {{
      color: var(--ink);
      font-weight: 600;
    }}
    @media (min-width: 760px) {{
      .report-shell {{
        padding: 30px 20px 56px;
      }}
      .top-ribbon {{
        padding: 22px 30px 0;
      }}
      .hero {{
        padding: 22px 30px 12px;
      }}
      .command-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .section-flow {{
        padding: 10px 30px 30px;
      }}
      .summary-board {{
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }}
    }}
    @media (min-width: 980px) {{
      .hero-grid {{
        grid-template-columns: minmax(0, 1.45fr) minmax(330px, 0.7fr);
        align-items: start;
      }}
      .section-heading {{
        grid-template-columns: minmax(0, 1fr) auto;
        align-items: end;
        gap: 20px;
      }}
      .metrics {{
        grid-template-columns: repeat(4, minmax(0, 1fr));
      }}
      .meta-board {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .panel-grid {{
        grid-template-columns: repeat(12, minmax(0, 1fr));
      }}
      .span-4 {{
        grid-column: span 4;
      }}
      .span-5 {{
        grid-column: span 5;
      }}
      .span-6 {{
        grid-column: span 6;
      }}
      .span-7 {{
        grid-column: span 7;
      }}
      .span-8 {{
        grid-column: span 8;
      }}
      .span-12 {{
        grid-column: span 12;
      }}
    }}
    @media print {{
      body {{
        background: #fff;
      }}
      body::before {{
        display: none;
      }}
      .report-shell {{
        margin: 0;
        padding: 0;
        width: 100%;
      }}
      .report-frame {{
        border: none;
        border-radius: 0;
        box-shadow: none;
      }}
      .hero-intro,
      .panel-dark,
      .meta-card.dark,
      th,
      .command-card,
      pre {{
        color: #111 !important;
        background: #fff !important;
      }}
      th {{
        position: static !important;
      }}
      .panel,
      .meta-card,
      .metric-card,
      .table-shell,
      .command-card {{
        break-inside: avoid;
      }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      .hero-intro,
      .hero-side > *,
      .panel-grid > *,
      .meta-card,
      .panel {{
        animation: none !important;
        transition: none !important;
        transform: none !important;
      }}
    }}
  </style>
</head>
<body>
  <main class="report-shell">
    <div class="report-frame">
      <div class="top-ribbon">
        <div>JumpServer / Inspection Dossier</div>
        <div>{escape(metadata['company'])} / Generated {escape(metadata['generated_at'])}</div>
      </div>

      <header class="hero">
        <div class="hero-grid">
          <section class="hero-intro">
            <p class="eyebrow">JumpServer Inspection Brief</p>
            {render_risk_badge(context['risk_level'])}
            <h1>{escape(metadata['title'])}</h1>
            <p class="hero-summary">{escape(dispatch_message)}</p>
            <p class="hero-lead">{coverage_summary}</p>
            <div class="hero-foot">
              <span class="hero-chip">Profile / {escape(metadata['profile_name'])}</span>
              <span class="hero-chip">Scope / {escape(metadata['scope_name'])}</span>
              <span class="hero-chip">Version / {escape(metadata['version'])}</span>
              <span class="hero-chip">Window / {escape(context['report_range'])}</span>
            </div>
            {render_anchor_nav(section_nav)}
          </section>
          <aside class="hero-side">
            <section class="meta-card featured hero-stack">
              <span class="meta-label">Executive Snapshot</span>
              <div class="meta-value">值班总览</div>
              <p class="meta-note">把最先需要看的一层信息压缩到首页右侧，适合转发给值班、运维和安全负责人。</p>
              {render_html_list(context['executive_summary_items'])}
            </section>
            <section class="meta-card dark hero-stack">
              <span class="meta-label">Report Identity</span>
              <div class="meta-board">
                <div class="meta-tile">
                  <span class="meta-name">统计区间</span>
                  <span class="meta-copy">{escape(context['report_range'])}</span>
                </div>
                <div class="meta-tile">
                  <span class="meta-name">生成时间</span>
                  <span class="meta-copy">{escape(metadata['generated_at'])}</span>
                </div>
                <div class="meta-tile">
                  <span class="meta-name">客户</span>
                  <span class="meta-copy">{escape(metadata['customer'])}</span>
                </div>
                <div class="meta-tile">
                  <span class="meta-name">JumpServer</span>
                  <span class="meta-copy">{escape(metadata['base_url'])}</span>
                </div>
              </div>
              <div class="runtime-list">
                <span class="runtime-pill">Company：{escape(metadata['company'])}</span>
                <span class="runtime-pill">Theme：{escape(metadata['theme_color'])}</span>
              </div>
            </section>
          </aside>
        </div>
        {render_notice_block(context.get('report_notice_items', []))}
      </header>

      <section class="section-flow" id="situation">
        <div class="section-heading">
          <div>
            <div class="section-index">01 / Situation</div>
            <h2 class="section-title">态势总览</h2>
          </div>
          <p class="section-caption">先给出风险级别、异常聚焦和最值得注意的结论，减少用户在长报告里自己找重点的成本。</p>
        </div>
        {render_summary_callouts(summary_callouts)}
        <div class="panel-grid">
        <article class="panel panel-strong span-12">
          <div class="panel-body">
            <p class="panel-kicker">Security Posture</p>
            <h2>核心态势指标</h2>
            <p class="panel-summary">将风险、登录、会话、命令巡检和审计记录压缩成一排可快速扫描的指标卡。</p>
            <div class="metrics">{render_metric_cards(overview_cards)}</div>
          </div>
        </article>

        <article class="panel span-7">
          <div class="panel-body">
            <p class="panel-kicker">Focus</p>
            <h2>异常聚焦</h2>
            <p class="panel-summary">合并登录失败、异常资产、高风险会话与命令巡检异常，作为值班排查的第一入口。</p>
            {render_html_table_block(
                [("异常等级", "level"), ("异常节点", "node"), ("异常描述", "description")],
                anomaly_rows,
                "当前未发现需要升级处理的异常。"
            )}
          </div>
        </article>

        <article class="panel panel-dark span-5">
          <div class="panel-body">
            <p class="panel-kicker">Findings</p>
            <h2>关键发现</h2>
            <p class="panel-summary">把当日最值得在晨会或交班里直接引用的结论单独摘出来。</p>
            {render_html_list(context['key_findings_items'])}
            <div class="signal-list">
              <span class="signal-pill">客户：{escape(metadata['customer'])}</span>
              <span class="signal-pill">公司：{escape(metadata['company'])}</span>
            </div>
          </div>
        </article>

        <article class="panel span-7">
          <div class="panel-body">
            <p class="panel-kicker">Risk Surface</p>
            <h2>安全风险摘要</h2>
            <p class="panel-summary">汇总爆破线索、高风险会话、命令异常和危险操作，形成可交付的风险面概览。</p>
            {render_html_list(context['security_risk_items'], "今日未识别出显著安全风险。")}
          </div>
        </article>

        <article class="panel span-5">
          <div class="panel-body">
            <p class="panel-kicker">Assets</p>
            <h2>资产状态</h2>
            <p class="panel-summary">展示纳管资产基础状态，便于在总览层先确认平台覆盖面与异常资产分布。</p>
            {render_html_table_block(
                scoped_headers([("机器名", "name"), ("机器类型", "platform"), ("机器 IP", "ip"), ("机器端口", "port"), ("SSH 用户名", "username"), ("是否有效", "enabled"), ("状态", "status")], asset_rows),
                asset_rows,
                "当前未查询到资产数据。"
            )}
          </div>
        </article>
        </div>
      </section>

      <section class="section-flow" id="evidence">
        <div class="section-heading">
          <div>
            <div class="section-index">02 / Evidence</div>
            <h2 class="section-title">主机证据</h2>
          </div>
          <p class="section-caption">把命令巡检摘要、磁盘高水位和原始命令输出放在同一层，方便快速复核采集链路与系统运行态。</p>
        </div>
        <div class="panel-grid">
        <article class="panel span-4">
          <div class="panel-body">
            <p class="panel-kicker">Command Inspection</p>
            <h2>系统命令巡检</h2>
            <p class="panel-summary">主机级证据摘要，适合先确认命令采集成功率、异常数量与目标覆盖情况。</p>
            {render_html_list(context['command_stats']['summary_items'], "当前未配置系统命令巡检。")}
          </div>
        </article>

        <article class="panel span-8">
          <div class="panel-body">
            <p class="panel-kicker">Filesystem</p>
            <h2>磁盘使用率</h2>
            <p class="panel-summary">聚焦 `df -Th` 结果中的高水位挂载点，异常文件系统通常是故障前的第一类信号。</p>
            {render_html_table_block(
                [("节点", "target_name"), ("文件系统", "filesystem"), ("类型", "type"), ("总量", "size"), ("已用", "used"), ("可用", "avail"), ("使用率", "usage"), ("挂载点", "mount")],
                [
                    {
                        "target_name": row["target_name"],
                        "filesystem": row["filesystem"],
                        "type": row["type"],
                        "size": row["size"],
                        "used": row["used"],
                        "avail": row["avail"],
                        "usage": f"{row['usage']}%",
                        "mount": row["mount"],
                    }
                    for row in filesystem_rows
                ],
                "当前未采集到 df -Th 输出或未识别出有效文件系统数据。"
            )}
          </div>
        </article>

        <article class="panel panel-dark span-12">
          <div class="panel-body">
            <p class="panel-kicker">Evidence</p>
            <h2>命令输出样本</h2>
            <p class="panel-summary">保留关键命令原始输出，供运维和安全侧在不切回终端的情况下直接复核证据。</p>
            <div class="command-grid">{render_command_cards(command_rows)}</div>
          </div>
        </article>
        </div>
      </section>

      <section class="section-flow" id="audit">
        <div class="section-heading">
          <div>
            <div class="section-index">03 / Access And Audit</div>
            <h2 class="section-title">访问与审计</h2>
          </div>
          <p class="section-caption">最后展开账号访问、在线会话和高风险操作，既适合当天排查，也适合作为归档版巡检日报。</p>
        </div>
        <div class="panel-grid">
        <article class="panel span-6">
          <div class="panel-body">
            <p class="panel-kicker">Access</p>
            <h2>登录异常</h2>
            <p class="panel-summary">优先展示失败明细，便于判断是否存在爆破、凭据异常、误配置或接入侧故障。</p>
            {render_html_table_block(
                scoped_headers([("时间", "time"), ("用户", "username"), ("来源 IP", "ip"), ("原因", "message")], login_failure_rows),
                login_failure_rows,
                "今日未发现登录失败记录。"
            )}
          </div>
        </article>

        <article class="panel span-6">
          <div class="panel-body">
            <p class="panel-kicker">Session</p>
            <h2>活跃会话</h2>
            <p class="panel-summary">聚焦当前在线连接与来源地址，适合值班人员临时排查敏感时段和异常来源。</p>
            {render_html_table_block(
                scoped_headers([("用户", "username"), ("目标资产", "asset"), ("来源 IP", "remote_addr"), ("协议", "protocol"), ("开始时间", "start_at")], session_rows),
                session_rows,
                "当前无活跃会话。"
            )}
          </div>
        </article>

        <article class="panel span-7">
          <div class="panel-body">
            <p class="panel-kicker">Audit</p>
            <h2>高风险操作审计</h2>
            <p class="panel-summary">提取 delete、remove、drop 等高风险动作，适合作为值班复核和留痕依据。</p>
            {render_html_table_block(
                scoped_headers([("时间", "time"), ("用户", "username"), ("动作", "action"), ("对象", "target")], dangerous_rows),
                dangerous_rows,
                "未发现高风险操作审计记录。"
            )}
          </div>
        </article>

        <article class="panel panel-dark span-5">
          <div class="panel-body">
            <p class="panel-kicker">Action</p>
            <h2>处置建议</h2>
            <p class="panel-summary">按当前风险面给出可直接执行的后续动作，适合交班时抄走就用。</p>
            {render_html_list(context['recommendation_items'])}
          </div>
        </article>

        <article class="panel span-12">
          <div class="panel-body">
            <p class="panel-kicker">Runtime</p>
            <h2>巡检说明</h2>
            <p class="panel-summary">记录采集来源、输出链路与运行上下文，便于归档、转发和后续复跑追踪。</p>
            {render_html_list(context['report_notice_items'], "本次巡检数据采集与渲染链路正常。")}
            <div class="runtime-list">
              <span class="runtime-pill">Profile：{escape(metadata['profile_name'])}</span>
              <span class="runtime-pill">组织范围：{escape(metadata['scope_name'])}</span>
              <span class="runtime-pill">环境文件：{escape(metadata['profile_source'])}</span>
              <span class="runtime-pill">报告日期：{escape(metadata['report_date'])}</span>
            </div>
          </div>
        </article>
        </div>
      </section>

      <div class="footer-bar">
        <div><strong>{escape(metadata['company'])}</strong> / JumpServer Inspection Report</div>
        <div>{escape(metadata['generated_at'])}</div>
      </div>
    </div>
  </main>
</body>
</html>
"""


def render_markdown_table(headers: List[str], rows: List[Dict[str, Any]], empty_text: str = "暂无数据。") -> str:
    if not rows:
        return empty_text
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(str(row.get(key, "-")).replace("\n", "<br>") for key in headers) + " |")
    return "\n".join([head, sep, *body])


def default_top_n() -> int:
    return parse_int_env("JMS_DEFAULT_TOP_N", DEFAULT_TOP_N)


def build_analysis_rows(counter: Counter[str], label: str, top_n: int) -> List[Dict[str, Any]]:
    return [
        {"排名": index, label: key, "次数": count}
        for index, (key, count) in enumerate(counter.most_common(top_n), start=1)
    ]


def find_asset_matches(rows: List[Dict[str, Any]], host: str) -> List[Dict[str, Any]]:
    needle = host.strip().lower()
    matches: List[Dict[str, Any]] = []
    for row in rows:
        candidates = [
            str(row.get("asset", "")).strip().lower(),
            str(row.get("name", "")).strip().lower(),
            str(row.get("ip", "")).strip().lower(),
            str(row.get("hostname", "")).strip().lower(),
        ]
        if needle and needle in candidates:
            matches.append(row)
    return matches


def build_host_probe_target(host: str, org_id: Optional[str]) -> Dict[str, Any]:
    asset_id, asset_name = resolve_exact_asset_id(host, org_id=org_id)
    account_name = get_runtime_env("JMS_EXEC_ACCOUNT_NAME")
    if not account_name:
        raise JumpServerApiError("执行主机负载巡检前，请先配置 JMS_EXEC_ACCOUNT_NAME。")
    account_id, _ = resolve_exact_account_id(account_name, asset_id=asset_id, org_id=org_id)
    return {
        "name": asset_name,
        "asset": asset_id,
        "account": account_id,
        "protocol": get_runtime_env("JMS_EXEC_PROTOCOL", "ssh") or "ssh",
        "input_username": get_runtime_env("JMS_EXEC_USERNAME", account_name) or account_name,
        "input_secret": get_runtime_env("JMS_EXEC_SECRET"),
        "connect_method": get_runtime_env("JMS_EXEC_CONNECT_METHOD", "web_cli") or "web_cli",
        "connect_options": dict(DEFAULT_CONNECT_OPTIONS),
        "timeout": parse_int_env("JMS_EXEC_TIMEOUT", DEFAULT_COMMAND_TIMEOUT),
        "commands": ["uptime"],
        "org_id": org_id,
    }


def run_host_load_probe(host: str, org_id: Optional[str]) -> Dict[str, Any]:
    target = build_host_probe_target(host, org_id=org_id)
    evidence = collect_command_evidence([target])[0]
    if evidence.get("status") != "ok":
        raise JumpServerApiError(humanize_value(evidence.get("error"), default="主机负载采集失败"))
    output = evidence.get("results", [{}])[0].get("output", "未采集到 uptime 输出。")
    return {
        "host": target["name"],
        "command": "uptime",
        "output": output,
    }


def format_org_summary(contexts: List[Dict[str, Any]], top_n: int) -> str:
    chunks: List[str] = []
    for context in contexts:
        user_rows = build_analysis_rows(context["login_stats"]["all_users"], "用户", top_n)
        asset_rows = build_analysis_rows(context["login_stats"]["all_assets"], "资产", top_n)
        chunks.append(
            f"### {context['org_name']}\n"
            f"{render_markdown_table(['排名', '用户', '次数'], user_rows, '暂无登录用户排行。')}\n\n"
            f"{render_markdown_table(['排名', '资产', '次数'], asset_rows, '暂无资产排行。')}"
        )
    return "\n\n".join(chunks)


def analyze_context(context: Dict[str, Any], analysis_type: str, top_n: int, host: Optional[str] = None) -> Dict[str, Any]:
    if analysis_type == "login-anomalies":
        rows = context["login_stats"]["failure_details"][:top_n]
        markdown = render_markdown_table(["time", "username", "asset", "ip", "message"], rows, "未发现异常登录。")
        summary = f"时间范围内共发现 {context['login_stats']['failure']} 条登录失败记录。"
        return {"type": analysis_type, "summary": summary, "table": markdown, "rows": rows}

    if analysis_type == "top-users":
        rows = build_analysis_rows(context["login_stats"]["all_users"], "用户", top_n)
        summary = f"时间范围内共统计到 {len(rows)} 个高频登录用户候选。"
        markdown = render_markdown_table(["排名", "用户", "次数"], rows, "暂无登录用户排行。")
        if context["org_contexts"]:
            markdown = markdown + "\n\n" + format_org_summary(context["org_contexts"], top_n)
        return {"type": analysis_type, "summary": summary, "table": markdown, "rows": rows}

    if analysis_type == "top-assets":
        counter = Counter(context["login_stats"]["all_assets"])
        if not counter:
            counter.update(context["session_stats"]["asset_counter"])
        rows = build_analysis_rows(counter, "资产", top_n)
        summary = f"时间范围内共统计到 {len(rows)} 个高频登录资产候选。"
        markdown = render_markdown_table(["排名", "资产", "次数"], rows, "暂无资产排行。")
        if context["org_contexts"]:
            per_org: List[str] = []
            for org_context in context["org_contexts"]:
                local_counter = Counter(org_context["login_stats"]["all_assets"])
                if not local_counter:
                    local_counter.update(org_context["session_stats"]["asset_counter"])
                local_rows = build_analysis_rows(local_counter, "资产", top_n)
                per_org.append(f"### {org_context['org_name']}\n{render_markdown_table(['排名', '资产', '次数'], local_rows, '暂无资产排行。')}")
            markdown = markdown + "\n\n" + "\n\n".join(per_org)
        return {"type": analysis_type, "summary": summary, "table": markdown, "rows": rows}

    if analysis_type == "host-usage":
        if not host:
            raise JumpServerApiError("host-usage 分析需要提供 --host。")
        session_rows = [row for row in context["session_stats"]["rows"] if host.lower() in str(row.get("asset", "")).lower()]
        load_info = run_host_load_probe(host, context.get("org_id"))
        summary = f"{host} 当前活跃会话 {len(session_rows)} 个，负载采样命令为 uptime。"
        markdown = (
            "### 负载情况\n"
            f"```text\n{load_info['output']}\n```\n\n"
            "### 正在使用该资产的会话\n"
            f"{render_markdown_table(['username', 'asset', 'remote_addr', 'protocol', 'start_at'], session_rows, '当前未发现活跃会话。')}"
        )
        return {
            "type": analysis_type,
            "summary": summary,
            "table": markdown,
            "rows": session_rows,
            "load": load_info,
        }

    raise JumpServerApiError(f"未知分析类型：{analysis_type}")


def load_docx_library():
    try:
        module = importlib.import_module("docx")
    except Exception:
        maybe_auto_install("docx")
        module = importlib.import_module("docx")
    return module


def load_pdf_library():
    try:
        module = importlib.import_module("pypdf")
    except Exception:
        maybe_auto_install("pdf")
        module = importlib.import_module("pypdf")
    return module


def replace_placeholders(text: str, values: Dict[str, str]) -> str:
    result = text
    for key, value in values.items():
        result = result.replace(f"{{{{ {key} }}}}", value).replace(f"{{{{{key}}}}}", value)
    return result


def template_context_values(context: Dict[str, Any]) -> Dict[str, str]:
    return {
        "report_date": context["report_date"],
        "report_range": f"{context['date_from']} 至 {context['date_to']}",
        "profile_name": context["metadata"]["profile_name"],
        "scope_name": context["metadata"]["scope_name"],
        "command_summary": context["command_summary"],
        "report_notices": context["report_notices"],
        "today_login_logs": context["today_login_logs"],
        "asset_status": context["asset_status"],
        "active_sessions": context["active_sessions"],
        "operate_logs": context["operate_logs"],
        "security_risk_summary": context["security_risk_summary"],
        "risk_level": context["risk_level"],
        "executive_summary": context["executive_summary"],
        "key_findings": context["key_findings"],
        "recommendations": context["recommendations"],
    }


def standard_template_sections(context: Dict[str, Any]) -> List[Tuple[str, str]]:
    return [
        ("巡检概览", context["executive_summary"]),
        ("管理摘要", context["executive_summary"]),
        ("系统命令巡检", context["command_summary"]),
        ("关键发现", context["key_findings"]),
        ("登录情况", context["today_login_logs"]),
        ("活跃会话", context["active_sessions"]),
        ("资产状态", context["asset_status"]),
        ("操作审计", context["operate_logs"]),
        ("安全风险摘要", context["security_risk_summary"]),
        ("巡检说明", context["report_notices"]),
        ("处置建议", context["recommendations"]),
    ]


def paragraph_is_heading(paragraph: Any) -> bool:
    style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
    text = paragraph.text.strip()
    return style_name.lower().startswith("heading") or bool(re.match(r"^[一二三四五六七八九十0-9]+[、.\s]", text))


def insert_paragraph_after(paragraph: Any, text: str = "", style: Optional[str] = None) -> Any:
    docx_text = importlib.import_module("docx.text.paragraph")
    docx_oxml = importlib.import_module("docx.oxml")
    new_p = docx_oxml.OxmlElement("w:p")
    paragraph._p.addnext(new_p)
    new_para = docx_text.Paragraph(new_p, paragraph._parent)
    if style:
        try:
            new_para.style = style
        except Exception:  # noqa: BLE001
            pass
    if text:
        new_para.add_run(text)
    return new_para


def fill_docx_document(document: Any, context: Dict[str, Any]) -> None:
    values = template_context_values(context)
    section_map = standard_template_sections(context)
    matched_sections: set[str] = set()

    for paragraph in document.paragraphs:
        if paragraph.text:
            replaced = replace_placeholders(paragraph.text, values)
            if replaced != paragraph.text:
                paragraph.text = replaced

    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    if paragraph.text:
                        replaced = replace_placeholders(paragraph.text, values)
                        if replaced != paragraph.text:
                            paragraph.text = replaced

    for index, paragraph in enumerate(document.paragraphs):
        heading_text = paragraph.text.strip()
        if not heading_text:
            continue
        for title, content in section_map:
            if title not in heading_text:
                continue
            matched_sections.add(title)
            next_paragraph = document.paragraphs[index + 1] if index + 1 < len(document.paragraphs) else None
            if next_paragraph and not paragraph_is_heading(next_paragraph):
                if (not next_paragraph.text.strip()) or "{{" in next_paragraph.text or any(token in next_paragraph.text for token in ("待补充", "TODO", "请填写")):
                    next_paragraph.text = content
                else:
                    insert_paragraph_after(paragraph, content)
            else:
                insert_paragraph_after(paragraph, content)
            break

    for title, content in section_map:
        if title in matched_sections:
            continue
        document.add_heading(title, level=2)
        for line in content.splitlines():
            document.add_paragraph(line)


def convert_doc_to_docx(input_file: Path) -> Path:
    maybe_auto_install("pdf")
    binary = shutil.which("soffice") or shutil.which("libreoffice")
    if not binary:
        install_system_package("libreoffice")
        binary = shutil.which("soffice") or shutil.which("libreoffice")
    if not binary:
        raise JumpServerApiError("未找到可用的 LibreOffice/soffice，无法转换 .doc 模板。")

    output_dir = Path(tempfile.mkdtemp(prefix="jms-docx-"))
    subprocess.run(
        [binary, "--headless", "--convert-to", "docx", "--outdir", str(output_dir), str(input_file)],
        check=True,
    )
    output_file = output_dir / f"{input_file.stem}.docx"
    if not output_file.exists():
        raise JumpServerApiError("`.doc` 转换为 `.docx` 失败。")
    return output_file


def extract_pdf_text(input_file: Path) -> str:
    module = load_pdf_library()
    reader = module.PdfReader(str(input_file))
    chunks = []
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
    return "\n".join(chunks).strip()


def default_filled_output(input_file: Path) -> Path:
    suffix = ".docx" if input_file.suffix.lower() in (".doc", ".pdf") else input_file.suffix.lower()
    return FILLED_TEMPLATE_DIR / f"{input_file.stem}_filled{suffix}"


def fill_template_artifact(
    profile: Optional[str],
    date_from: str,
    date_to: str,
    input_file: str,
    output_file: Optional[str],
    org_name: Optional[str],
    all_orgs: bool,
) -> Tuple[Path, str]:
    profile_name, _ = activate_profile(profile)
    context = build_data_bundle(
        report_date=date_to,
        profile_name=profile_name,
        org_name=org_name,
        all_orgs=all_orgs,
        date_from=date_from,
        date_to=date_to,
    )
    source = Path(input_file).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"模板文件不存在：{source}")

    target = Path(output_file).expanduser().resolve() if output_file else default_filled_output(source)
    ensure_parent_dir(target)
    suffix = source.suffix.lower()

    if suffix == ".docx":
        docx = load_docx_library()
        document = docx.Document(str(source))
        fill_docx_document(document, context)
        document.save(str(target))
        return target, "docx"

    if suffix == ".doc":
        converted = convert_doc_to_docx(source)
        docx = load_docx_library()
        document = docx.Document(str(converted))
        fill_docx_document(document, context)
        target = target.with_suffix(".docx")
        document.save(str(target))
        return target, "docx"

    if suffix == ".pdf":
        text = extract_pdf_text(source)
        docx = load_docx_library()
        document = docx.Document()
        document.add_heading(source.stem, level=1)
        if text:
            document.add_paragraph("原始 PDF 模板摘录")
            for line in text.splitlines()[:80]:
                if line.strip():
                    document.add_paragraph(line.strip())
        fill_docx_document(document, context)
        target = target.with_suffix(".docx")
        document.save(str(target))
        return target, "docx"

    raise JumpServerApiError("当前仅支持 `.doc`、`.docx`、`.pdf` 模板。")


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


def output_report(report_text: str, output_file: Path, report_format: str, print_stdout: bool = True) -> Path:
    ensure_parent_dir(output_file)
    output_file.write_text(report_text, encoding="utf-8")
    sync_latest_output(report_text, report_format)
    if print_stdout:
        if report_format == "html":
            print(str(output_file))
        else:
            print(report_text)
    return output_file


def load_state(state_file: Path = DEFAULT_STATE_FILE) -> Dict[str, Any]:
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_state(data: Dict[str, Any], state_file: Path = DEFAULT_STATE_FILE) -> None:
    ensure_parent_dir(state_file)
    state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def setup_daily_push(
    hour: int = 8,
    minute: int = 0,
    template: str = DEFAULT_TEMPLATE_NAME,
    template_file: Path = USER_TEMPLATE_FILE,
    open_id: Optional[str] = None,
    group_id: Optional[str] = None,
    output_file: Path = DEFAULT_OUTPUT_FILE,
    profile: Optional[str] = None,
    org_name: Optional[str] = None,
    all_orgs: bool = False,
) -> Dict[str, Any]:
    state = {
        "hour": hour,
        "minute": minute,
        "template": template,
        "template_file": str(template_file),
        "open_id": open_id,
        "group_id": group_id,
        "output_file": str(output_file),
        "profile": profile,
        "org_name": org_name,
        "all_orgs": all_orgs,
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


def run_once(
    template_file: Path,
    open_id: Optional[str] = None,
    group_id: Optional[str] = None,
    profile: Optional[str] = None,
    org_name: Optional[str] = None,
    all_orgs: bool = False,
) -> Dict[str, Any]:
    profile_name, _ = activate_profile(profile)
    template_text = load_template(template_file)
    context = build_data_bundle(today_str(), profile_name, org_name=org_name, all_orgs=all_orgs)
    mode = detect_template_mode(template_text)
    report = render_placeholder_template(template_text, context) if mode == "placeholder" else render_natural_language_template(template_text, context)
    output_report(report, output_file=DEFAULT_OUTPUT_FILE, report_format="markdown", print_stdout=False)
    payload = send_rich_text(report, open_id=open_id, group_id=group_id)
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    return payload


def run_daemon(
    hour: int,
    minute: int,
    template_file: Path,
    open_id: Optional[str] = None,
    group_id: Optional[str] = None,
    profile: Optional[str] = None,
    org_name: Optional[str] = None,
    all_orgs: bool = False,
) -> None:
    print(json.dumps({
        "status": "daemon_started",
        "hour": hour,
        "minute": minute,
        "template_file": str(template_file),
        "open_id": open_id,
        "group_id": group_id,
        "profile": profile,
        "org_name": org_name,
        "all_orgs": all_orgs,
    }, ensure_ascii=False), flush=True)
    while True:
        wait_seconds = seconds_until(hour, minute)
        time.sleep(wait_seconds)
        try:
            run_once(template_file, open_id=open_id, group_id=group_id, profile=profile, org_name=org_name, all_orgs=all_orgs)
        except Exception:  # noqa: BLE001
            print(DEFAULT_ERROR_MESSAGE, flush=True)
            time.sleep(60)


def self_improve(instruction: str, skill_dir: Path = SKILL_DIR) -> Dict[str, Any]:
    note_file = ensure_parent_dir(skill_dir / "runtime" / "self_improve.todo.md")
    history = []
    if note_file.exists():
        history.append(note_file.read_text(encoding="utf-8"))
    history.append(
        f"## {datetime.now().isoformat()}\n"
        f"- 指令：{instruction}\n"
        f"- 状态：待修改 scripts/jms_inspection.py 并在下一个 turn 重新加载 Skill。\n"
    )
    note_file.write_text("\n".join(history), encoding="utf-8")
    return {
        "status": "queued",
        "message": "已记录优化需求，请继续修改 scripts/jms_inspection.py。",
        "instruction": instruction,
        "note_file": str(note_file),
    }


def update_token_instruction(profile: Optional[str] = None) -> str:
    if profile:
        return (
            f"请更新 profile `{profile}` 对应的环境文件中的 "
            "JUMPSERVER_TOKEN，或更新 JUMPSERVER_KEY_ID / JUMPSERVER_SECRET_ID，"
            "然后重新执行 report/self-test。"
        )
    return "请在运行环境中重新设置 JUMPSERVER_TOKEN，或重新设置 JUMPSERVER_KEY_ID / JUMPSERVER_SECRET_ID，然后重试。"


def build_report_artifact(
    report_date: str,
    report_format: str,
    profile: Optional[str],
    template_file: Optional[str],
    output_file: Optional[str],
    legacy: bool,
    style: str = "modern",
    org_name: Optional[str] = None,
    all_orgs: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Tuple[str, Path]:
    profile_name, _ = activate_profile(profile)
    date_from = date_from or report_date
    date_to = date_to or report_date
    target = resolve_output_file(output_file, report_format=report_format, profile_name=profile_name, legacy=legacy)

    if report_format == "html":
        if style == "legacy":
            if get_legacy_provider() == "official":
                official_payload = run_official_legacy_probe(profile_name, output_target=target, check_only=False)
                report_text = str(official_payload.get("html_text") or "")
            else:
                report_text = render_legacy_html_report(
                    report_date,
                    profile_name,
                    org_name=org_name,
                    all_orgs=all_orgs,
                    date_from=date_from,
                    date_to=date_to,
                )
        else:
            report_text = render_html_report(
                report_date,
                profile_name,
                org_name=org_name,
                all_orgs=all_orgs,
                date_from=date_from,
                date_to=date_to,
            )
    else:
        template_path = resolve_template_file(template_file)
        template_text = load_template(template_path)
        context = build_data_bundle(
            report_date,
            profile_name,
            org_name=org_name,
            all_orgs=all_orgs,
            date_from=date_from,
            date_to=date_to,
        )
        mode = detect_template_mode(template_text)
        report_text = render_placeholder_template(template_text, context) if mode == "placeholder" else render_natural_language_template(template_text, context)

    return report_text, output_report(report_text, output_file=target, report_format=report_format, print_stdout=True)


def cmd_report(args: argparse.Namespace) -> int:
    try:
        report_date = args.to_date or args.date
        build_report_artifact(
            report_date=report_date,
            report_format=args.format,
            profile=args.profile,
            template_file=args.template_file,
            output_file=args.output_file,
            legacy=False,
            style=args.style,
            org_name=args.org_name,
            all_orgs=args.all_orgs,
            date_from=args.from_date,
            date_to=args.to_date or report_date,
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        print(str(exc) or DEFAULT_ERROR_MESSAGE, file=sys.stderr)
        return 1


def cmd_generate(args: argparse.Namespace) -> int:
    try:
        report_date = parse_date(args.to_date or args.date).strftime("%Y-%m-%d") if (args.to_date or args.date) else today_str()
        build_report_artifact(
            report_date=report_date,
            report_format=args.format,
            profile=args.profile,
            template_file=args.template_file,
            output_file=args.output_file,
            legacy=True,
            style=args.style,
            org_name=args.org_name,
            all_orgs=args.all_orgs,
            date_from=args.from_date,
            date_to=args.to_date or report_date,
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        print(str(exc) or DEFAULT_ERROR_MESSAGE, file=sys.stderr)
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
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1


def cmd_save_config(args: argparse.Namespace) -> int:
    try:
        if args.profile:
            profile_path = Path(args.profile).expanduser()
            if profile_path.exists():
                activate_profile(args.profile)
        elif RUNTIME_PROFILE.get("source"):
            activate_profile(args.profile)
        updates = parse_key_value_pairs(args.entry)
        path = persist_runtime_settings(updates, profile=args.profile)
        print(json.dumps({
            "profile": args.profile or RUNTIME_PROFILE.get("name"),
            "env_file": str(path),
            "saved_keys": sorted(updates.keys()),
        }, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(str(exc) or DEFAULT_ERROR_MESSAGE, file=sys.stderr)
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
            output_file=resolve_output_file(args.output_file, report_format="markdown", profile_name=args.profile or "default", legacy=True),
            profile=args.profile,
            org_name=args.org_name,
            all_orgs=args.all_orgs,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("注意：真正的定时运行请使用 daemon 子命令并保持进程常驻。")
        return 0
    except Exception:  # noqa: BLE001
        print(DEFAULT_ERROR_MESSAGE, file=sys.stderr)
        return 1


def cmd_daemon(args: argparse.Namespace) -> int:
    try:
        run_daemon(
            hour=args.hour,
            minute=args.minute,
            template_file=resolve_template_file(args.template_file),
            open_id=args.open_id,
            group_id=args.group_id,
            profile=args.profile,
            org_name=args.org_name,
            all_orgs=args.all_orgs,
        )
        return 0
    except Exception:  # noqa: BLE001
        print(DEFAULT_ERROR_MESSAGE, file=sys.stderr)
        return 1


def cmd_send_payload(args: argparse.Namespace) -> int:
    report_file = Path(args.report_file).expanduser().resolve() if args.report_file else DEFAULT_OUTPUT_FILE
    payload = send_rich_text(
        markdown=report_file.read_text(encoding="utf-8"),
        title=args.title,
        open_id=args.open_id,
        group_id=args.group_id,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_self_improve(args: argparse.Namespace) -> int:
    print(json.dumps(self_improve(args.instruction), ensure_ascii=False, indent=2))
    return 0


def cmd_update_token(args: argparse.Namespace) -> int:
    print(update_token_instruction(profile=args.profile))
    return 0


def cmd_list_orgs(args: argparse.Namespace) -> int:
    try:
        activate_profile(args.profile)
        rows = list_organizations()
        print(json.dumps({"profile": args.profile or RUNTIME_PROFILE.get("name"), "organizations": rows}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(str(exc) or DEFAULT_ERROR_MESSAGE, file=sys.stderr)
        return 1


def cmd_self_test(args: argparse.Namespace) -> int:
    try:
        profile_name, _ = activate_profile(args.profile)
        cfg = get_env_config()
        legacy_provider = get_legacy_provider()
        scopes = resolve_org_scopes(org_name=args.org_name, all_orgs=args.all_orgs)
        org_id = scopes[0]["id"] if len(scopes) == 1 else None
        assets, assets_error = safe_fetch(lambda: get_assets(org_id=org_id), "资产接口不可用")
        sessions, sessions_error = safe_fetch(lambda: get_active_sessions(org_id=org_id), "活跃会话接口不可用")
        logins, logins_error = safe_fetch(lambda: get_login_logs(args.date or today_str(), org_id=org_id), "登录日志接口不可用")
        operates, operates_error = safe_fetch(lambda: get_operate_logs(args.date or today_str(), org_id=org_id), "操作审计接口不可用")
        command_state = get_command_target_state()
        command_targets = command_state.get("targets", [])
        command_error = get_command_execution_error(command_targets)
        legacy_remote_config_ready = False
        legacy_remote_config_error = None
        legacy_db_ready = False
        legacy_db_error = None
        legacy_db_config = None
        legacy_state: Dict[str, Any] = {"targets": [], "resolution_mode": None, "error": None}
        legacy_targets: List[Dict[str, Any]] = []
        if legacy_provider == "python":
            legacy_state = get_legacy_system_target_state()
            legacy_targets = legacy_state.get("targets", [])
            legacy_remote_config_error = legacy_state.get("error")
            if legacy_targets and not legacy_state.get("error"):
                evidence = collect_command_evidence([legacy_targets[0]])
                if evidence and evidence[0].get("status") == "ok":
                    snapshot = parse_system_target_snapshot(legacy_targets[0], evidence[0])
                    try:
                        resolved_db = resolve_legacy_db_config([snapshot])
                        execute_sql_row(resolved_db, "rds_status.sql", {})
                        legacy_remote_config_ready = bool(snapshot.get("remote_config_text") or resolved_db.get("source") == "local_override")
                        legacy_db_ready = True
                        legacy_db_config = {
                            "engine": resolved_db.get("engine"),
                            "host": resolved_db.get("host"),
                            "port": resolved_db.get("port"),
                            "name": resolved_db.get("name"),
                            "source": resolved_db.get("source"),
                        }
                    except Exception as exc:  # noqa: BLE001
                        legacy_db_error = str(exc)
                        if "config" in str(exc).lower():
                            legacy_remote_config_error = str(exc)
                else:
                    legacy_remote_config_error = humanize_value(evidence[0].get("error") if evidence else legacy_state.get("error"), default="远程命令执行失败")

        official_binary_ready = False
        official_binary_error = None
        official_binary_info: Dict[str, Any] = {}
        official_ssh_ready = False
        official_ssh_error = None
        official_ssh_config: Dict[str, Any] = {}
        official_probe_ready = False
        official_probe_error = None
        official_probe: Dict[str, Any] = {}
        try:
            official_binary_info = prepare_official_runtime_binary()
            official_binary_ready = True
        except Exception as exc:  # noqa: BLE001
            official_binary_error = str(exc)
        try:
            official_ssh_config = get_official_ssh_config()
            official_ssh_ready = True
        except Exception as exc:  # noqa: BLE001
            official_ssh_error = str(exc)
        if official_binary_ready and official_ssh_ready:
            try:
                official_probe = run_official_legacy_probe(profile_name, check_only=True)
                official_probe_ready = True
            except Exception as exc:  # noqa: BLE001
                official_probe_error = str(exc)

        result = {
            "profile": args.profile or RUNTIME_PROFILE.get("name"),
            "date": args.date or today_str(),
            "org_scope": scope_label(scopes),
            "legacy_provider": legacy_provider,
            "auth_mode": cfg.get("auth_mode"),
            "auth_source": cfg.get("auth_source"),
            "access_key_ready": bool(cfg.get("key_id") and cfg.get("secret_id")),
            "access_key_persist_message": cfg.get("persist_message"),
            "assets_count": len(assets),
            "active_sessions_count": len(sessions),
            "login_logs_count": len(logins),
            "operate_logs_count": len(operates),
            "command_targets_count": len(command_targets),
            "command_resolution_mode": command_state.get("resolution_mode"),
            "command_target_error": command_state.get("error"),
            "command_execution_ready": not bool(command_error) if command_targets else False,
            "command_execution_error": command_error,
            "legacy_system_targets_count": len(legacy_targets),
            "legacy_system_resolution_mode": legacy_state.get("resolution_mode"),
            "legacy_system_target_error": legacy_state.get("error"),
            "legacy_remote_config_ready": legacy_remote_config_ready,
            "legacy_remote_config_error": legacy_remote_config_error,
            "legacy_db_ready": legacy_db_ready,
            "legacy_db_error": legacy_db_error,
            "legacy_db_config": legacy_db_config,
            "official_binary_ready": official_binary_ready,
            "official_binary_error": official_binary_error,
            "official_binary_source": official_binary_info.get("source"),
            "official_runtime_binary": official_binary_info.get("runtime_path"),
            "official_ssh_ready": official_ssh_ready,
            "official_ssh_error": official_ssh_error,
            "official_ssh_target": f"{official_ssh_config.get('username', '')}@{official_ssh_config.get('host', '')}:{official_ssh_config.get('port', '')}" if official_ssh_config else None,
            "official_remote_config_path": official_ssh_config.get("remote_config_path") if official_ssh_config else None,
            "official_check_only_ready": official_probe_ready,
            "official_check_only_error": official_probe_error,
            "official_remote_platform": official_probe.get("remote_platform"),
            "assets_error": assets_error,
            "active_sessions_error": sessions_error,
            "login_logs_error": logins_error,
            "operate_logs_error": operates_error,
            "sample_asset": assets[0] if assets else None,
            "sample_session": sessions[0] if sessions else None,
            "sample_login": logins[0] if logins else None,
            "sample_command_target": sanitize_target_preview(command_targets[0]) if command_targets else None,
            "sample_legacy_target": sanitize_target_preview(legacy_targets[0]) if legacy_targets else None,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        healthy = not any([assets_error, sessions_error, logins_error, operates_error])
        if command_state.get("error"):
            healthy = False
        if command_targets and command_error:
            healthy = False
        if legacy_provider == "python" and (legacy_state.get("error") or (legacy_targets and (not legacy_remote_config_ready or not legacy_db_ready))):
            healthy = False
        if legacy_provider == "official" and (not official_binary_ready or not official_ssh_ready or not official_probe_ready):
            healthy = False
        return 0 if healthy else 1
    except Exception as exc:  # noqa: BLE001
        print(str(exc) or DEFAULT_ERROR_MESSAGE, file=sys.stderr)
        return 1


def cmd_exec_commands(args: argparse.Namespace) -> int:
    try:
        activate_profile(args.profile)
        command_state = get_command_target_state()
        targets = get_command_targets()
        if command_state.get("error"):
            raise JumpServerApiError(str(command_state["error"]))
        if args.target:
            targets = [item for item in targets if item["name"] == args.target]
        if not targets:
            raise JumpServerApiError("当前 profile 未配置可执行的命令巡检目标")
        precheck_error = get_command_execution_error(targets)
        if precheck_error:
            raise JumpServerApiError(precheck_error)

        override_commands = normalize_command_list(args.command or [])
        override_commands.extend(load_command_file(args.command_file or ""))
        if override_commands:
            for item in targets:
                item["commands"] = override_commands

        evidence = collect_command_evidence(targets)
        print(json.dumps({
            "profile": args.profile,
            "targets": evidence,
        }, ensure_ascii=False, indent=2))
        return 0 if all(item.get("status") == "ok" for item in evidence) else 1
    except Exception as exc:  # noqa: BLE001
        print(str(exc) or DEFAULT_ERROR_MESSAGE, file=sys.stderr)
        return 1


def cmd_analyze(args: argparse.Namespace) -> int:
    try:
        if args.analysis_type == "host-usage" and args.all_orgs:
            raise JumpServerApiError("host-usage 需要明确到单个组织，不能直接对全部组织执行。")
        top_n = args.top or default_top_n()
        profile_name, _ = activate_profile(args.profile)
        context = build_data_bundle(
            report_date=args.to_date,
            profile_name=profile_name,
            org_name=args.org_name,
            all_orgs=args.all_orgs,
            date_from=args.from_date,
            date_to=args.to_date,
        )
        result = analyze_context(context, args.analysis_type, top_n, host=args.host)
        payload = {
            "profile": args.profile,
            "org_scope": context["metadata"]["scope_name"],
            "date_from": args.from_date,
            "date_to": args.to_date,
            **result,
        }
        if args.format == "json":
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(
                f"# 分析结果\n\n"
                f"- 类型：{args.analysis_type}\n"
                f"- 组织范围：{payload['org_scope']}\n"
                f"- 时间范围：{args.from_date} 至 {args.to_date}\n"
                f"- 摘要：{result['summary']}\n\n"
                f"{result['table']}"
            )
        return 0
    except Exception as exc:  # noqa: BLE001
        print(str(exc) or DEFAULT_ERROR_MESSAGE, file=sys.stderr)
        return 1


def cmd_fill_template(args: argparse.Namespace) -> int:
    try:
        output_path, output_format = fill_template_artifact(
            profile=args.profile,
            date_from=args.from_date,
            date_to=args.to_date,
            input_file=args.input_file,
            output_file=args.output_file,
            org_name=args.org_name,
            all_orgs=args.all_orgs,
        )
        print(json.dumps({
            "profile": args.profile,
            "org_name": args.org_name,
            "all_orgs": args.all_orgs,
            "input_file": str(Path(args.input_file).expanduser().resolve()),
            "output_file": str(output_path),
            "output_format": output_format,
        }, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(str(exc) or DEFAULT_ERROR_MESSAGE, file=sys.stderr)
        return 1


def cmd_ensure_deps(args: argparse.Namespace) -> int:
    try:
        result = ensure_dependencies(args.target)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(str(exc) or DEFAULT_ERROR_MESSAGE, file=sys.stderr)
        return 1


def cmd_bootstrap(args: argparse.Namespace) -> int:
    try:
        ensure_parent_dir((PROFILE_DIR / ".gitkeep").resolve())
        ensure_parent_dir((REPORT_DIR / ".gitkeep").resolve())
        PLAYWRIGHT_BROWSERS_DIR.mkdir(parents=True, exist_ok=True)
        created_profile = False
        profile_path: Optional[Path] = None
        if args.profile:
            profile_path, created_profile = ensure_profile_from_example(args.profile, overwrite=args.overwrite_profile)
            activate_profile(args.profile)

        groups = ["db", "exec", "docx", "official"]
        if args.include_pdf:
            groups.append("pdf")
        deps_result = bootstrap_dependency_groups(groups)
        pending_profile_keys = detect_pending_profile_keys(profile_path)

        command_runtime_ready = False
        command_runtime_error = None
        try:
            ensure_command_runtime_ready()
            command_runtime_ready = True
        except Exception as exc:  # noqa: BLE001
            command_runtime_error = str(exc)

        official_binary_ready = False
        official_binary_error = None
        official_binary_info: Dict[str, Any] = {}
        try:
            official_binary_info = prepare_official_runtime_binary()
            official_binary_ready = True
        except Exception as exc:  # noqa: BLE001
            official_binary_error = str(exc)

        payload = {
            "profile": args.profile,
            "profile_file": str(profile_path) if profile_path else None,
            "profile_created": created_profile,
            "legacy_provider": get_legacy_provider(),
            "pending_profile_keys": pending_profile_keys,
            "dependency_groups": groups,
            "dependencies": deps_result,
            "command_runtime_ready": command_runtime_ready,
            "command_runtime_error": command_runtime_error,
            "official_binary_ready": official_binary_ready,
            "official_binary_error": official_binary_error,
            "official_binary_source": official_binary_info.get("source"),
            "official_runtime_binary": official_binary_info.get("runtime_path"),
            "playwright_browsers_path": str(PLAYWRIGHT_BROWSERS_DIR),
            "notes": [
                "bootstrap 默认安装 db+exec+docx+official，避免 fresh install 一上来就被按需补依赖打断。",
                "如需 PDF 模板补全，再追加 --include-pdf 或单独执行 ensure-deps pdf。",
                "playwright/chromium 浏览器缓存默认落在 runtime/.playwright-browsers，避免依赖用户全局缓存目录。",
                "exec 依赖现在会优先复用系统 Chrome/Chromium；只有本机没有可用浏览器时才尝试下载 Playwright Chromium，并会自动切换下载源。",
                "legacy 正式完整版默认走 official 引擎，需要额外补齐 JumpServer_IP、JMS_OFFICIAL_SSH_USERNAME、JMS_OFFICIAL_SSH_PASSWORD。",
            ],
            "next_steps": [
                f"编辑 {profile_path} 补齐 {', '.join(pending_profile_keys)}" if profile_path and pending_profile_keys else "",
                f"python3 scripts/jms_inspection.py list-orgs --profile {args.profile}" if args.profile else "",
                f"python3 scripts/jms_inspection.py self-test --profile {args.profile} --date {today_str()}" if args.profile else "",
            ],
        }
        payload["next_steps"] = [item for item in payload["next_steps"] if item]
        critical_failed_groups = [group for group in deps_result.get("failed_groups", []) if group != "exec"]
        if "exec" in deps_result.get("failed_groups", []):
            payload["notes"].append("exec 浏览器运行时暂未就绪，但不会阻塞 official legacy 正式报告、模板补全和大多数分析链路。")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if official_binary_ready and not critical_failed_groups else 1
    except Exception as exc:  # noqa: BLE001
        print(str(exc) or DEFAULT_ERROR_MESSAGE, file=sys.stderr)
        return 1


def add_org_scope_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--org-name", help="组织名称，精确匹配或唯一模糊匹配后执行")
    parser.add_argument("--all-orgs", action="store_true", help="对全部组织执行，输出先总览再分组织")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JumpServer 巡检报告生成与定时推送工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p_bootstrap = sub.add_parser("bootstrap", help="首次安装自举：准备 profile、运行时依赖、命令执行环境与 official 巡检引擎")
    p_bootstrap.add_argument("--profile", help="环境 profile 名称或 env 文件路径；传入时不存在则自动从 .env.example 创建")
    p_bootstrap.add_argument("--overwrite-profile", action="store_true", help="若 profile 已存在，允许用 .env.example 覆盖")
    p_bootstrap.add_argument("--include-pdf", action="store_true", help="额外安装 PDF 模板补全依赖，可能触发 libreoffice 安装")
    p_bootstrap.set_defaults(func=cmd_bootstrap)

    p_report = sub.add_parser("report", help="推荐入口：固定三个参数生成巡检报告")
    p_report.add_argument("profile", help="环境 profile 名称或 env 文件路径")
    p_report.add_argument("date", help="报告日期，格式 YYYY-MM-DD")
    p_report.add_argument("format", choices=("html", "markdown"), help="输出格式，推荐 html")
    p_report.add_argument("--template-file", help="Markdown 模板文件路径；仅 markdown 格式时生效")
    p_report.add_argument("--output-file", help="输出文件路径；留空时写入 runtime/reports/<profile>/")
    p_report.add_argument("--from", dest="from_date", help="报告开始日期，格式 YYYY-MM-DD；留空时按单日报告处理")
    p_report.add_argument("--to", dest="to_date", help="报告结束日期，格式 YYYY-MM-DD；留空时默认等于位置参数 date")
    p_report.add_argument("--style", choices=("modern", "legacy"), default=get_runtime_env("JMS_REPORT_STYLE", DEFAULT_REPORT_STYLE) or DEFAULT_REPORT_STYLE, help="HTML 报告样式：legacy 为 official 正式完整版，modern 为控制台摘要版")
    add_org_scope_args(p_report)
    p_report.set_defaults(func=cmd_report)

    p_generate = sub.add_parser("generate", help="兼容入口：默认生成 official HTML 正式巡检报告")
    p_generate.add_argument("--date", help="报告日期，格式 YYYY-MM-DD")
    p_generate.add_argument("--profile", help="环境 profile 名称或 env 文件路径")
    p_generate.add_argument("--format", choices=("markdown", "html"), default="html", help="输出格式；默认 html，markdown 仅用于显式模板场景")
    p_generate.add_argument("--template-file", help="模板文件路径；仅在显式 markdown 模板场景下使用")
    p_generate.add_argument("--output-file", help="输出文件路径；留空时写入 runtime/last_report.html 或 runtime/last_report.md")
    p_generate.add_argument("--from", dest="from_date", help="报告开始日期，格式 YYYY-MM-DD；留空时按单日报告处理")
    p_generate.add_argument("--to", dest="to_date", help="报告结束日期，格式 YYYY-MM-DD；留空时默认等于 --date 或今天")
    p_generate.add_argument("--style", choices=("modern", "legacy"), default=get_runtime_env("JMS_REPORT_STYLE", DEFAULT_REPORT_STYLE) or DEFAULT_REPORT_STYLE, help="HTML 报告样式：legacy 为 official 正式完整版，modern 为控制台摘要版")
    add_org_scope_args(p_generate)
    p_generate.set_defaults(func=cmd_generate)

    p_list_orgs = sub.add_parser("list-orgs", help="列出当前 profile 下可见的组织列表")
    p_list_orgs.add_argument("--profile", help="环境 profile 名称或 env 文件路径")
    p_list_orgs.set_defaults(func=cmd_list_orgs)

    p_analyze = sub.add_parser("analyze", help="输出异常登录、Top 10 或单机使用分析")
    p_analyze.add_argument("--profile", required=True, help="环境 profile 名称或 env 文件路径")
    p_analyze.add_argument("--from", dest="from_date", required=True, help="开始日期，格式 YYYY-MM-DD")
    p_analyze.add_argument("--to", dest="to_date", required=True, help="结束日期，格式 YYYY-MM-DD")
    p_analyze.add_argument("--type", dest="analysis_type", required=True, choices=("login-anomalies", "top-users", "top-assets", "host-usage"))
    p_analyze.add_argument("--host", help="host-usage 时必填，支持资产名、主机名或 IP")
    p_analyze.add_argument("--top", type=int, help="Top N，默认读取 JMS_DEFAULT_TOP_N 或 10")
    p_analyze.add_argument("--format", choices=("markdown", "json"), default="markdown")
    add_org_scope_args(p_analyze)
    p_analyze.set_defaults(func=cmd_analyze)

    p_fill = sub.add_parser("fill-template", help="按巡检数据补全文档模板，支持 doc/docx/pdf")
    p_fill.add_argument("--profile", required=True, help="环境 profile 名称或 env 文件路径")
    p_fill.add_argument("--from", dest="from_date", required=True, help="开始日期，格式 YYYY-MM-DD")
    p_fill.add_argument("--to", dest="to_date", required=True, help="结束日期，格式 YYYY-MM-DD")
    p_fill.add_argument("--input-file", required=True, help="输入模板文件路径，支持 .doc/.docx/.pdf")
    p_fill.add_argument("--output-file", help="输出文件路径；留空时写入 runtime/filled_templates/")
    add_org_scope_args(p_fill)
    p_fill.set_defaults(func=cmd_fill_template)

    p_deps = sub.add_parser("ensure-deps", help="安装缺失的可选依赖")
    p_deps.add_argument("target", choices=("db", "exec", "docx", "official", "pdf", "all"))
    p_deps.set_defaults(func=cmd_ensure_deps)

    p_save = sub.add_parser("save-template", help="保存模板")
    p_save.add_argument("--content", help="模板原文")
    p_save.add_argument("--content-file", help="从文件读取模板原文")
    p_save.add_argument("--template-file", help="模板写入路径；留空时写入 runtime/template.md")
    p_save.set_defaults(func=cmd_save_template)

    p_save_config = sub.add_parser("save-config", help="把追问得到的配置项写回 env/profile 文件")
    p_save_config.add_argument("--profile", help="环境 profile 名称或 env 文件路径；留空时写回当前已激活的 profile")
    p_save_config.add_argument("entry", nargs="+", help="配置项，格式 KEY=VALUE")
    p_save_config.set_defaults(func=cmd_save_config)

    p_setup = sub.add_parser("setup-daily-push", help="写入每日推送配置")
    p_setup.add_argument("--hour", type=int, default=8)
    p_setup.add_argument("--minute", type=int, default=0)
    p_setup.add_argument("--template", default=DEFAULT_TEMPLATE_NAME)
    p_setup.add_argument("--template-file", help="模板文件路径或内置别名 daily/executive")
    p_setup.add_argument("--open-id")
    p_setup.add_argument("--group-id")
    p_setup.add_argument("--output-file", help="输出 Markdown 文件路径；留空时写入 runtime/last_report.md")
    p_setup.add_argument("--profile", help="环境 profile 名称或 env 文件路径")
    add_org_scope_args(p_setup)
    p_setup.set_defaults(func=cmd_setup_daily_push)

    p_daemon = sub.add_parser("daemon", help="启动每日推送守护进程")
    p_daemon.add_argument("--hour", type=int, default=8)
    p_daemon.add_argument("--minute", type=int, default=0)
    p_daemon.add_argument("--template-file", help="模板文件路径或内置别名 daily/executive")
    p_daemon.add_argument("--open-id")
    p_daemon.add_argument("--group-id")
    p_daemon.add_argument("--profile", help="环境 profile 名称或 env 文件路径")
    add_org_scope_args(p_daemon)
    p_daemon.set_defaults(func=cmd_daemon)

    p_payload = sub.add_parser("send-payload", help="输出飞书发送载荷")
    p_payload.add_argument("--report-file", help="报告 Markdown 文件路径；留空时读取 runtime/last_report.md")
    p_payload.add_argument("--title", default="JumpServer 巡检报告")
    p_payload.add_argument("--open-id")
    p_payload.add_argument("--group-id")
    p_payload.set_defaults(func=cmd_send_payload)

    p_improve = sub.add_parser("self-improve", help="记录自优化需求")
    p_improve.add_argument("instruction")
    p_improve.set_defaults(func=cmd_self_improve)

    p_token = sub.add_parser("update-token", help="输出更新 Token 的操作提示")
    p_token.add_argument("--profile", help="环境 profile 名称或 env 文件路径")
    p_token.set_defaults(func=cmd_update_token)

    p_self_test = sub.add_parser("self-test", help="自测 JumpServer 接口、命令执行链路与 official legacy 巡检能力")
    p_self_test.add_argument("--date", help="报告日期，格式 YYYY-MM-DD")
    p_self_test.add_argument("--profile", help="环境 profile 名称或 env 文件路径")
    add_org_scope_args(p_self_test)
    p_self_test.set_defaults(func=cmd_self_test)

    p_exec = sub.add_parser("exec-commands", help="通过 connection-token 执行 df -Th 或自定义命令")
    p_exec.add_argument("profile", help="环境 profile 名称或 env 文件路径")
    p_exec.add_argument("--target", help="仅执行指定 target 名称")
    p_exec.add_argument("--command", action="append", help="追加执行命令，可重复传入")
    p_exec.add_argument("--command-file", help="命令文件路径，一行一个命令")
    p_exec.set_defaults(func=cmd_exec_commands)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
