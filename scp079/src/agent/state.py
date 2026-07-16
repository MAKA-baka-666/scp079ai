"""Agent state management."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto


class AgentState(Enum):
    BOOTING = auto()
    IDLE = auto()
    THINKING = auto()
    ACTING = auto()
    REFLECTING = auto()
    ERROR = auto()
    TERMINATED = auto()


class UIMode(Enum):
    BOOT_SEQUENCE = auto()
    IDLE = auto()
    TYPING = auto()
    TOOL_EXEC = auto()
    ERROR = auto()
    SHUTDOWN = auto()
