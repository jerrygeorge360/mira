from __future__ import annotations

from core.db.repositories import create_answer_trace

TraceSection = dict[str, object]


class TraceBuilder:
    """Accumulates provenance data during one MIRA turn and persists it as an answer trace."""

    def __init__(self, session_id: str, user_observation_id: str) -> None:
        self.session_id = session_id
        self.user_observation_id = user_observation_id
        self.assistant_observation_id: str | None = None
        self.retrieval_mode: str | None = None
        self.retrieved_observation_ids: list[str] = []
        self.retrieved_fact_ids: list[str] = []
        self.session_item_ids: list[str] = []
        self.hot_memory_ids: list[str] = []
        self.graph_path_ids: list[str] = []
        self.community_summary_ids: list[str] = []
        self.sufficiency: dict[str, object] | None = None
        self.prompt_sections: list[TraceSection] = []
        self.hydration_ids: list[str] = []
        self.retrieval_log_id: str | None = None
        self.prompt_log_id: str | None = None

    def record_retrieval(self, mode: str, items: list[dict[str, object]]) -> None:
        """Record the retrieval mode and classify each retrieved item by source."""
        self.retrieval_mode = mode
        for item in items:
            source = str(item.get("source", ""))
            source_id = str(item.get("source_id", "") or item.get("id", ""))
            if not source_id:
                continue
            if source in ("observations", "recent_observations", "observation"):
                self.retrieved_observation_ids.append(source_id)
            elif source == "atomic_facts":
                self.retrieved_fact_ids.append(source_id)
            elif source == "graph_edge":
                self.graph_path_ids.append(source_id)
            elif source == "community_summary":
                self.community_summary_ids.append(source_id)
            else:
                self.retrieved_observation_ids.append(source_id)

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
        return create_answer_trace(
            {
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
        )
