"""Regenerate the standalone-manager ER DOT baseline (FR-008 golden file).

Run from repo root::

    uv run python specs/022-voyager-composed-clusters/make_baseline.py

Imports the baseline entities from tests.test_composed_voyager so the
``__module__`` context matches the golden-file assertion exactly.
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import ErManager
from nexusx.voyager.er_diagram_dot import ErDiagramDotBuilder
from tests.test_composed_voyager import CvHr, CvTb

sf = async_sessionmaker(
    create_async_engine("sqlite+aiosqlite:///:memory:"),
    class_=AsyncSession,
    expire_on_commit=False,
)
er = ErManager(session_factory=sf, entities=[CvTb, CvHr])
builder = ErDiagramDotBuilder(er, show_module=True)
builder.analysis()
out = Path(__file__).parent / "baseline_single_er.dot"
out.write_text(builder.render_dot())
print(f"baseline written: {out} ({len(out.read_text().splitlines())} lines)")
