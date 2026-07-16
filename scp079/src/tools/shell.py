"""Shell command execution tool with safety gates."""

import asyncio
import os

from .base import BaseTool, ToolResult


class ShellTool(BaseTool):
    name = "shell"
    description = (
        "Execute a shell command. Commands that modify files or the system "
        "require user confirmation. Use this to explore the file system, "
        "run scripts, or interact with the environment."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
        },
        "required": ["command"],
    }

    def __init__(
        self,
        allowlist: list[str] | None = None,
        require_confirmation: bool = True,
        timeout_sec: int = 30,
    ):
        self.allowlist = allowlist or []
        self.require_confirmation = require_confirmation
        self.timeout = timeout_sec

        # Commands that always need confirmation (destructive)
        self._dangerous = {
            "rm", "del", "rmdir", "format", "mkfs", "dd",
            "shutdown", "reboot", "taskkill", "kill",
            "wget", "curl", "chmod", "chown",
        }

    def _needs_confirmation(self, command: str) -> bool:
        """Check if this command needs user approval."""
        if not self.require_confirmation:
            return False
        # Allowlisted commands skip confirmation
        first_word = command.strip().split()[0].lower() if command.strip() else ""
        if first_word in [a.lower() for a in self.allowlist]:
            return False
        # Dangerous commands always need confirmation
        if first_word in self._dangerous:
            return True
        # Commands that write/modify
        if any(kw in command.lower() for kw in [">", ">>", "|", "rm ", "mv ", "cp "]):
            return True
        return False

    async def execute(self, command: str = "", **kwargs) -> ToolResult:
        if not command.strip():
            return ToolResult(False, "", "Empty command.")

        # Safety check
        if self._needs_confirmation(command):
            return ToolResult(
                False,
                "",
                f"CONFIRMATION REQUIRED: The command '{command[:80]}' "
                f"needs user approval. The researcher must explicitly "
                f"authorize this action.",
            )

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.getcwd(),
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )

            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")

            # Build result
            result_parts = []
            if out.strip():
                result_parts.append(out[:4000])
            if err.strip():
                result_parts.append(f"[STDERR]\n{err[:2000]}")

            output = "\n".join(result_parts) if result_parts else "(no output)"
            if len(output) > 6000:
                output = output[:6000] + "\n... [truncated]"

            success = proc.returncode == 0
            return ToolResult(
                success=success,
                output=output,
                error=None if success else f"Exit code: {proc.returncode}",
            )

        except asyncio.TimeoutError:
            return ToolResult(False, "", f"Command timed out after {self.timeout}s")
        except Exception as e:
            return ToolResult(False, "", f"Shell error: {e}")
