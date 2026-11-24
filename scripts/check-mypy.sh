#!/usr/bin/env bash
# Type-check the modules that are held to mypy --strict.
#
# The single source of truth is the strict module list in pyproject.toml
# ([[tool.mypy.overrides]] ... strict bundle). This script turns each module
# name into its file under src/ and runs mypy on exactly those targets, with
# the global follow_imports=silent so not-yet-cleared imports do not block.
# `uv run mypy src/nexusx` locally still reports the whole package.
set -euo pipefail

mapfile -t modules < <(uv run python - <<'PY'
import pathlib, tomllib
cfg = tomllib.loads(pathlib.Path("pyproject.toml").read_text())
overrides = cfg["tool"]["mypy"].get("overrides", [])
strict = [o for o in overrides if o.get("disallow_untyped_defs")]
mods = [m for o in strict for m in o["module"] if not m.endswith(".*")]
wildcards = [m[:-2] for o in strict for m in o["module"] if m.endswith(".*")]
root = pathlib.Path("src")
files = [str(root / (m.replace(".", "/") + ".py")) for m in mods]
for wc in wildcards:
    files += sorted(str(p) for p in (root / wc.replace(".", "/")).glob("*.py"))
print("\n".join(files))
PY
)
uv run mypy "${modules[@]}"
