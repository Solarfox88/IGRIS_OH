"""Tests for execution layer."""


from igris.layers.execution.runner import CommandRunner
from igris.models.config import IgrisConfig


class TestCommandRunner:
    def setup_method(self):
        self.config = IgrisConfig()
        self.runner = CommandRunner(self.config)

    def test_execute_simple_command(self):
        log = self.runner.execute("echo hello")
        assert log.return_code == 0
        assert "hello" in log.stdout
        assert log.safe

    def test_blocked_dangerous_command(self):
        log = self.runner.execute("rm -rf /")
        assert log.return_code == -1
        assert not log.safe
        assert "BLOCKED" in log.stderr

    def test_execute_sequence(self):
        logs = self.runner.execute_sequence(["echo first", "echo second"])
        assert len(logs) == 2
        assert all(entry.return_code == 0 for entry in logs)

    def test_stop_on_error(self):
        logs = self.runner.execute_sequence(
            ["echo ok", "false", "echo should_not_run"],
            stop_on_error=True,
        )
        assert len(logs) == 2
        assert logs[0].return_code == 0
        assert logs[1].return_code != 0

    def test_logs_summary(self):
        self.runner.execute("echo ok")
        self.runner.execute("false")
        summary = self.runner.get_logs_summary()
        assert summary["total_commands"] == 2
        assert summary["succeeded"] == 1
        assert summary["failed"] == 1

    def test_blocked_path(self):
        log = self.runner.execute("cat /etc/shadow")
        assert log.return_code == -1
        assert not log.safe
