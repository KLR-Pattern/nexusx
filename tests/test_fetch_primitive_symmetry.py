"""T020 — fetch primitive symmetry (specs/018 US4).

β and γ federation each have ONE Resolver-internal fetch primitive, with honest
docstrings:

  (a) ``fetch_remote_subtree`` — β entity federation (entity-first gql /
      Resolver entity dispatch). Docstring must say so.
  (b) ``fetch_dto_subtree`` — γ DTO federation (Core API / UseCase). Docstring
      must say so.
  (c) Call-site convergence: ``fetch_remote_subtree`` is called only inside the
      Resolver (US3); ``set_dto_page_params`` is called only inside
      ``fetch_dto_subtree`` (US4).
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from nexusx.federation.remote_loader import (
    fetch_dto_subtree,
    fetch_remote_subtree,
)

# fetch_remote_subtree.__module__ is the string "nexusx.federation.remote_loader"
# (NOT a path) — Path() on it treats the dotted name as one filename, whose
# parent chain lands at the repo root or higher, making rglob scan the whole
# home dir (.venv included → thousands of files → hang). Use inspect.getfile
# to get the real source file and derive src/nexusx from it.
NEXUSX_SRC = Path(inspect.getfile(fetch_remote_subtree)).resolve().parent.parent


def _callers(func_name: str) -> set[str]:
    """Files that CALL or IMPORT ``func_name`` (AST-level → excludes
    docstrings/comments, which plain text grep cannot distinguish)."""
    callers: set[str] = set()
    for path in NEXUSX_SRC.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name) and f.id == func_name:
                    callers.add(path.name)
                elif isinstance(f, ast.Attribute) and f.attr == func_name:
                    callers.add(path.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.name == func_name or alias.asname == func_name:
                        callers.add(path.name)
    return callers


# ── (a) / (b): honest docstrings ────────────────────────────────────────


def test_fetch_remote_subtree_docstring_is_beta_only():
    """(a) fetch_remote_subtree advertises β entity federation, not "shared"."""
    doc = fetch_remote_subtree.__doc__ or ""
    assert "β" in doc, "docstring must name β"
    assert "entity-federation" in doc or "entity federation" in doc
    # the old misleading "shared primitive for BOTH β and γ" is gone
    assert "shared" not in doc.lower()


def test_fetch_dto_subtree_docstring_is_gamma_only():
    """(b) fetch_dto_subtree advertises γ DTO federation."""
    doc = fetch_dto_subtree.__doc__ or ""
    assert "γ" in doc, "docstring must name γ"
    assert "DTO-federation" in doc or "DTO federation" in doc


# ── (c): call-site convergence ──────────────────────────────────────────


def test_fetch_remote_subtree_called_only_in_resolver():
    """(c) β fetch primitive's only caller is the Resolver (specs/018 US3)."""
    callers = _callers("fetch_remote_subtree")
    # remote_loader.py defines it (a def, not a call) — excluded by AST.
    assert callers == {"resolver.py"}, (
        f"fetch_remote_subtree must be called only from resolver.py, got {callers}"
    )


def test_set_dto_page_params_called_only_in_fetch_dto_subtree():
    """(c) set_dto_page_params's only caller is fetch_dto_subtree (specs/018 US4).

    γ page-params side-channel collapsed into one primitive; the Resolver no
    longer imports/calls set_dto_page_params directly.
    """
    callers = _callers("set_dto_page_params")
    assert callers == {"remote_loader.py"}, (
        f"set_dto_page_params must be called only from remote_loader.py "
        f"(fetch_dto_subtree), got {callers}"
    )
