"""Tool system base classes."""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ToolResult:
    success: bool
    output: str
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class BaseTool(ABC):
    """Protocol that all tools must implement."""

    name: str
    description: str
    parameters: dict  # JSON Schema

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with the given arguments."""
        ...

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Discovery and registration of tools."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_enabled(self) -> list[BaseTool]:
        return list(self._tools.values())

    def get_schemas(self) -> list[dict]:
        return [t.to_openai_schema() for t in self._tools.values()]

    def execute(self, name: str, arguments: dict) -> ToolResult:
        """Synchronous wrapper that runs the async tool in a mini event loop."""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(False, "", f"Unknown tool: {name}")
        try:
            return asyncio.run(tool.execute(**arguments))
        except Exception as e:
            return ToolResult(False, "", str(e))
