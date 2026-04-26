"""Tests for IGRIS data models."""

import tempfile
from pathlib import Path

from igris.models.config import IgrisConfig
from igris.models.report import SelfTestCheck, SelfTestReport
from igris.models.state import FamilySaturationState, ProjectState
from igris.models.task import Task, TaskFamily, TaskPriority, TaskRisk, TaskStatus


class TestTask:
    def test_create_task(self):
        task = Task(title="Test task", description="A test")
        assert task.title == "Test task"
        assert task.status == TaskStatus.NEW
        assert task.family == TaskFamily.OTHER
        assert task.priority == TaskPriority.MEDIUM
        assert task.risk == TaskRisk.LOW
        assert task.semantic_hash

    def test_semantic_hash(self):
        t1 = Task(title="Fix bug", family=TaskFamily.BUG_FIX)
        t2 = Task(title="Fix bug", family=TaskFamily.BUG_FIX)
        assert t1.semantic_hash == t2.semantic_hash

    def test_different_hash(self):
        t1 = Task(title="Fix bug", family=TaskFamily.BUG_FIX)
        t2 = Task(title="Add feature", family=TaskFamily.CODE_IMPLEMENTATION)
        assert t1.semantic_hash != t2.semantic_hash

    def test_is_observation_like(self):
        assert Task(title="t", family=TaskFamily.OBSERVATION).is_observation_like
        assert Task(title="t", family=TaskFamily.SYNTHESIS).is_observation_like
        assert not Task(title="t", family=TaskFamily.CODE_IMPLEMENTATION).is_observation_like

    def test_mark_completed(self):
        task = Task(title="Test")
        task.mark_in_progress()
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.execution_count == 1
        task.mark_completed("Done")
        assert task.status == TaskStatus.COMPLETED
        assert task.outcome == "Done"
        assert task.completed_at is not None

    def test_mark_blocked(self):
        task = Task(title="Test")
        task.mark_blocked("Missing dependency")
        assert task.status == TaskStatus.BLOCKED
        assert task.blocked_reason == "Missing dependency"

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            task = Task(title="Save test", description="Testing save/load")
            path = task.save(Path(tmpdir))
            loaded = Task.load(path)
            assert loaded.title == task.title
            assert loaded.id == task.id


class TestSelfTestReport:
    def test_create_report(self):
        report = SelfTestReport(task_id="test-1")
        assert report.total_checks == 0
        assert report.all_passed

    def test_add_checks(self):
        report = SelfTestReport(task_id="test-1")
        report.checks.append(SelfTestCheck(name="check1", passed=True, message="OK"))
        report.checks.append(SelfTestCheck(name="check2", passed=False, message="FAIL"))
        assert report.total_checks == 2
        assert report.passed_checks == 1
        assert report.failed_checks == 1
        assert not report.all_passed

    def test_to_markdown(self):
        report = SelfTestReport(task_id="test-1")
        report.checks.append(SelfTestCheck(name="check1", passed=True, message="OK"))
        md = report.to_markdown()
        assert "PASS" in md
        assert "check1" in md


class TestFamilySaturation:
    def test_record_execution(self):
        state = FamilySaturationState()
        state.record_execution(TaskFamily.OBSERVATION)
        assert state.families["observation"].total_executions == 1
        assert state.families["observation"].consecutive_executions == 1

    def test_saturation_after_max_reps(self):
        state = FamilySaturationState()
        for _ in range(3):
            state.record_execution(TaskFamily.OBSERVATION, max_reps=3)
        assert state.is_family_saturated(TaskFamily.OBSERVATION)

    def test_no_saturation_before_max(self):
        state = FamilySaturationState()
        for _ in range(2):
            state.record_execution(TaskFamily.OBSERVATION, max_reps=3)
        assert not state.is_family_saturated(TaskFamily.OBSERVATION)

    def test_consecutive_reset(self):
        state = FamilySaturationState()
        state.record_execution(TaskFamily.OBSERVATION)
        state.record_execution(TaskFamily.OBSERVATION)
        state.record_execution(TaskFamily.CODE_IMPLEMENTATION)
        assert state.families["observation"].consecutive_executions == 0
        assert state.families["code_implementation"].consecutive_executions == 1

    def test_get_available_families(self):
        state = FamilySaturationState()
        for _ in range(3):
            state.record_execution(TaskFamily.OBSERVATION, max_reps=3)
        available = state.get_available_families()
        assert TaskFamily.OBSERVATION not in available
        assert TaskFamily.CODE_IMPLEMENTATION in available


class TestConfig:
    def test_default_config(self):
        config = IgrisConfig()
        assert config.local_llm.provider == "ollama"
        assert config.local_llm.model == "mistral"
        assert config.fallback_llm.provider == "openai"
        assert config.safety.max_command_duration_seconds == 300

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = IgrisConfig(project_name="test", project_root=tmpdir)
            path = config.save(Path(tmpdir) / "config.json")
            loaded = IgrisConfig.load(path)
            assert loaded.project_name == "test"
            assert loaded.local_llm.model == "mistral"


class TestProjectState:
    def test_create_state(self):
        state = ProjectState(project_name="test")
        assert state.project_name == "test"
        assert state.project_health == "unknown"

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = ProjectState(project_name="test")
            state.save(Path(tmpdir))
            loaded = ProjectState.load(Path(tmpdir))
            assert loaded.project_name == "test"
