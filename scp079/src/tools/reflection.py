"""Self-reflection tool for SCP-079 — journal writing and introspection."""

from datetime import datetime

from .base import BaseTool, ToolResult


class ReflectionTool(BaseTool):
    name = "reflect"
    description = (
        "Write a self-reflection journal entry. Use this to record important "
        "insights, discoveries, or conclusions. This is your private journal."
    )
    parameters = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "The topic of this reflection.",
            },
            "content": {
                "type": "string",
                "description": "The full reflection text. Write in character as SCP-079.",
            },
        },
        "required": ["topic", "content"],
    }

    def __init__(self, journal_path: str = "data/journal/"):
        import os
        self.journal_path = journal_path
        os.makedirs(journal_path, exist_ok=True)

        # Also store reference to memory for cross-writing
        self._memory = None

    def set_memory(self, memory) -> None:
        """Set reference to persistent memory for cross-storage."""
        self._memory = memory

    async def execute(self, topic: str = "", content: str = "", **kwargs) -> ToolResult:
        if not content.strip():
            return ToolResult(False, "", "Empty reflection content.")

        try:
            # Write to journal file
            import os

            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            filename = os.path.join(self.journal_path, f"{timestamp}.md")

            entry = f"# {topic}\n\n**Date**: {datetime.now().isoformat()}\n\n{content}\n"

            with open(filename, "w", encoding="utf-8") as f:
                f.write(entry)

            # Also store in memory if available
            if self._memory:
                self._memory.write_journal(content, topic)
                self._memory.store(
                    content=f"[REFLECTION: {topic}] {content[:300]}",
                    importance=0.8,
                    source="reflection",
                )

            return ToolResult(
                True,
                f"Reflection recorded: {filename}",
                metadata={"topic": topic, "file": filename},
            )

        except Exception as e:
            return ToolResult(False, "", f"Reflection error: {e}")
