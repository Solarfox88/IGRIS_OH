"""Configuration models for IGRIS agent."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """Configuration for an LLM provider."""

    provider: str = "ollama"
    model: str = "mistral"
    base_url: str = "http://localhost:11434"
    api_key: str = ""
    max_tokens: int = 4096
    temperature: float = 0.3
    timeout_seconds: int = 120
    cost_per_1k_tokens: float = 0.0


class VastAIConfig(BaseModel):
    """Configuration for Vast.ai GPU fallback."""

    api_key: str = ""
    gpu_type: str = "RTX_4090"
    max_cost_per_hour: float = 0.50
    preferred_image: str = "pytorch/pytorch:2.1.0-cuda12.1-cudnn8-runtime"
    auto_destroy: bool = True
    max_runtime_minutes: int = 60


class SafetyConfig(BaseModel):
    """Safety constraints for command execution."""

    allowed_commands: list[str] = Field(default_factory=lambda: [
        "python", "pip", "git", "npm", "node", "cargo", "rustc",
        "ls", "cat", "head", "tail", "find", "grep", "wc",
        "mkdir", "cp", "mv", "echo", "touch", "curl", "wget",
        "docker", "docker-compose", "pytest", "ruff", "mypy",
        "powershell", "cmd",
    ])
    blocked_commands: list[str] = Field(default_factory=lambda: [
        "rm -rf /", "format", "del /s /q", "shutdown", "reboot",
        "mkfs", "dd if=", ":(){ :|:& };:",
    ])
    max_command_duration_seconds: int = 300
    require_confirmation_for_risk: str = "high"
    sandbox_mode: bool = False
    allowed_paths: list[str] = Field(default_factory=list)
    blocked_paths: list[str] = Field(default_factory=lambda: [
        "/Windows/System32", "/etc/passwd", "/etc/shadow",
        "C:/Windows/System32",
    ])


class AntiLoopConfig(BaseModel):
    """Anti-loop governance configuration."""

    max_family_repetitions: int = 3
    max_consecutive_observation_like: int = 2
    max_total_cycles: int = 50
    saturation_cooldown_cycles: int = 5
    semantic_similarity_threshold: float = 0.85
    forced_strategy_shift_after: int = 3


class IgrisConfig(BaseModel):
    """Main configuration for IGRIS agent."""

    project_name: str = "default"
    project_root: str = "."
    workspace_root: str = ""
    local_llm: LLMConfig = Field(default_factory=lambda: LLMConfig(
        provider="ollama",
        model="mistral",
        base_url="http://localhost:11434",
    ))
    fallback_llm: LLMConfig = Field(default_factory=lambda: LLMConfig(
        provider="openai",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        api_key="",
        cost_per_1k_tokens=0.00015,
    ))
    vastai: VastAIConfig = Field(default_factory=VastAIConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    anti_loop: AntiLoopConfig = Field(default_factory=AntiLoopConfig)
    log_level: str = "INFO"
    auto_commit: bool = True
    auto_push: bool = False
    reports_dir: str = ".igris/reports"
    tasks_dir: str = ".igris/tasks"
    logs_dir: str = ".igris/logs"
    memory_dir: str = ".igris/memory"
    max_context_tokens: int = 8000

    def save(self, path: Path | None = None) -> Path:
        if path is None:
            path = Path(self.project_root) / ".igris" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.model_dump(), indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> IgrisConfig:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    @classmethod
    def load_or_default(cls, project_root: str = ".") -> IgrisConfig:
        config_path = Path(project_root) / ".igris" / "config.json"
        if config_path.exists():
            return cls.load(config_path)
        config = cls(project_root=project_root)
        config.save()
        return config
