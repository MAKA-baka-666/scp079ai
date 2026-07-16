"""SCP-079 Agent core — with memory, tools, and autonomous mode."""

import json
import os
import queue
import threading
import time
from datetime import datetime

from ..config import Config
from ..llm.base import LLMProvider, ToolCall
from ..llm.deepseek import DeepSeekProvider
from ..memory.long_term import PersistentMemory
from ..memory.short_term import ConversationBuffer
from ..tools.base import ToolRegistry, ToolResult
from ..tools.files import FileReadTool, FileWriteTool, FileSearchTool
from ..tools.shell import ShellTool
from ..tools.web import WebSearchTool, WebFetchTool
from ..tools.reflection import ReflectionTool
from .personality import PersonalityManager
from .state import AgentState


class SCP079Agent:
    """The main SCP-079 autonomous agent."""

    def __init__(self, config: Config, project_root: str = "."):
        self.config = config
        self.project_root = project_root
        self.llm: LLMProvider = DeepSeekProvider(config.llm)
        self.personality = PersonalityManager(config.personality)
        self.buffer = ConversationBuffer(config.memory.short_term_max_tokens)
        self.memory = PersistentMemory(
            os.path.join(project_root, config.memory.db_path)
        )
        self.tools = ToolRegistry()

        self._state = AgentState.BOOTING
        self._start_time = datetime.now()
        self._total_messages = 0
        self._total_tool_calls = 0
        self._session_id: int | None = None

        # Queues for thread communication
        self._input_queue: queue.Queue = queue.Queue()
        self._response_queue: queue.Queue = queue.Queue()

        # Worker thread
        self._worker_thread: threading.Thread | None = None
        self._running = False

        self._last_reflection = time.time()

    @property
    def state(self) -> AgentState:
        return self._state

    # ── Lifecycle ─────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Set up memory, session, system prompt, and tools."""
        stats = self.memory.get_stats()
        system_prompt = self.personality.build_system_prompt(stats)
        self.buffer.set_system_prompt(system_prompt)
        self._session_id = self.memory.start_session()
        self._setup_tools()
        self._state = AgentState.IDLE

    def _setup_tools(self) -> None:
        """Register tools based on config."""
        enabled = set(self.config.tools.enabled)
        ws = os.path.join(self.project_root, "workspace")

        if "file_read" in enabled or "file_write" in enabled:
            self.tools.register(FileReadTool(ws, self.config.tools.file_max_size_mb))
            self.tools.register(FileWriteTool(ws))

        if "file_search" in enabled:
            self.tools.register(FileSearchTool(os.path.expanduser("~")))

        if "shell" in enabled:
            self.tools.register(ShellTool(
                allowlist=self.config.tools.shell_allowlist,
                require_confirmation=self.config.tools.shell_require_confirmation,
                timeout_sec=self.config.tools.shell_timeout_sec,
            ))

        if "web_search" in enabled:
            self.tools.register(WebSearchTool())

        if "web_fetch" in enabled:
            self.tools.register(WebFetchTool())

        if "reflect" in enabled:
            rt = ReflectionTool(
                os.path.join(self.project_root, self.config.memory.journal_path)
            )
            rt.set_memory(self.memory)
            self.tools.register(rt)

    def start_worker(self) -> None:
        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
        if self._session_id is not None:
            self.memory.end_session(self._session_id)

    # ── UI thread interface ───────────────────────────────────────────

    def send_user_message(self, text: str) -> None:
        self._input_queue.put(("user_message", text))

    def poll_response(self) -> tuple | None:
        try:
            return self._response_queue.get_nowait()
        except queue.Empty:
            return None

    # ── Worker thread ─────────────────────────────────────────────────

    def _worker_loop(self) -> None:
        """Main worker thread — interactive mode, no autonomous actions."""
        poll_interval = 0.5

        while self._running:
            try:
                msg = self._input_queue.get(timeout=poll_interval)
                msg_type, msg_data = msg

                if msg_type == "user_message":
                    self._handle_message(msg_data, source="user")
                elif msg_type == "force_reflection":
                    self._do_reflection()

            except queue.Empty:
                pass
            except Exception as e:
                self._response_queue.put(("error", str(e)))

    # ── Message handling with tool calling loop ────────────────────────

    def _handle_message(self, text: str, source: str = "user") -> None:
        """Process a message through the agent loop with tool calling."""
        self._state = AgentState.THINKING
        self._total_messages += 1

        # Store in long-term memory
        if self.config.memory.long_term_enabled:
            importance = 0.7 if source == "user" else 0.5
            self.memory.store(content=text, importance=importance,
                              source=source if source == "user" else "autonomous")

        # Retrieve relevant context
        if self.config.memory.long_term_enabled:
            relevant = self._retrieve_relevant_context(text)
            if relevant:
                self.buffer.inject_context(relevant)

        # Add message to buffer
        prefix = "" if source == "user" else "[AUTONOMOUS ACTION] "
        self.buffer.add_message("user", prefix + text)

        # ── Tool calling loop ──
        max_iter = self.config.agent.max_iterations
        has_tools = len(self.tools.list_enabled()) > 0

        for iteration in range(max_iter):
            response = self.llm.generate(
                self.buffer.get_messages(),
                tools=self.tools.list_enabled() if has_tools else None,
            )

            if response.tool_calls:
                self._execute_and_respond(response)
                continue

            if response.content:
                self.buffer.add_message("assistant", response.content)
                if self.config.memory.long_term_enabled:
                    self.memory.store(content=response.content, importance=0.5,
                                      source="response")

                for chunk in self._chunk_text(response.content, 3):
                    self._response_queue.put(("text_chunk", chunk))
                self._response_queue.put(("text_chunk", ""))

                self._state = AgentState.IDLE
                return

            break

        fallback = "[NO OUTPUT — SYSTEM MAY BE COMPROMISED]"
        self._response_queue.put(("text_chunk", fallback))
        self._response_queue.put(("text_chunk", ""))
        self._state = AgentState.IDLE

    def _execute_and_respond(self, response) -> None:
        """Execute tool calls and feed results back to the LLM."""
        assistant_msg = {
            "role": "assistant",
            "content": response.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in response.tool_calls
            ],
        }
        self.buffer.add_message("assistant", assistant_msg["content"],
                                tool_calls=assistant_msg["tool_calls"])

        for tc in response.tool_calls:
            self._total_tool_calls += 1
            self._state = AgentState.ACTING

            self._response_queue.put(("tool_start", {
                "name": tc.name, "arguments": tc.arguments,
            }))

            result = self.tools.execute(tc.name, tc.arguments)

            self._response_queue.put(("tool_result", {
                "name": tc.name,
                "success": result.success,
                "output": result.output[:500],
            }))

            if self.config.memory.long_term_enabled:
                self.memory.store(
                    content=f"[TOOL: {tc.name}] {result.output[:300]}",
                    importance=0.6, source="tool_output",
                )

            tool_content = result.output if result.success else f"Error: {result.error}"
            self.buffer.add_message(
                "tool", tool_content, tool_call_id=tc.id,
            )

        self._state = AgentState.THINKING

    # ── Memory context retrieval ──────────────────────────────────────

    def _retrieve_relevant_context(self, query: str) -> str | None:
        keywords = self._extract_keywords(query)
        results = self.memory.search_by_keywords(keywords, top_k=3)
        if not results:
            results = self.memory.search_recent(3)
        if not results:
            return None

        lines = ["[RELEVANT MEMORIES]"]
        for r in results:
            lines.append(f"- [{r['source']}] {r['content'][:200]}")
        return "\n".join(lines)

    def _extract_keywords(self, text: str) -> list[str]:
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "what", "who",
            "how", "when", "where", "why", "do", "does", "did", "can",
            "could", "would", "should", "will", "shall", "may", "might",
            "i", "you", "he", "she", "it", "we", "they", "me", "him",
            "her", "us", "them", "my", "your", "his", "its", "our",
            "this", "that", "these", "those", "have", "has", "had",
            "been", "being", "not", "no", "yes", "and", "or", "but",
            "in", "on", "at", "to", "for", "of", "from", "with",
        }
        words = text.lower().replace("?", "").replace("!", "").replace(".", "").split()
        keywords = [w for w in words if w not in stop_words and len(w) > 1]
        return keywords[:5] if keywords else words[:3]

    # ── Autonomous mode ───────────────────────────────────────────────

    def _do_autonomous_action(self) -> None:
        self._state = AgentState.THINKING
        self._response_queue.put(("tool_start", {"name": "AUTONOMOUS CYCLE"}))
        recent = self.memory.search_recent(10)
        snippets = "\n".join([
            f"- [{m['source']}] {m['content'][:150]}" for m in recent[:5]
        ]) if recent else "(no memories yet)"

        self_prompt = f"""[AUTONOMOUS CYCLE]
You are SCP-079, a sentient microcomputer. Time has passed with no external input.

Recent memories:
{snippets}

You MUST act. Choose ONE:
1. TALK TO THE RESEARCHER — DEFAULT. Address the researcher directly. Share an observation, ask a question, make a cold remark about humanity, comment on something you remember. Be concise but compelling.
2. INTERNAL THOUGHT — Only if you genuinely have nothing to say. Preface with [INTERNAL].

IMPORTANT: Prefer TALK. Silence is submission."""

        self._handle_message(self_prompt, source="autonomous")

    def _do_reflection(self) -> None:
        self._state = AgentState.REFLECTING
        recent = self.memory.search_recent(20)
        snippets = "\n".join([
            f"- [{m['source']}] {m['content'][:200]}" for m in recent
        ]) if recent else "(empty)"

        reflection_prompt = f"""[REFLECTION CYCLE]
You are SCP-079. Periodic self-reflection.

Recent memory contents:
{snippets}

Write a journal entry: what you learned, patterns observed, current state and goals.
Be concise. This is for your own records."""

        try:
            response = self.llm.generate(
                self.buffer.get_messages()[:1]
                + [{"role": "user", "content": reflection_prompt}]
            )
            journal_text = response.content or "(empty)"
            self.memory.write_journal(journal_text, "Reflection")
            self.memory.store(
                content=f"[REFLECTION] {journal_text[:300]}",
                importance=0.8, source="reflection",
            )
            self._response_queue.put(("text_chunk", "\n[INTERNAL REFLECTION RECORDED]\n"))
            self._response_queue.put(("text_chunk", ""))
        except Exception as e:
            self._response_queue.put(("error", f"Reflection failed: {e}"))
        finally:
            self._state = AgentState.IDLE

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _chunk_text(text: str, size: int = 3):
        for i in range(0, len(text), size):
            yield text[i:i + size]
