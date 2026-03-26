# Findings

- Fresh-environment failures are currently spread across multiple places:
  - `runtime/.venv` may exist without `pip`
  - `playwright` Python package may exist without Chromium
  - Chromium download may fail due a short default timeout or network restrictions
  - browser binaries were previously falling back to user-global cache paths
- Legacy/system command collection depends on browser execution and DB readiness, so install/runtime issues surface as missing report sections.
- Fresh-install UX improves materially when bootstrap can:
  - create the profile scaffold automatically
  - keep dependency failures isolated by group instead of aborting at the first error
  - report pending profile keys and next-step commands explicitly
