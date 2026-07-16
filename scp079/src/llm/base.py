"""Abstract LLM provider interface and shared types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict  # JSON Schema for parameters


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: Optional[str] = None
    tool_calls: list = field(default_factory=list)  # List[ToolCall]
    finish_reason: str = "stop"
    usage: dict = field(default_factory=dict)


class LLMProvider(ABC):
    """Abstract interface for LLM backends."""

    @abstractmethod
    def generate(
        self,
        messages: list[dict],
        tools: Optional[list[ToolDefinition]] = None,
    ) -> LLMResponse:
        """Send messages to the LLM and get a response.

        Args:
            messages: List of dicts with 'role' and 'content'.
            tools: Optional list of tool definitions for function calling.

        Returns:
            LLMResponse with content and/or tool_calls.
        """
        ...

    @abstractmethod
    def count_tokens(self, messages: list[dict]) -> int:
        """Estimate token count for a list of messages."""
        ...
