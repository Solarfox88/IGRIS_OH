"""Task Intelligence Layer - classification, selection, dedup, saturation."""

from igris.layers.task.deduplicator import SemanticDeduplicator
from igris.layers.task.selector import TaskSelector

__all__ = ["TaskSelector", "SemanticDeduplicator"]
