"""Semantic deduplication for tasks."""

from __future__ import annotations

import logging
from difflib import SequenceMatcher

from igris.models.task import Task

logger = logging.getLogger("igris.task.dedup")


class SemanticDeduplicator:
    """Detects semantically duplicate tasks using multiple signals."""

    def __init__(self, similarity_threshold: float = 0.85):
        self.similarity_threshold = similarity_threshold

    def is_duplicate(self, new_task: Task, existing_tasks: list[Task]) -> tuple[bool, Task | None]:
        for existing in existing_tasks:
            if self._are_semantically_equivalent(new_task, existing):
                logger.info(
                    f"Duplicate detected: '{new_task.title}' ~ '{existing.title}'"
                )
                return True, existing
        return False, None

    def _are_semantically_equivalent(self, a: Task, b: Task) -> bool:
        if a.semantic_hash == b.semantic_hash:
            return True

        if a.family == b.family:
            title_sim = self._text_similarity(a.title, b.title)
            if title_sim >= self.similarity_threshold:
                return True

            desc_sim = self._text_similarity(a.description, b.description)
            combined = (title_sim * 0.6) + (desc_sim * 0.4)
            if combined >= self.similarity_threshold:
                return True

        return False

    def _text_similarity(self, a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        a_lower = a.lower().strip()
        b_lower = b.lower().strip()
        if a_lower == b_lower:
            return 1.0
        return SequenceMatcher(None, a_lower, b_lower).ratio()

    def deduplicate_list(self, tasks: list[Task]) -> list[Task]:
        unique: list[Task] = []
        for task in tasks:
            is_dup, _ = self.is_duplicate(task, unique)
            if not is_dup:
                unique.append(task)
            else:
                logger.debug(f"Removed duplicate: {task.title}")
        return unique
