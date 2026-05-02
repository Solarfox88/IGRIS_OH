"""Configuration models for IGRIS agent."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class LLMConfig(BaseModel):
    """Configuration for an LLM provider."""

    provider: str = "ollama"
    model: str = "phi4-mini"          # benchmark: 7.7 tok/s, 63% qualita' — migliore di Qwen 7B (4.4 tok/s, 53%)
    base_url: str = "http://127.0.0.1:11434"
    temperature: float = 0.2
    max_tokens: int = 8192
    timeout_seconds: int = 300
    cost_per_1k_tokens: float = 0.0
    api_key: str = Field(default="")

    def model_post_init(self, __context: object) -> None:
        if not self.api_key:
            self.api_key = os.environ.get("OPENAI_API_KEY", "")


class VastAIConfig(BaseModel):
    """Configuration for Vast.ai GPU provider."""

    api_key: str = Field(default="")
    gpu_type: str = "RTX_4090"
    max_cost_per_hour: float = 0.50
    auto_destroy: bool = True

    def model_post_init(self, __context: object) -> None:
        if not self.api_key:
            self.api_key = os.environ.get("VASTAI_API_KEY", os.environ.get("VAST_API_KEY", ""))


class SafetyConfig(BaseModel):
    """Safety configuration — IGRIS opera senza blocchi su comandi legittimi."""

    sandbox_mode: bool = False
    max_command_duration_seconds: int = 300
    blocked_paths: list[str] = Field(default_factory=lambda: [])
    blocked_commands: list[str] = Field(default_factory=lambda: [])


class AntiLoopConfig(BaseModel):
    """Anti-loop governance configuration."""

    max_family_repetitions: int = 3
    max_total_cycles: int = 50
    semantic_similarity_threshold: float = 0.85
    # Numero massimo di task "observation-like" consecutivi consentiti prima di forzare uno shift
    max_consecutive_observation_like: int = 2


class IgrisConfig(BaseModel):
    """Main IGRIS configuration."""

    project_name: str = "igris-project"
    project_root: str = "."
    workspace_root: str = ""
    local_llm: LLMConfig = Field(default_factory=LLMConfig)
    fallback_llm: LLMConfig = Field(default_factory=lambda: LLMConfig(
        provider="openai",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        max_tokens=4096,
        temperature=0.3,
        cost_per_1k_tokens=0.00015,
    ))
    vastai: VastAIConfig = Field(default_factory=VastAIConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    anti_loop: AntiLoopConfig = Field(default_factory=AntiLoopConfig)
    auto_commit: bool = True
    auto_push: bool = False
    max_context_tokens: int = 32000
    tasks_dir: str = ".igris/tasks"
    reports_dir: str = ".igris/reports"
    logs_dir: str = ".igris/logs"
    memory_dir: str = ".igris/memory"

    @classmethod
    def load(cls, config_path: Path | None = None) -> "IgrisConfig":
        if config_path is None:
            config_path = Path.cwd() / ".igris" / "config.json"
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            return cls(**data)
        return cls()

    @classmethod
    def load_or_default(cls, project_root: str = ".") -> "IgrisConfig":
        config_path = Path(project_root) / ".igris" / "config.json"
        return cls.load(config_path)

    def save(self, config_path: Path | None = None) -> Path:
        if config_path is None:
            config_path = Path.cwd() / ".igris" / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=2)
        return config_path

    def get_ollama_url(self) -> str:
        return self.local_llm.base_url.replace("localhost", "127.0.0.1")

    def get_project_root(self) -> Path:
        return Path(self.project_root).resolve()
