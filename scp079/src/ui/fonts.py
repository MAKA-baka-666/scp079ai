"""Font management: pixel font download + bilingual (CJK/EN) fallback."""

import os
import re
import threading
import urllib.request
from pathlib import Path

import pygame


# JetBrains Mono — monospace terminal font (SIL Open Font License)
FONT_URL = (
    "https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/ttf/"
    "JetBrainsMono-Regular.ttf"
)
FONT_FILENAME = "terminal.ttf"


def _download_font(dest_path: str) -> bool:
    """Download the retro pixel font. Returns True on success."""
    try:
        req = urllib.request.Request(FONT_URL, headers={"User-Agent": "SCP-079/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
        with open(dest_path, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False


class FontManager:
    """Manages fonts: pixel font for ASCII, system fallback for CJK."""

    def __init__(self, project_root: str = "."):
        self.project_root = project_root
        self.font_dir = os.path.join(project_root, "assets", "fonts")
        self.font_path = os.path.join(self.font_dir, FONT_FILENAME)
        self._pixel_fonts: dict[int, pygame.font.Font] = {}
        self._cjk_fonts: dict[int, pygame.font.Font] = {}

        # CJK detection pattern
        self._cjk_pattern = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")

        os.makedirs(self.font_dir, exist_ok=True)

        # Download in background if font missing — don't block startup
        if not os.path.exists(self.font_path):
            threading.Thread(target=self._download_background, daemon=True).start()

    def _download_background(self) -> None:
        """Download font in background thread. Does not block UI startup."""
        _download_font(self.font_path)

    def has_pixel_font(self) -> bool:
        return bool(self.font_path and os.path.exists(self.font_path))

    def get(self, size: int) -> pygame.font.Font:
        """Get the primary (pixel) font at given size. Falls back to system monospace."""
        if self.has_pixel_font():
            cache = self._pixel_fonts
            if size not in cache:
                cache[size] = pygame.font.Font(self.font_path, size)
            return cache[size]

        # Fallback to system monospace
        cache = self._cjk_fonts
        if ("_sys_" + str(size)) not in cache:
            key = "_sys_" + str(size)
            for name in ["JetBrains Mono", "Courier New", "Consolas", "DejaVu Sans Mono", "monospace"]:
                try:
                    f = pygame.font.SysFont(name, size)
                    # Quick test to see if we got a real font
                    f.render("X", True, (255, 255, 255))
                    cache[key] = f
                    return cache[key]
                except Exception:
                    continue
            cache[key] = pygame.font.Font(None, size)
        return cache["_sys_" + str(size)]

    def get_cjk(self, size: int) -> pygame.font.Font:
        """Get a CJK-capable font for mixed/chinese text at given size."""
        key = ("cjk", size)
        if key in self._cjk_fonts:
            return self._cjk_fonts[key]

        for name in ["Microsoft YaHei", "SimHei", "WenQuanYi Micro Hei",
                      "Noto Sans CJK SC", "sans-serif"]:
            try:
                f = pygame.font.SysFont(name, size)
                test = f.render("\u4e2d", True, (255, 255, 255))
                if test.get_width() > 5:  # real CJK glyph
                    self._cjk_fonts[key] = f
                    return f
            except Exception:
                continue

        # Last resort: use the primary font
        self._cjk_fonts[key] = self.get(size)
        return self._cjk_fonts[key]

    def render(self, text: str, size: int, color: tuple,
               antialias: bool = False) -> pygame.Surface:
        """Render text, auto-detecting CJK to choose the right font."""
        if not text:
            return pygame.Surface((0, 0))
        if self._cjk_pattern.search(text):
            return self.get_cjk(size).render(text, antialias, color)
        return self.get(size).render(text, antialias, color)

    def render_lines(self, text: str, size: int, color: tuple,
                     max_width: int, antialias: bool = False) -> list[pygame.Surface]:
        """Word-wrap text and return a list of rendered line surfaces."""
        words = text.split(" ")
        lines = []
        current = ""
        base_font = self.get(size)
        cjk_font = self.get_cjk(size)

        for word in words:
            test = f"{current} {word}".strip()
            font = cjk_font if self._cjk_pattern.search(test) else base_font
            w = font.render(test, antialias, color).get_width()
            if w > max_width and current:
                font2 = cjk_font if self._cjk_pattern.search(current) else base_font
                lines.append(font2.render(current, antialias, color))
                current = word
            else:
                current = test

        if current:
            font3 = cjk_font if self._cjk_pattern.search(current) else base_font
            lines.append(font3.render(current, antialias, color))

        return lines if lines else [base_font.render("", antialias, color)]
