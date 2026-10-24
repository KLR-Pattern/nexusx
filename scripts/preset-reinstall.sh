#!/usr/bin/env bash
# nexusx preset 重新安装脚本
#
# spec-kit 的 `specify preset add --dev` 是 copy-based（非 symlink），
# 每次编辑 preset 源文件后必须重新安装才能在 .specify/templates/、
# .specify/extensions/<preset-id>/commands/ 等位置生效。
# 本脚本封装 remove + add 流程，让测试迭代一轮一次按键。
#
# v0.2.0+ 架构：preset 只 replace template（4 个）、不 replace command；
# nexusx 增强命令（nexusx-phase0 / nexusx-plan-decisions / nexusx-tasks-phase-tags）
# 作为独立 prepend 命令通过 .specify/extensions.yml 的 before_specify / before_plan /
# before_tasks hooks 自动触发。插拔不影响 spec-kit 主流程。
#
# Usage: bash scripts/preset-reinstall.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRESET_DIR="${REPO_ROOT}/presets/nexusx"

if [ ! -f "${PRESET_DIR}/preset.yml" ]; then
    echo "ERROR: ${PRESET_DIR}/preset.yml 不存在" >&2
    exit 1
fi

echo "==> Removing existing nexusx preset (if installed)"
specify preset remove nexusx 2>/dev/null || echo "    (was not installed)"

echo "==> Installing nexusx preset from ${PRESET_DIR}"
specify preset add --dev "${PRESET_DIR}"

echo "==> Installed presets:"
specify preset list

echo
echo "==> Verify template resolution (nexusx should win over core):"
for tpl in spec-template plan-template tasks-template constitution-template; do
    resolved=$(specify preset resolve "${tpl}" 2>/dev/null || echo "FAILED")
    echo "    ${tpl} → ${resolved}"
done

echo
echo "==> nexusx prepend commands (independent, also auto-triggered via .specify/extensions.yml hooks):"
for cmd in nexusx-phase0 nexusx-plan-decisions nexusx-tasks-phase-tags; do
    if [ -f "${PRESET_DIR}/commands/${cmd}.md" ]; then
        echo "    ✓ ${cmd}.md present"
    else
        echo "    ✗ ${cmd}.md MISSING"
    fi
done

echo
echo "==> Hooks in .specify/extensions.yml (optional, non-blocking):"
grep -E "before_(specify|plan|tasks)|nexusx\.(phase0|plan-decisions|tasks-phase-tags)" \
    "${REPO_ROOT}/.specify/extensions.yml" 2>/dev/null | sed 's/^/    /' || \
    echo "    (no nexusx hooks found — check .specify/extensions.yml)"

echo
echo "Done. 现在可以在 nexusx 项目中运行 /speckit-specify 测试（before_specify hook 会先跑 /nexusx-phase0）。"
