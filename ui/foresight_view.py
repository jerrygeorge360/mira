"""Foresight timeline view for the MIRA UI.

Ownership: MIRA contributors.
Related issue: ISSUE-048.
Architecture area: UI.

Foresight is easier to understand when its lifecycle is visible: pending,
active, resolved, expired, and cancelled constraints laid out on a timeline by
their valid windows. This page shows each record's content, status, validity
window, always-inject flag, source observation, and resolver, with active /
expired / resolved / upcoming filters. It does not detect foresight (Non-Goal) --
it reads existing records read-only. Streamlit is lazy-imported and ``st``/the
loader are injectable so the page is testable without Streamlit or a database.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

ForesightRecord = dict[str, object]
ForesightLoader = Callable[[], list[ForesightRecord]]

DEFAULT_SESSION_ID = "demo-session"

STATUS_FILTERS: dict[str, Callable[[ForesightRecord], bool]] = {
    "all": lambda record: True,
    "active": lambda record: str(record.get("status")) == "active",
    "expired": lambda record: str(record.get("status")) == "expired",
    "resolved": lambda record: str(record.get("status")) == "resolved",
    "upcoming": lambda record: str(record.get("status")) == "pending",
}
STATUS_FILTER_OPTIONS = list(STATUS_FILTERS)

DISPLAY_FIELDS = (
    "content",
    "status",
    "valid_from",
    "valid_until",
    "always_inject",
    "source_observation_id",
    "resolved_by",
)

_MOCK_RECORDS: list[ForesightRecord] = [
    {
        "id": "fs_1",
        "content": "Hackathon submission is due 2026-07-01.",
        "status": "active",
        "valid_from": "2026-06-24T00:00:00+00:00",
        "valid_until": "2026-07-01T23:59:59+00:00",
        "always_inject": 0,
        "source_observation_id": "obs_deadline",
        "resolved_by": None,
    },
    {
        "id": "fs_2",
        "content": "Run make check before every PR.",
        "status": "active",
        "valid_from": None,
        "valid_until": None,
        "always_inject": 1,
        "source_observation_id": "obs_workflow",
        "resolved_by": None,
    },
    {
        "id": "fs_3",
        "content": "Freeze deploys during the audit window.",
        "status": "pending",
        "valid_from": "2026-08-01T00:00:00+00:00",
        "valid_until": "2026-08-15T00:00:00+00:00",
        "always_inject": 0,
        "source_observation_id": "obs_audit",
        "resolved_by": None,
    },
    {
        "id": "fs_4",
        "content": "Submit the grant report.",
        "status": "resolved",
        "valid_from": "2026-05-01T00:00:00+00:00",
        "valid_until": "2026-06-01T00:00:00+00:00",
        "always_inject": 0,
        "source_observation_id": "obs_grant",
        "resolved_by": "obs_grant_done",
    },
    {
        "id": "fs_5",
        "content": "Old conference deadline.",
        "status": "expired",
        "valid_from": "2026-04-01T00:00:00+00:00",
        "valid_until": "2026-04-15T00:00:00+00:00",
        "always_inject": 0,
        "source_observation_id": "obs_conf",
        "resolved_by": None,
    },
]


def filter_foresight(
    records: list[ForesightRecord],
    status_filter: str = "all",
) -> list[ForesightRecord]:
    """Filter foresight records by lifecycle status group."""
    predicate = STATUS_FILTERS.get(status_filter, STATUS_FILTERS["all"])
    return [record for record in records if predicate(record)]


def timeline_rows(records: list[ForesightRecord]) -> list[dict[str, object]]:
    """Build timeline rows (with validity windows) sorted by start of window."""
    rows = [
        {
            "content": record.get("content", ""),
            "status": record.get("status", ""),
            "valid_from": record.get("valid_from") or "—",
            "valid_until": record.get("valid_until") or "—",
            "window": _window(record),
            "always_inject": bool(record.get("always_inject")),
        }
        for record in records
    ]
    return sorted(rows, key=lambda row: str(row["valid_from"]))


def render_foresight_timeline(
    session_id: str = DEFAULT_SESSION_ID,
    st: Any | None = None,
    loader: ForesightLoader | None = None,
    *,
    use_mock: bool = True,
) -> None:
    """Render the foresight timeline page."""
    streamlit = st if st is not None else _load_streamlit()
    records = _resolve_loader(loader, use_mock)()

    streamlit.title("⏳ Foresight Timeline")
    streamlit.caption("Future-relevant constraints and their lifecycle.")

    status_filter = streamlit.sidebar.selectbox("Status", STATUS_FILTER_OPTIONS)
    filtered = filter_foresight(records, str(status_filter))
    if not filtered:
        streamlit.info("No foresight records match the current filter.")
        return

    streamlit.subheader("Timeline")
    streamlit.dataframe(timeline_rows(filtered))

    for record in filtered:
        _render_record_detail(streamlit, record)


def _render_record_detail(st: Any, record: ForesightRecord) -> None:
    st.subheader(f"{record.get('status', 'unknown')} — {record.get('content', '')}")
    st.markdown(f"**Valid window:** {_window(record)}")
    st.markdown(f"**Always inject:** {bool(record.get('always_inject'))}")
    st.markdown(f"**Source observation:** {record.get('source_observation_id', '—')}")
    if record.get("resolved_by"):
        st.markdown(f"**Resolved by:** {record.get('resolved_by')}")


def _window(record: ForesightRecord) -> str:
    start = record.get("valid_from") or "—"
    end = record.get("valid_until") or "—"
    return f"{start} → {end}"


def load_foresight() -> list[ForesightRecord]:
    """Load all foresight records from durable storage (read-only)."""
    from core.db.repositories import repository_connection

    with repository_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM foresight_records ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def _resolve_loader(loader: ForesightLoader | None, use_mock: bool) -> ForesightLoader:
    if loader is not None:
        return loader
    if use_mock:
        return lambda: [dict(record) for record in _MOCK_RECORDS]
    return load_foresight


def _load_streamlit() -> Any:
    try:
        return importlib.import_module("streamlit")
    except ModuleNotFoundError as error:  # pragma: no cover - only without streamlit
        raise RuntimeError("streamlit is not installed; install it to run the MIRA UI") from error
