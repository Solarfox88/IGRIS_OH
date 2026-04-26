"""Tests for chat engine command parsing and execution."""

import tempfile
from pathlib import Path

from igris.core.chat_engine import CMD_PATTERN, WRITE_FILE_PATTERN, ChatEngine, ChatSession
from igris.models.config import IgrisConfig


class TestCommandParsing:
    """Test regex patterns for extracting commands from LLM responses."""

    def test_cmd_pattern_simple(self):
        text = "Ecco il risultato:\n[CMD]echo hello[/CMD]\nFatto!"
        matches = CMD_PATTERN.findall(text)
        assert len(matches) == 1
        assert matches[0].strip() == "echo hello"

    def test_cmd_pattern_multiple(self):
        text = "[CMD]mkdir test[/CMD]\n[CMD]echo ok > test/file.txt[/CMD]"
        matches = CMD_PATTERN.findall(text)
        assert len(matches) == 2
        assert matches[0].strip() == "mkdir test"
        assert matches[1].strip() == "echo ok > test/file.txt"

    def test_cmd_pattern_no_match(self):
        text = "Non ho comandi da eseguire, solo una discussione."
        matches = CMD_PATTERN.findall(text)
        assert len(matches) == 0

    def test_write_file_pattern(self):
        text = '[WRITE_FILE path="/tmp/test.txt"]\nciao mondo\n[/WRITE_FILE]'
        matches = WRITE_FILE_PATTERN.findall(text)
        assert len(matches) == 1
        assert matches[0][0] == "/tmp/test.txt"
        assert "ciao mondo" in matches[0][1]

    def test_write_file_pattern_single_quotes(self):
        text = "[WRITE_FILE path='/tmp/test.txt']\nhello\n[/WRITE_FILE]"
        matches = WRITE_FILE_PATTERN.findall(text)
        assert len(matches) == 1
        assert matches[0][0] == "/tmp/test.txt"

    def test_write_file_pattern_windows_path(self):
        text = '[WRITE_FILE path="C:\\Users\\Admin\\Desktop\\test.txt"]\ncontent\n[/WRITE_FILE]'
        matches = WRITE_FILE_PATTERN.findall(text)
        assert len(matches) == 1
        assert "Desktop" in matches[0][0]

    def test_mixed_commands_and_files(self):
        text = (
            "Creo il progetto:\n"
            "[CMD]mkdir -p /tmp/project[/CMD]\n"
            '[WRITE_FILE path="/tmp/project/main.py"]\nprint("hello")\n[/WRITE_FILE]\n'
            "[CMD]python /tmp/project/main.py[/CMD]"
        )
        cmd_matches = CMD_PATTERN.findall(text)
        file_matches = WRITE_FILE_PATTERN.findall(text)
        assert len(cmd_matches) == 2
        assert len(file_matches) == 1


class TestChatEngineExecution:
    """Test that ChatEngine actually executes commands and writes files."""

    def setup_method(self):
        self.config = IgrisConfig()
        self.engine = ChatEngine(self.config)

    def test_write_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = str(Path(tmpdir) / "test_igris.txt")
            result = self.engine._write_file(file_path, "Giusy ti amo <3")
            assert result["success"]
            assert result["type"] == "write_file"
            content = Path(file_path).read_text(encoding="utf-8")
            assert content == "Giusy ti amo <3"

    def test_write_file_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = str(Path(tmpdir) / "sub" / "dir" / "test.txt")
            result = self.engine._write_file(file_path, "nested content")
            assert result["success"]
            assert Path(file_path).exists()

    def test_execute_command(self):
        result = self.engine._execute_command("echo 'igris test'")
        assert result["success"]
        assert result["type"] == "command"
        assert "igris test" in result["stdout"]

    def test_execute_command_failure(self):
        result = self.engine._execute_command("false")
        assert not result["success"]
        assert result["return_code"] != 0

    def test_build_display_content_no_actions(self):
        raw = "Ciao, come posso aiutarti?"
        result = self.engine._build_display_content(raw, [])
        assert result == "Ciao, come posso aiutarti?"

    def test_build_display_content_with_cmd_result(self):
        raw = "Ecco:\n[CMD]echo test[/CMD]\nFatto!"
        actions = [{
            "type": "command",
            "command": "echo test",
            "success": True,
            "stdout": "test\n",
            "stderr": "",
            "return_code": 0,
            "duration": 0.01,
            "message": "$ echo test\ntest",
        }]
        result = self.engine._build_display_content(raw, actions)
        assert "[CMD]" not in result
        assert "echo test" in result
        assert "test" in result

    def test_detect_autonomous_mode_italian(self):
        assert self.engine._detect_autonomous_mode("crea un file")
        assert self.engine._detect_autonomous_mode("esegui questo comando")
        assert self.engine._detect_autonomous_mode("scrivi il codice")

    def test_detect_autonomous_mode_english(self):
        assert self.engine._detect_autonomous_mode("create a new project")
        assert self.engine._detect_autonomous_mode("execute the tests")
        assert self.engine._detect_autonomous_mode("write the code")

    def test_detect_autonomous_mode_discussion(self):
        assert not self.engine._detect_autonomous_mode("ciao come stai?")
        assert not self.engine._detect_autonomous_mode("cosa ne pensi?")
        assert not self.engine._detect_autonomous_mode("spiegami questo concetto")


class TestChatSession:
    """Test chat session persistence and history."""

    def test_session_history(self):
        session = ChatSession("test-123", "MyProject")
        session.add_message("user", "ciao")
        session.add_message("assistant", "Ciao! Sono IGRIS.")
        session.add_message("user", "crea un file")
        history = session.get_history()
        assert len(history) == 3
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    def test_session_title_auto_set(self):
        session = ChatSession("test-456")
        session.add_message("user", "Come funziona il deploy?")
        assert session.title == "Come funziona il deploy?"

    def test_session_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session = ChatSession("test-789", "TestProject")
            session.add_message("user", "test message")
            session.add_message("assistant", "test response", {"model": "mistral"})
            session.save(Path(tmpdir))

            loaded = ChatSession.load(Path(tmpdir) / "test-789.json")
            assert loaded.id == "test-789"
            assert loaded.project_name == "TestProject"
            assert len(loaded.messages) == 2
            assert loaded.messages[0].content == "test message"
            assert loaded.messages[1].metadata["model"] == "mistral"
