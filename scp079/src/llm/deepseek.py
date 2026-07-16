"""DeepSeek LLM provider using OpenAI-compatible API."""

import json
import time
from typing import Optional

from openai import OpenAI

from ..config import LLMConfig
from .base import LLMProvider, LLMResponse, ToolCall, ToolDefinition


class DeepSeekProvider(LLMProvider):
    """DeepSeek API provider via OpenAI SDK with custom base_url."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.request_timeout_sec,
            max_retries=config.max_retries,
        )

    def generate(
        self,
        messages: list[dict],
        tools: Optional[list[ToolDefinition]] = None,
    ) -> LLMResponse:
        kwargs: dict = {
            "model": "deepseek-chat",
            "messages": messages,
            "temperature": self.config.temperature,
        }

        if tools:
            kwargs["tools"] = [self._tool_to_openai(t) for t in tools]
            kwargs["tool_choice"] = "auto"

        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.client.chat.completions.create(**kwargs)
                return self._parse_response(response)
            except Exception as e:
                if attempt == self.config.max_retries:
                    raise
                time.sleep(2 ** attempt)

        raise RuntimeError("Unreachable")

    def count_tokens(self, messages: list[dict]) -> int:
        """Rough token estimation: characters / 3.5 (reasonable for mixed CN/EN)."""
        total_chars = sum(
            len(m.get("content", ""))
            + sum(len(tc.get("arguments", "{}")) for tc in m.get("tool_calls", []))
            for m in messages
        )
        return int(total_chars / 3.5)

    def _tool_to_openai(self, tool: ToolDefinition) -> dict:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }

    def _parse_response(self, response) -> LLMResponse:
        choice = response.choices[0]
        message = choice.message

        content = message.content or ""

        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    arguments = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=arguments,
                ))

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
        )
