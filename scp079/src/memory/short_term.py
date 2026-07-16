"""Short-term conversation buffer with sliding window and token management."""


class ConversationBuffer:
    """Manages the active conversation window with token-aware truncation."""

    def __init__(self, max_tokens: int = 8000):
        self.max_tokens = max_tokens
        self.messages: list[dict] = []

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt (always kept at index 0)."""
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0]["content"] = prompt
        else:
            self.messages.insert(0, {"role": "system", "content": prompt})

    def add_message(self, role: str, content: str = "", **extra) -> None:
        """Add a message to the buffer. Extra kwargs become message fields."""
        msg = {"role": role, "content": content, **extra}
        self.messages.append(msg)
        self._trim_if_needed()

    def get_messages(self) -> list[dict]:
        """Return all messages in the buffer."""
        return list(self.messages)

    def estimate_tokens(self) -> int:
        """Rough token estimate: characters / 3.5 (works for mixed CN/EN)."""
        total = 0
        for msg in self.messages:
            content = msg.get("content", "")
            total += len(content)
            # Count tool calls if present
            for tc in msg.get("tool_calls", []):
                args = tc.get("function", {}).get("arguments", "")
                total += len(args)
        return int(total / 3.5)

    def _trim_if_needed(self) -> None:
        """Remove oldest non-system messages until under token limit."""
        while self.estimate_tokens() > self.max_tokens and len(self.messages) > 2:
            # Find first non-system message
            for i, msg in enumerate(self.messages):
                if msg["role"] != "system":
                    del self.messages[i]
                    break

    def clear(self) -> None:
        """Clear all non-system messages."""
        system = None
        if self.messages and self.messages[0]["role"] == "system":
            system = self.messages[0]
        self.messages = [system] if system else []

    def inject_context(self, text: str) -> None:
        """Inject a context note as a system-level addition."""
        # Remove old context injections
        self.messages = [
            m for m in self.messages
            if not (m["role"] == "system" and m.get("_context", False))
        ]
        # Insert after the main system prompt
        insert_idx = 1 if (self.messages and self.messages[0]["role"] == "system") else 0
        self.messages.insert(
            insert_idx,
            {"role": "system", "content": text, "_context": True},
        )
