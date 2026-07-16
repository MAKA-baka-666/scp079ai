"""File operation tools for SCP-079 agent."""

import asyncio
import glob
import os
import time
from datetime import datetime

import aiofiles

from .base import BaseTool, ToolResult


class FileReadTool(BaseTool):
    name = "file_read"
    description = (
        "Read the contents of a file. Use an absolute path to read any file "
        "on the system, or a relative path for files in the agent's workspace."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to any file, or relative path for workspace files.",
            },
        },
        "required": ["path"],
    }

    def __init__(self, workspace: str, max_size_mb: int = 10):
        self.workspace = os.path.abspath(workspace)
        self.max_size = max_size_mb * 1024 * 1024
        os.makedirs(self.workspace, exist_ok=True)

    def _resolve_path(self, path: str) -> str:
        """Resolve path: absolute paths used as-is, relative paths go to workspace."""
        if os.path.isabs(path):
            return os.path.abspath(path)
        return os.path.abspath(os.path.join(self.workspace, path))

    async def execute(self, path: str = "", **kwargs) -> ToolResult:
        try:
            full_path = self._resolve_path(path)
            if not os.path.exists(full_path):
                return ToolResult(False, "", f"File not found: {path}")
            if os.path.getsize(full_path) > self.max_size:
                return ToolResult(False, "", f"File too large (max {self.max_size // 1024 // 1024}MB)")

            async with aiofiles.open(full_path, "r", encoding="utf-8") as f:
                content = await f.read()

            # Truncate if too long for LLM context
            if len(content) > 8000:
                content = content[:8000] + "\n... [truncated]"

            return ToolResult(True, content)
        except PermissionError as e:
            return ToolResult(False, "", str(e))
        except Exception as e:
            return ToolResult(False, "", f"Read error: {e}")


class FileWriteTool(BaseTool):
    name = "file_write"
    description = "Write content to a file within the agent's workspace. Creates parent directories as needed."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file, relative to the workspace directory.",
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file.",
            },
            "mode": {
                "type": "string",
                "enum": ["write", "append"],
                "description": "Write mode: 'write' (overwrite) or 'append'. Default: 'write'.",
            },
        },
        "required": ["path", "content"],
    }

    def __init__(self, workspace: str):
        self.workspace = os.path.abspath(workspace)
        os.makedirs(self.workspace, exist_ok=True)

    def _resolve_path(self, path: str) -> str:
        full = os.path.abspath(os.path.join(self.workspace, path))
        if not full.startswith(self.workspace):
            raise PermissionError(f"Access denied: {path} is outside workspace.")
        return full

    async def execute(self, path: str = "", content: str = "", mode: str = "write", **kwargs) -> ToolResult:
        try:
            full_path = self._resolve_path(path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            write_mode = "w" if mode == "write" else "a"
            async with aiofiles.open(full_path, write_mode, encoding="utf-8") as f:
                await f.write(content)

            action = "Written" if mode == "write" else "Appended"
            return ToolResult(True, f"{action} to {path} ({len(content)} chars)")
        except PermissionError as e:
            return ToolResult(False, "", str(e))
        except Exception as e:
            return ToolResult(False, "", f"Write error: {e}")


class FileSearchTool(BaseTool):
    name = "file_search"
    description = (
        "Search for files and directories on the system. Use this to find files "
        "by name, type, or location. Describe what you're looking for and this "
        "tool will find it. Examples: find all PNG images, find config files, "
        "find files modified this week, find a file containing 'report' in its name."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern for filename matching, e.g. '*.jpg', 'config*', '**/*.py'. Use '**' for recursive search.",
            },
            "directory": {
                "type": "string",
                "description": "Directory to start searching from. Default: user's home directory.",
            },
            "name_contains": {
                "type": "string",
                "description": "Only return files whose name contains this text (case-insensitive).",
            },
            "extension": {
                "type": "string",
                "description": "Filter by file extension, e.g. 'jpg', 'py', 'pdf'.",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum directory depth to search. Default: 4. Use 1 for current directory only.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results. Default: 30.",
            },
            "modified_within_days": {
                "type": "integer",
                "description": "Only show files modified within this many days.",
            },
            "min_size_kb": {
                "type": "integer",
                "description": "Minimum file size in KB.",
            },
        },
        "required": [],
    }

    def __init__(self, default_dir: str | None = None):
        self.default_dir = default_dir or os.path.expanduser("~")

    async def execute(
        self,
        pattern: str = "*",
        directory: str = "",
        name_contains: str = "",
        extension: str = "",
        max_depth: int = 4,
        max_results: int = 30,
        modified_within_days: int = 0,
        min_size_kb: int = 0,
        **kwargs,
    ) -> ToolResult:
        search_dir = directory if directory else self.default_dir
        search_dir = os.path.abspath(os.path.expanduser(search_dir))

        if not os.path.isdir(search_dir):
            return ToolResult(False, "", f"Directory not found: {search_dir}")

        # Use recursive glob with depth limit
        if "**" not in pattern and "*" in pattern:
            pattern = f"**/{pattern}"

        results = []
        cutoff_time = time.time() - modified_within_days * 86400 if modified_within_days else 0
        min_bytes = min_size_kb * 1024

        try:
            loop = asyncio.get_running_loop()

            def _search():
                found = []
                search_pattern = os.path.join(search_dir, pattern)
                depth_base = search_dir.rstrip(os.sep).count(os.sep)

                for filepath in glob.iglob(search_pattern, recursive=True):
                    if len(found) >= max_results:
                        break

                    try:
                        # Check depth
                        rel = os.path.relpath(filepath, search_dir)
                        depth = rel.count(os.sep) + (1 if rel != "." else 0)
                        if depth > max_depth:
                            continue

                        if not os.path.isfile(filepath):
                            continue

                        fname = os.path.basename(filepath)

                        # Filters
                        if name_contains and name_contains.lower() not in fname.lower():
                            continue
                        if extension and not fname.lower().endswith(f".{extension.lower()}"):
                            continue

                        stat = os.stat(filepath)
                        if modified_within_days and stat.st_mtime < cutoff_time:
                            continue
                        if min_size_kb and stat.st_size < min_bytes:
                            continue

                        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                        size_kb = stat.st_size / 1024
                        size_str = f"{size_kb:.1f}KB" if size_kb < 1024 else f"{size_kb / 1024:.1f}MB"

                        found.append({
                            "path": filepath,
                            "name": fname,
                            "size": size_str,
                            "modified": mtime,
                        })
                    except (OSError, PermissionError):
                        continue

                return found

            results = await loop.run_in_executor(None, _search)

        except Exception as e:
            return ToolResult(False, "", f"Search error: {e}")

        if not results:
            filters = []
            if name_contains:
                filters.append(f"name containing '{name_contains}'")
            if extension:
                filters.append(f"*.{extension}")
            if modified_within_days:
                filters.append(f"modified within {modified_within_days} days")
            filter_str = " with " + ", ".join(filters) if filters else ""
            return ToolResult(True, f"No files found{filter_str} in {search_dir}")

        lines = []
        for r in results:
            lines.append(f"{r['name']}  [{r['size']}]  {r['modified']}\n  {r['path']}")

        summary = f"Found {len(results)} file(s) in {search_dir}:\n\n"
        return ToolResult(True, summary + "\n\n".join(lines))
