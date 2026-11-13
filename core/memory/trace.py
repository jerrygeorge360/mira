from __future__ import annotations

from core.db.repositories import JSON_COLUMNS, TABLE_COLUMNS, create_answer_trace

TraceSection = dict[str, object]
TraceEvidence = dict[str, object]

_SOURCE_CLASSIFICATION_ALIASES = {
    "observations": "observation",
    "recent_observations": "observation",
    "observation": "observation",
    "atomic_facts": "atomic_fact",
    "reflection": "reflection",
    "reflections": "reflection",
    "foresight": "foresight",
    "foresight_records": "foresight",
    "structured_tool": "structured_tool",
    "contradiction": "contradiction",
    "graph_edge": "graph_edge",
    "community_summary": "community_summary",
}

_TRACE_ID_ATTRIBUTES = {
    "observation": "retrieved_observation_ids",
    "atomic_fact": "retrieved_fact_ids",
    "reflection": "retrieved_reflection_ids",
    "foresight": "retrieved_foresight_ids",
    "structured_tool": "structured_tool_ids",
    "contradiction": "contradiction_ids",
    "graph_edge": "graph_path_ids",
    "community_summary": "community_summary_ids",
    "unclassified": "unclassified_ids",
}

_OPTIONAL_TRACE_JSON_ATTRIBUTES = {
    "retrieved_reflection_ids_json": "retrieved_reflection_ids",
    "retrieved_foresight_ids_json": "retrieved_foresight_ids",
    "structured_tool_ids_json": "structured_tool_ids",
    "contradiction_ids_json": "contradiction_ids",
    "unclassified_ids_json": "unclassified_ids",
    "detailed_evidence_json": "detailed_evidence",
}


class TraceBuilder:
    """Accumulates provenance data during one MIRA turn and persists it as an answer trace."""

    def __init__(self, session_id: str, user_observation_id: str) -> None:
        self.session_id = session_id
        self.user_observation_id = user_observation_id
        self.assistant_observation_id: str | None = None
        self.retrieval_mode: str | None = None
        self.retrieved_observation_ids: list[str] = []
        self.retrieved_fact_ids: list[str] = []
        self.retrieved_reflection_ids: list[str] = []
        self.retrieved_foresight_ids: list[str] = []
        self.structured_tool_ids: list[str] = []
        self.contradiction_ids: list[str] = []
        self.unclassified_ids: list[str] = []
        self.session_item_ids: list[str] = []
        self.hot_memory_ids: list[str] = []
        self.graph_path_ids: list[str] = []
        self.community_summary_ids: list[str] = []
        self.detailed_evidence: list[TraceEvidence] = []
        self.sufficiency: dict[str, object] | None = None
        self.prompt_sections: list[TraceSection] = []
        self.hydration_ids: list[str] = []
        self.retrieval_log_id: str | None = None
        self.prompt_log_id: str | None = None

    def record_retrieval(self, mode: str, items: list[dict[str, object]]) -> None:
        """Record the retrieval mode and classify each retrieved item by source."""
        self.retrieval_mode = mode
        for item in items:
            source = str(item.get("source", "")).strip()
            source_id = _source_id(item)
            if not source_id:
                continue
            classification = _classify_source(source)
            id_attribute = _TRACE_ID_ATTRIBUTES[classification]
            getattr(self, id_attribute).append(source_id)

            detailed_item = dict(item)
            detailed_item["source_id"] = source_id
            detailed_item["source_classification"] = classification
            self.detailed_evidence.append(detailed_item)

    def record_session_items(self, items: list[dict[str, object]]) -> None:
        """Record session working-set item IDs used in prompt construction."""
        for item in items:
            item_id = item.get("id")
            if isinstance(item_id, str) and item_id:
                self.session_item_ids.append(item_id)

    def record_hot_memory(self, items: list[dict[str, object]]) -> None:
        """Record hot memory item IDs used in prompt construction."""
        for item in items:
            item_id = item.get("id")
            if isinstance(item_id, str) and item_id:
                self.hot_memory_ids.append(item_id)

    def record_prompt_sections(self, context_pack: list[dict[str, object]]) -> None:
        """Record which sections and source IDs went into the prompt."""
        for section in context_pack:
            section_name = str(section.get("section", ""))
            raw_ids = section.get("source_ids", [])
            self.prompt_sections.append(
                {
                    "section": section_name,
                    "source_ids": (
                        sorted(str(s) for s in raw_ids) if isinstance(raw_ids, list) else []
                    ),
                }
            )

    def record_hydration(self, ids: list[str]) -> None:
        """Record session working-set item IDs created by hydration."""
        self.hydration_ids = [str(i) for i in ids if i]

    def record_sufficiency(self, result: dict[str, object] | None) -> None:
        """Record the sufficiency-check result."""
        self.sufficiency = result

    def link_retrieval_log(self, log_id: str | None) -> None:
        """Link this trace to the existing retrieval log."""
        self.retrieval_log_id = log_id

    def link_prompt_log(self, log_id: str | None) -> None:
        """Link this trace to the existing prompt log."""
        self.prompt_log_id = log_id

    def build(self) -> str:
        """Persist the accumulated trace data and return the trace identifier."""
        trace: dict[str, object] = {
            "session_id": self.session_id,
            "user_observation_id": self.user_observation_id,
            "assistant_observation_id": self.assistant_observation_id,
            "retrieval_mode": self.retrieval_mode or "quick",
            "retrieved_observation_ids_json": self.retrieved_observation_ids,
            "retrieved_fact_ids_json": self.retrieved_fact_ids,
            "session_item_ids_json": self.session_item_ids,
            "hot_memory_ids_json": self.hot_memory_ids,
            "graph_path_ids_json": self.graph_path_ids,
            "community_summary_ids_json": self.community_summary_ids,
            "sufficiency_json": self.sufficiency,
            "prompt_sections_json": self.prompt_sections,
            "hydration_ids_json": self.hydration_ids,
            "retrieval_log_id": self.retrieval_log_id,
            "prompt_log_id": self.prompt_log_id,
        }
        for column, attribute in _OPTIONAL_TRACE_JSON_ATTRIBUTES.items():
            if _supports_optional_trace_field(column):
                trace[column] = list(getattr(self, attribute))
        return create_answer_trace(trace)


def _classify_source(source: str) -> str:
    """Return an explicit trace classification without guessing unknown sources."""
    return _SOURCE_CLASSIFICATION_ALIASES.get(source.casefold(), "unclassified")


def _source_id(item: TraceEvidence) -> str:
    """Return the stable source identifier used by legacy trace buckets."""
    value = item.get("source_id") or item.get("id")
    return str(value) if value else ""


def _supports_optional_trace_field(column: str) -> bool:
    """Only add optional fields when the current repository schema can serialize them."""
    return column in TABLE_COLUMNS.get("answer_traces", ()) and column in JSON_COLUMNS
