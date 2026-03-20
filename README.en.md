# JumpServer Inspection Report

[中文](README.md)

`jumpserver-inspection-report` is an execution-oriented skill for JumpServer inspection reporting. It uses bundled scripts to generate Markdown daily reports, executive summaries, Feishu delivery payloads, and local schedule state for operations and after-sales workflows.

## Repository Layout

```text
.
├── SKILL.md
├── README.md
├── README.en.md
├── .gitignore
├── agents/
│   └── openai.yaml
├── assets/
│   └── templates/
│       ├── daily.md
│       └── executive.md
├── references/
│   ├── runtime.md
│   ├── templates.md
│   ├── delivery.md
│   └── troubleshooting.md
├── runtime/
│   └── .gitkeep
├── scripts/
│   ├── jms_inspection.py
│   └── load_probe.sh
├── main.py
└── requirements.txt
```

## What It Does

- Generates inspection reports from JumpServer API data
- Supports both placeholder templates and natural-language templates
- Produces Feishu message payloads for an upper-layer sender
- Stores local schedule state and supports a foreground daemon
- Degrades gracefully when a single API endpoint fails

## Runtime Requirements

- Python 3
- JumpServer URL and authentication environment variables

Bearer mode:

```bash
export JUMPSERVER_URL="https://your-jumpserver.example.com"
export JUMPSERVER_TOKEN="your_token"
```

Signature mode:

```bash
export JUMPSERVER_URL="https://your-jumpserver.example.com"
export JUMPSERVER_KEY_ID="your_key_id"
export JUMPSERVER_SECRET_ID="your_secret"
```

The current implementation only uses Python standard library modules, so `requirements.txt` intentionally contains no third-party package entries.

## Common Commands

```bash
python3 scripts/jms_inspection.py generate --date 2026-03-20
python3 scripts/jms_inspection.py generate --template-file executive
python3 scripts/jms_inspection.py save-template --content-file /path/to/template.md
python3 scripts/jms_inspection.py send-payload --open-id ou_xxx
python3 scripts/jms_inspection.py setup-daily-push --hour 8 --minute 0 --template-file daily
python3 scripts/jms_inspection.py daemon --hour 8 --minute 0 --template-file runtime/template.md
python3 scripts/jms_inspection.py self-test --date 2026-03-20
python3 scripts/jms_inspection.py update-token
```

## Documentation Entry Points

- Execution boundaries and routing: `SKILL.md`
- Runtime and environment: `references/runtime.md`
- Template behavior: `references/templates.md`
- Delivery and scheduling: `references/delivery.md`
- Troubleshooting: `references/troubleshooting.md`
