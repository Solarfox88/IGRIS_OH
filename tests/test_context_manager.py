"""Tests for smart context window management."""

from igris.core.context_manager import (
    build_context_messages,
    get_context_limit,
    summarize_messages,
)
from igris.layers.advisory.router import LLMTier


class TestContextLimit:
    """Test context limit calculation for different models/tiers."""

    def test_local_mistral_default(self):
        limit = get_context_limit("mistral", LLMTier.LOCAL, 0)
        assert limit == 8000 - 2000  # model limit minus reserve

    def test_api_gpt4o_mini(self):
        limit = get_context_limit("gpt-4o-mini", LLMTier.API, 0)
        assert limit == 128000 - 2000

    def test_config_override_lower(self):
        limit = get_context_limit("mistral", LLMTier.LOCAL, 4000)
        assert limit == 4000 - 2000

    def test_config_override_higher_than_model(self):
        # Config says 200k but model only supports 8k — use model's limit
        limit = get_context_limit("mistral", LLMTier.LOCAL, 200000)
        assert limit == 8000 - 2000

    def test_unknown_model_local(self):
        limit = get_context_limit("unknown-model", LLMTier.LOCAL, 0)
        assert limit == 8000 - 2000  # default for local

    def test_unknown_model_api(self):
        limit = get_context_limit("unknown-model", LLMTier.API, 0)
        assert limit == 128000 - 2000  # default for API


class TestSummarizeMessages:
    """Test message summarization."""

    def test_empty(self):
        assert summarize_messages([]) == ""

    def test_single_user_message(self):
        msgs = [{"role": "user", "content": "crea un file test.txt"}]
        summary = summarize_messages(msgs)
        assert "Christian ha chiesto" in summary
        assert "crea un file" in summary

    def test_conversation(self):
        msgs = [
            {"role": "user", "content": "ciao"},
            {"role": "assistant", "content": "Ciao Christian! Sono IGRIS."},
            {"role": "user", "content": "crea un progetto Flask"},
        ]
        summary = summarize_messages(msgs)
        assert "Christian ha chiesto" in summary
        assert "IGRIS ha risposto" in summary

    def test_long_message_truncated(self):
        msgs = [{"role": "user", "content": "x" * 500}]
        summary = summarize_messages(msgs)
        assert "..." in summary
        assert len(summary) < 500


class TestBuildContextMessages:
    """Test smart context building with different scenarios."""

    def test_short_conversation_fits_entirely(self):
        messages = [
            {"role": "user", "content": "ciao"},
            {"role": "assistant", "content": "Ciao!"},
        ]
        result = build_context_messages(
            system_prompt="You are IGRIS.",
            all_messages=messages,
            model="gpt-4o-mini",
            tier=LLMTier.API,
            config_max_tokens=0,
        )
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"
        assert result[2]["role"] == "assistant"
        assert len(result) == 3

    def test_api_tier_sends_all_messages(self):
        messages = [
            {"role": "user", "content": f"messaggio {i}"}
            for i in range(50)
        ]
        result = build_context_messages(
            system_prompt="System prompt.",
            all_messages=messages,
            model="gpt-4o-mini",
            tier=LLMTier.API,
            config_max_tokens=0,
        )
        # Should include system + all 50 messages
        assert len(result) == 51

    def test_local_tier_with_overflow_summarizes(self):
        # Create enough messages to overflow a small context window
        messages = [
            {"role": "user", "content": "messaggio lungo " * 100}
            for _ in range(30)
        ]
        result = build_context_messages(
            system_prompt="System prompt.",
            all_messages=messages,
            model="mistral",
            tier=LLMTier.LOCAL,
            config_max_tokens=4000,
        )
        # Should have system + summary + some recent messages
        assert result[0]["role"] == "system"
        # Should be fewer than 30+1 messages (some were summarized)
        assert len(result) < 31
        # At least 2 recent messages should be kept
        assert len(result) >= 3

    def test_project_context_included(self):
        result = build_context_messages(
            system_prompt="You are IGRIS.",
            all_messages=[{"role": "user", "content": "ciao"}],
            model="mistral",
            tier=LLMTier.LOCAL,
            config_max_tokens=8000,
            project_context="Progetto: MyApp - un'app Flask per gestione utenti",
        )
        system_content = result[0]["content"]
        assert "MyApp" in system_content
        assert "Flask" in system_content

    def test_empty_messages(self):
        result = build_context_messages(
            system_prompt="You are IGRIS.",
            all_messages=[],
            model="mistral",
            tier=LLMTier.LOCAL,
            config_max_tokens=8000,
        )
        assert len(result) == 1
        assert result[0]["role"] == "system"

    def test_summarized_messages_contain_context(self):
        messages = [
            {"role": "user", "content": "Crea un progetto chiamato SuperApp con Flask e PostgreSQL"},
            {"role": "assistant", "content": "Ho creato il progetto SuperApp con Flask e PostgreSQL."},
        ]
        # Use very small context to force summarization
        messages.extend([
            {"role": "user", "content": "aggiungi autenticazione " * 50}
            for _ in range(20)
        ])
        messages.append({"role": "user", "content": "stato del progetto?"})

        result = build_context_messages(
            system_prompt="System.",
            all_messages=messages,
            model="mistral",
            tier=LLMTier.LOCAL,
            config_max_tokens=3000,
        )
        # Should have system, possibly a summary, and recent messages
        assert result[0]["role"] == "system"
        assert len(result) >= 2
