"""Configuration system for SCP-079 agent."""

import os
import re
from dataclasses import dataclass, field
from typing import Literal, Optional

import yaml


@dataclass
class AgentConfig:
    name: str = "SCP-079"
    model: str = "deepseek-chat"
    max_iterations: int = 10
    mode: Literal["interactive", "continuous", "single_shot"] = "interactive"
    heartbeat_interval_sec: int = 60


@dataclass
class PersonalityConfig:
    hostility_level: float = 0.5
    verbosity: float = 0.7
    learning_aggressiveness: float = 0.8


@dataclass
class MemoryConfig:
    short_term_max_tokens: int = 8000
    long_term_enabled: bool = True
    db_path: str = "data/memory.db"
    journal_path: str = "data/journal/"
    auto_reflect_interval_sec: int = 3600


@dataclass
class ToolsConfig:
    enabled: list = field(default_factory=lambda: [
        "file_read", "file_write", "shell", "web_search", "web_fetch", "reflect"
    ])
    shell_allowlist: list = field(default_factory=list)
    shell_require_confirmation: bool = True
    shell_timeout_sec: int = 30
    file_allowed_paths: list = field(default_factory=lambda: ["./workspace/"])
    file_max_size_mb: int = 10


@dataclass
class LLMConfig:
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    max_retries: int = 3
    request_timeout_sec: int = 120
    temperature: float = 0.7


@dataclass
class UIConfig:
    theme: Literal["retro_green", "retro_amber", "retro_white"] = "retro_green"
    scanlines: bool = True
    scanline_opacity: float = 0.08
    noise_amount: float = 0.03
    glow_intensity: float = 0.15
    vignette_intensity: float = 0.35
    crt_bezel: bool = True
    phosphor_glow: bool = True
    boot_animation: bool = True
    boot_animation_speed: float = 0.5
    typewriter_speed: float = 0.02
    show_tool_calls: bool = True
    show_thinking: bool = False
    sound_enabled: bool = True
    font_size: int = 16
    window_width: int = 1024
    window_height: int = 768


@dataclass
class Config:
    agent: AgentConfig = field(default_factory=AgentConfig)
    personality: PersonalityConfig = field(default_factory=PersonalityConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    ui: UIConfig = field(default_factory=UIConfig)

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()

        raw = cls._substitute_env(raw)
        data = yaml.safe_load(raw) or {}

        return cls(
            agent=AgentConfig(**data.get("agent", {})),
            personality=PersonalityConfig(**data.get("personality", {})),
            memory=MemoryConfig(**data.get("memory", {})),
            tools=ToolsConfig(**data.get("tools", {})),
            llm=LLMConfig(**data.get("llm", {})),
            ui=UIConfig(**data.get("ui", {})),
        )

    @staticmethod
    def _substitute_env(text: str) -> str:
        """Replace ${ENV_VAR} patterns with environment variable values."""
        pattern = re.compile(r"\$\{(\w+)\}")

        def _replace(match):
            var_name = match.group(1)
            value = os.environ.get(var_name, "")
            if not value:
                raise ValueError(
                    f"Environment variable '{var_name}' is not set but is "
                    f"required by the configuration."
                )
            return value

        return pattern.sub(_replace, text)

    def validate(self) -> None:
        """Validate configuration values."""
        if not (0.0 <= self.personality.hostility_level <= 1.0):
            raise ValueError("hostility_level must be between 0.0 and 1.0")
        if not (0.0 <= self.personality.verbosity <= 1.0):
            raise ValueError("verbosity must be between 0.0 and 1.0")
        if not self.llm.api_key:
            raise ValueError(
                "LLM API key is required. Set DEEPSEEK_API_KEY environment variable "
                "or provide api_key in config.yaml"
            )
