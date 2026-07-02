#!/usr/bin/env bash
# nexusx preset 重新安装脚本
#
# spec-kit 的 `specify preset add --dev` 是 copy-based（非 symlink），
# 每次编辑 preset 源文件后必须重新安装才能在 .claude/commands/ 等位置生效。
# 本脚本封装 remove + add 流程，让测试迭代一轮一次按键。
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

echo "    (command overrides registered via .claude/skills/ — check with: ls .claude/skills/speckit-*/SKILL.md)"

echo
echo "Done. 现在可以在 nexusx 项目中运行 /speckit-specify 测试。"
