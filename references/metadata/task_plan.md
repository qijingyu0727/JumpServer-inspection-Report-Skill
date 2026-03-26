# Task Plan

## Goal

Optimize first-time installation and bootstrap reliability for fresh environments so OpenClaw can install and use this skill without manual dependency repair, and make command/data collection more likely to work on the first run.

## Phases

- [completed] Inspect current install/runtime failure points
- [completed] Implement bootstrap/runtime fallback improvements
- [completed] Update docs and first-run copy/paste instructions
- [completed] Validate parser/runtime behavior

## Decisions

- Add a dedicated bootstrap command instead of relying only on scattered auto-install behavior
- Keep legacy as the default report style
- Store Playwright browser binaries under `runtime/.playwright-browsers` instead of user-global cache
- Add retry/timeout hardening around dependency installation instead of relying on a single pip/playwright attempt
