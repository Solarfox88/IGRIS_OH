"""Tests for task selection and deduplication."""

from igris.layers.task.deduplicator import SemanticDeduplicator
from igris.layers.task.selector import TaskSelector
from igris.models.config import IgrisConfig
from igris.models.state import ProjectState
from igris.models.task import Task, TaskFamily, TaskPriority, TaskRisk, TaskStatus


class TestTaskSelector:
    def setup_method(self):
        self.config = IgrisConfig()
        self.selector = TaskSelector(self.config)
        self.state = ProjectState()

    def test_select_highest_priority(self):
        tasks = [
            Task(title="Low prio", priority=TaskPriority.LOW, family=TaskFamily.OTHER),
            Task(title="High prio", priority=TaskPriority.HIGH, family=TaskFamily.CODE_IMPLEMENTATION),
            Task(title="Medium prio", priority=TaskPriority.MEDIUM, family=TaskFamily.TESTING),
        ]
        selected = self.selector.select_next_task(tasks, self.state)
        assert selected is not None
        assert selected.title == "High prio"

    def test_skip_destructive(self):
        tasks = [
            Task(title="Dangerous", risk=TaskRisk.DESTRUCTIVE),
            Task(title="Safe", risk=TaskRisk.SAFE),
        ]
        selected = self.selector.select_next_task(tasks, self.state)
        assert selected.title == "Safe"

    def test_skip_completed(self):
        tasks = [
            Task(title="Done", status=TaskStatus.COMPLETED),
            Task(title="Todo", status=TaskStatus.NEW),
        ]
        selected = self.selector.select_next_task(tasks, self.state)
        assert selected.title == "Todo"

    def test_skip_saturated_family(self):
        for _ in range(3):
            self.state.saturation.record_execution(TaskFamily.OBSERVATION, max_reps=3)
        tasks = [
            Task(title="Observe more", family=TaskFamily.OBSERVATION),
            Task(title="Write code", family=TaskFamily.CODE_IMPLEMENTATION),
        ]
        selected = self.selector.select_next_task(tasks, self.state)
        assert selected.title == "Write code"

    def test_prefer_non_observation(self):
        tasks = [
            Task(title="Observe", family=TaskFamily.OBSERVATION, priority=TaskPriority.MEDIUM),
            Task(title="Code", family=TaskFamily.CODE_IMPLEMENTATION, priority=TaskPriority.MEDIUM),
        ]
        selected = self.selector.select_next_task(tasks, self.state)
        assert selected.title == "Code"

    def test_advisory_fidelity(self):
        advisory = Task(title="Advisory best", family=TaskFamily.BUG_FIX, priority=TaskPriority.HIGH)
        tasks = [
            Task(title="Other", family=TaskFamily.CODE_IMPLEMENTATION, priority=TaskPriority.CRITICAL),
        ]
        selected = self.selector.select_next_task(tasks, self.state, advisory_best=advisory)
        assert selected.title == "Advisory best"

    def test_no_eligible_tasks(self):
        tasks = [
            Task(title="Blocked", status=TaskStatus.BLOCKED),
            Task(title="Done", status=TaskStatus.COMPLETED),
        ]
        selected = self.selector.select_next_task(tasks, self.state)
        assert selected is None


class TestDeduplicator:
    def setup_method(self):
        self.dedup = SemanticDeduplicator(similarity_threshold=0.85)

    def test_exact_duplicate(self):
        t1 = Task(title="Fix the login bug", family=TaskFamily.BUG_FIX)
        t2 = Task(title="Fix the login bug", family=TaskFamily.BUG_FIX)
        is_dup, existing = self.dedup.is_duplicate(t2, [t1])
        assert is_dup
        assert existing.id == t1.id

    def test_semantic_duplicate(self):
        t1 = Task(title="Fix login bug in auth module", family=TaskFamily.BUG_FIX)
        t2 = Task(title="Fix login bug in auth module", family=TaskFamily.BUG_FIX)
        is_dup, _ = self.dedup.is_duplicate(t2, [t1])
        assert is_dup

    def test_not_duplicate(self):
        t1 = Task(title="Fix login bug", family=TaskFamily.BUG_FIX)
        t2 = Task(title="Add dark mode feature", family=TaskFamily.CODE_IMPLEMENTATION)
        is_dup, _ = self.dedup.is_duplicate(t2, [t1])
        assert not is_dup

    def test_deduplicate_list(self):
        tasks = [
            Task(title="Fix bug A", family=TaskFamily.BUG_FIX),
            Task(title="Fix bug A", family=TaskFamily.BUG_FIX),
            Task(title="Add feature B", family=TaskFamily.CODE_IMPLEMENTATION),
        ]
        unique = self.dedup.deduplicate_list(tasks)
        assert len(unique) == 2
