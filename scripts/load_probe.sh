#!/usr/bin/env bash
set -euo pipefail

HOSTNAME_VAL="$(hostname 2>/dev/null || echo unknown)"
NOW_VAL="$(date '+%F %T %z' 2>/dev/null || echo unknown)"
OS_VAL="$(awk -F= '/^PRETTY_NAME=/{gsub(/"/,"",$2); print $2}' /etc/os-release 2>/dev/null || true)"
KERNEL_VAL="$(uname -r 2>/dev/null || echo unknown)"

read _ USER1 NICE1 SYSTEM1 IDLE1 IOWAIT1 IRQ1 SOFTIRQ1 STEAL1 _ _ < /proc/stat
TOTAL1=$((USER1 + NICE1 + SYSTEM1 + IDLE1 + IOWAIT1 + IRQ1 + SOFTIRQ1 + STEAL1))
IDLE_ALL1=$((IDLE1 + IOWAIT1))
sleep 1
read _ USER2 NICE2 SYSTEM2 IDLE2 IOWAIT2 IRQ2 SOFTIRQ2 STEAL2 _ _ < /proc/stat
TOTAL2=$((USER2 + NICE2 + SYSTEM2 + IDLE2 + IOWAIT2 + IRQ2 + SOFTIRQ2 + STEAL2))
IDLE_ALL2=$((IDLE2 + IOWAIT2))
TOTAL_DIFF=$((TOTAL2 - TOTAL1))
IDLE_DIFF=$((IDLE_ALL2 - IDLE_ALL1))
IOWAIT_DIFF=$((IOWAIT2 - IOWAIT1))
CPU_USED_PCT="0.00"
IOWAIT_PCT="0.00"
if [ "$TOTAL_DIFF" -gt 0 ]; then
  CPU_USED_PCT="$(awk -v total="$TOTAL_DIFF" -v idle="$IDLE_DIFF" 'BEGIN { printf "%.2f", ((total-idle)/total)*100 }')"
  IOWAIT_PCT="$(awk -v total="$TOTAL_DIFF" -v iowait="$IOWAIT_DIFF" 'BEGIN { printf "%.2f", (iowait/total)*100 }')"
fi

read LOAD1 LOAD5 LOAD15 _ < /proc/loadavg

MEM_TOTAL_KB="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
MEM_AVAIL_KB="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
MEM_USED_KB=$((MEM_TOTAL_KB - MEM_AVAIL_KB))
MEM_USED_PCT="$(awk -v t="$MEM_TOTAL_KB" -v u="$MEM_USED_KB" 'BEGIN { if (t>0) printf "%.2f", (u/t)*100; else print "0.00" }')"
MEM_TOTAL_MB="$(awk -v t="$MEM_TOTAL_KB" 'BEGIN { printf "%.0f", t/1024 }')"
MEM_USED_MB="$(awk -v u="$MEM_USED_KB" 'BEGIN { printf "%.0f", u/1024 }')"

ROOT_DF_LINE="$(df -P / 2>/dev/null | tail -n 1 || true)"
ROOT_FS="$(echo "$ROOT_DF_LINE" | awk '{print $1}')"
ROOT_SIZE="$(echo "$ROOT_DF_LINE" | awk '{print $2}')"
ROOT_USED="$(echo "$ROOT_DF_LINE" | awk '{print $3}')"
ROOT_AVAIL="$(echo "$ROOT_DF_LINE" | awk '{print $4}')"
ROOT_USE_PCT="$(echo "$ROOT_DF_LINE" | awk '{print $5}' | tr -d '%')"
ROOT_MOUNT="$(echo "$ROOT_DF_LINE" | awk '{print $6}')"

HAS_IOSTAT=false
if command -v iostat >/dev/null 2>&1; then
  HAS_IOSTAT=true
fi

cat <<EOF
{
  "hostname": "${HOSTNAME_VAL}",
  "timestamp": "${NOW_VAL}",
  "os": "${OS_VAL}",
  "kernel": "${KERNEL_VAL}",
  "cpu_used_pct": ${CPU_USED_PCT},
  "iowait_pct": ${IOWAIT_PCT},
  "load1": ${LOAD1},
  "load5": ${LOAD5},
  "load15": ${LOAD15},
  "mem_total_mb": ${MEM_TOTAL_MB},
  "mem_used_mb": ${MEM_USED_MB},
  "mem_used_pct": ${MEM_USED_PCT},
  "root_fs": "${ROOT_FS}",
  "root_size_1k": "${ROOT_SIZE}",
  "root_used_1k": "${ROOT_USED}",
  "root_avail_1k": "${ROOT_AVAIL}",
  "root_use_pct": ${ROOT_USE_PCT:-0},
  "root_mount": "${ROOT_MOUNT}",
  "has_iostat": ${HAS_IOSTAT}
}
EOF

if command -v iostat >/dev/null 2>&1; then
  echo
  echo "# iostat"
  iostat -x 1 1 2>/dev/null || true
fi
