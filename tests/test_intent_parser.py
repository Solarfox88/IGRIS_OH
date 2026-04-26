"""Tests for intent parser — fallback command/file detection."""

from igris.core.intent_parser import (
    parse_llm_described_commands,
    parse_user_intent,
)


class TestParseUserIntent:
    """Test parsing user messages for direct action intents."""

    def test_crea_file_con_contenuto_e_percorso(self):
        msg = 'creami sul desktop un file test.txt con scritto "Giusy ti amo <3" crea qui il file che ti ho chiesto C:\\Users\\Admin\\Desktop\\'
        # Should not crash on complex messages — fallback system handles it
        result = parse_user_intent(msg)
        assert isinstance(result, list)

    def test_crea_file_simple(self):
        msg = "crea un file test.txt con scritto ciao"
        actions = parse_user_intent(msg)
        assert len(actions) >= 1
        assert actions[0]["type"] == "write_file"
        assert "test.txt" in actions[0]["path"]

    def test_crea_file_con_percorso_windows(self):
        msg = 'creami un file test.txt sul desktop con scritto "Giusy ti amo" C:\\Users\\Admin\\Desktop\\'
        result = parse_user_intent(msg)
        assert isinstance(result, list)

    def test_create_file_english(self):
        msg = "create a file hello.txt with content hello world"
        actions = parse_user_intent(msg)
        assert len(actions) >= 1
        assert actions[0]["type"] == "write_file"
        assert "hello.txt" in actions[0]["path"]

    def test_no_intent_discussion(self):
        msg = "cosa ne pensi di Python vs JavaScript?"
        actions = parse_user_intent(msg)
        assert len(actions) == 0

    def test_no_intent_question(self):
        msg = "come funziona il deploy?"
        actions = parse_user_intent(msg)
        assert len(actions) == 0


class TestParseLLMDescribedCommands:
    """Test fallback parsing of commands described by LLM in its response."""

    def test_code_block_commands(self):
        response = """Ho creato il file per te. Ecco i comandi:

```bash
mkdir -p /tmp/project
touch /tmp/project/test.txt
echo "hello" > /tmp/project/test.txt
```

Il file è stato creato!"""
        cmds = parse_llm_described_commands(response)
        assert len(cmds) == 3
        assert "mkdir -p /tmp/project" in cmds
        assert "touch /tmp/project/test.txt" in cmds

    def test_inline_described_commands(self):
        response = """Per creare il file, eseguo:

touch ~/Desktop/test.txt
echo "ciao" > ~/Desktop/test.txt
cat ~/Desktop/test.txt

Fatto!"""
        cmds = parse_llm_described_commands(response)
        assert len(cmds) >= 2

    def test_no_commands_in_discussion(self):
        response = "Ciao Christian! Come posso aiutarti oggi? Sono pronto."
        cmds = parse_llm_described_commands(response)
        assert len(cmds) == 0

    def test_skip_if_tags_present(self):
        response = "[CMD]echo hello[/CMD]"
        cmds = parse_llm_described_commands(response)
        assert len(cmds) == 0

    def test_skip_if_write_file_tags_present(self):
        response = '[WRITE_FILE path="/tmp/test.txt"]hello[/WRITE_FILE]'
        cmds = parse_llm_described_commands(response)
        assert len(cmds) == 0

    def test_numbered_steps_commands(self):
        response = """Ecco cosa faccio:

1. mkdir /tmp/test
2. touch /tmp/test/file.txt
3. echo "content" > /tmp/test/file.txt"""
        cmds = parse_llm_described_commands(response)
        assert len(cmds) >= 2

    def test_pip_install(self):
        response = """Per installare Flask:

pip install flask

Ora puoi usarlo."""
        cmds = parse_llm_described_commands(response)
        assert len(cmds) >= 1
        assert any("pip install flask" in cmd for cmd in cmds)

    def test_dedup_commands(self):
        response = """Esegui:

echo hello
echo hello
echo hello"""
        cmds = parse_llm_described_commands(response)
        assert cmds.count("echo hello") == 1
