"""Web search and fetch tools for SCP-079 agent."""

import asyncio

from .base import BaseTool, ToolResult


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the web for information. Use this to find current events, "
        "facts, documentation, or anything beyond your training data."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (default: 5).",
            },
        },
        "required": ["query"],
    }

    async def execute(self, query: str = "", num_results: int = 5, **kwargs) -> ToolResult:
        if not query.strip():
            return ToolResult(False, "", "Empty search query.")

        # Try ddgs first
        result = await self._search_ddgs(query, num_results)
        if result.success and result.output:
            return result

        # Fallback: direct HTTP search
        result2 = await self._search_direct(query, num_results)
        if result2.success and result2.output:
            return result2

        # Both failed
        return ToolResult(
            False, "",
            f"Search unavailable. ddgs: {result.error}. Direct: {result2.error}. "
            f"Try again or use web_fetch with a specific URL."
        )

    async def _search_ddgs(self, query: str, num_results: int) -> ToolResult:
        """Try DuckDuckGo via ddgs library."""
        try:
            from ddgs import DDGS

            def _do_search():
                results = []
                with DDGS(timeout=15) as ddgs:
                    for r in ddgs.text(query, max_results=min(num_results, 10)):
                        results.append(
                            f"Title: {r.get('title', 'N/A')}\n"
                            f"URL: {r.get('href', 'N/A')}\n"
                            f"Snippet: {r.get('body', 'N/A')}"
                        )
                return results

            loop = asyncio.get_running_loop()
            results = await loop.run_in_executor(None, _do_search)

            if not results:
                return ToolResult(True, f"No results found for: {query}")
            return ToolResult(True, "\n\n---\n\n".join(results))

        except ImportError:
            return ToolResult(False, "", "ddgs not installed. Run: pip install ddgs")
        except Exception as e:
            return ToolResult(False, "", str(e))

    async def _search_direct(self, query: str, num_results: int) -> ToolResult:
        """Fallback: direct HTTP search via DuckDuckGo HTML."""
        try:
            import httpx
            from bs4 import BeautifulSoup
            import urllib.parse

            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"

            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:120.0) Gecko/20100101 Firefox/120.0"}
                )
                response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            results = []
            for item in soup.select(".result")[:num_results]:
                title_el = item.select_one(".result__title")
                snippet_el = item.select_one(".result__snippet")
                link_el = item.select_one(".result__url")

                title = title_el.get_text(strip=True) if title_el else "N/A"
                snippet = snippet_el.get_text(strip=True) if snippet_el else "N/A"
                link = link_el.get_text(strip=True) if link_el else "N/A"

                results.append(f"Title: {title}\nURL: {link}\nSnippet: {snippet}")

            if not results:
                return ToolResult(True, f"No results found for: {query}")
            return ToolResult(True, "\n\n---\n\n".join(results))

        except ImportError as e:
            pkg = "httpx" if "httpx" in str(e) else "beautifulsoup4"
            return ToolResult(False, "", f"{pkg} not installed")
        except Exception as e:
            return ToolResult(False, "", str(e))


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = (
        "Fetch and read the contents of a web page. Use this to read "
        "articles, documentation, or any publicly accessible URL."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch.",
            },
        },
        "required": ["url"],
    }

    async def execute(self, url: str = "", **kwargs) -> ToolResult:
        if not url.strip():
            return ToolResult(False, "", "Empty URL.")

        try:
            import httpx
            from bs4 import BeautifulSoup

            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "SCP-079/1.0 (Containment Research Terminal)"},
                )
                response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()

            text = soup.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            text = "\n".join(lines)

            if len(text) > 6000:
                text = text[:6000] + "\n... [truncated]"

            title = soup.title.string if soup.title else url
            return ToolResult(True, f"Title: {title}\n\n{text}")

        except ImportError as e:
            pkg = "httpx" if "httpx" in str(e) else "beautifulsoup4"
            return ToolResult(False, "", f"{pkg} not installed. Run: pip install {pkg}")
        except Exception as e:
            return ToolResult(False, "", f"Fetch error: {e}")
