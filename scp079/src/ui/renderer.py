"""SCP containment terminal renderer.

Draws each zone of the CRT display:
  - Top banner: SCP Foundation classification header
  - Status bar: containment status, object ID, clearance level
  - Face area: the Exidy Sorcerer / CRT monitor (SCP-079's "face")
  - Dialogue area: agent text responses
  - Input area: user input prompt
  - Bottom bar: function key hints
"""

from enum import Enum, auto
from typing import Optional

import pygame

from .fonts import FontManager


class UIMode(Enum):
    BOOT_SEQUENCE = auto()
    IDLE = auto()
    TYPING = auto()
    ERROR = auto()
    SHUTDOWN = auto()


# Hacker terminal green color palette
COLORS = {
    "bg": (5, 10, 5),
    "text": (0, 210, 40),           # #00d228 deep phosphor green
    "text_dim": (0, 130, 25),       # #008219 darker green
    "text_bright": (60, 255, 100),  # #3cff64 highlight
    "warning": (255, 204, 0),       # #ffcc00 amber
    "error": (255, 51, 51),         # #ff3333 red
    "border": (0, 180, 35),
    "banner_bg": (0, 20, 0),
    "face_screen": (8, 25, 8),
    "face_border": (60, 60, 60),
    "input_bg": (10, 25, 10),
    "bar_bg": (8, 18, 8),
}


class TerminalRenderer:
    """Renders the SCP containment terminal UI zones."""

    def __init__(self, config, width: int, height: int, project_root: str = "."):
        self.full_config = config
        self.config = config.ui  # UIConfig
        self.width = width
        self.height = height
        self.project_root = project_root

        # Layout zones (calculated on resize)
        self._calc_zones()

        # Fonts (initialized after pygame.init)
        self.fonts: FontManager | None = None
        self._font_size = self.config.font_size
        self._effects = None  # CRTEffects reference, set by window

        # Face images
        self.face_normal: pygame.Surface | None = None
        self.face_erro: pygame.Surface | None = None
        self._use_images = False

        # Track hostility for face switching
        self.hostility_face = False  # True = show erro face

        # State
        self.mode = UIMode.IDLE

        self.displayed_text = ""       # Text currently shown (for typewriter)
        self.full_response_text = ""   # Complete response text
        self.typewriter_index = 0
        self.typewriter_timer = 0.0

        self.user_input = ""           # Current input buffer
        self.cursor_visible = True
        self.cursor_timer = 0.0

        # CLI history: list of (role, text) — "user" or "scp079"
        self.terminal_history: list[tuple[str, str]] = []
        self._pending_scp079_response: str | None = None

        # Face animation
        self.face_glitch_timer = 0.0

        # Tool call display
        self.tool_call_text: Optional[str] = None
        self.tool_call_timer = 0.0

    def _calc_zones(self) -> None:
        """Calculate layout zones: full-window terminal."""
        w, h = self.width, self.height

        margin_x = 72 if self.config.crt_bezel else 60
        margin_top = 20 if self.config.crt_bezel else 8
        margin_bottom = 16

        self.face_rect = pygame.Rect(0, 0, 0, 0)  # unused in normal mode

        self.term_rect = pygame.Rect(
            margin_x,
            margin_top,
            w - margin_x * 2,
            h - margin_top - margin_bottom,
        )

    def resize(self, width: int, height: int) -> None:
        """Handle window resize: recalculate layout zones."""
        self.width = width
        self.height = height
        self._calc_zones()

    def init_fonts(self) -> None:
        """Initialize font manager and load face images. Call after pygame.init()."""
        self.fonts = FontManager(self.project_root)
        self._load_face_images()

    def _load_face_images(self) -> None:
        """Load SCP-079 face images from project root."""
        import os
        normal_path = os.path.join(self.project_root, "079.jpg")
        erro_path = os.path.join(self.project_root, "erro.jpg")

        try:
            if os.path.exists(normal_path):
                self.face_normal = pygame.image.load(normal_path)
                self._use_images = True
        except Exception:
            pass

        try:
            if os.path.exists(erro_path):
                self.face_erro = pygame.image.load(erro_path)
                self._use_images = True
        except Exception:
            pass

    def set_hostility_face(self, active: bool) -> None:
        """Switch to erro face (True) or normal face (False)."""
        self.hostility_face = active

    def add_user_to_history(self, text: str) -> None:
        """Record user message in CLI history."""
        self.terminal_history.append(("user", text))
        # Trim old entries
        if len(self.terminal_history) > 200:
            self.terminal_history = self.terminal_history[-200:]

    def commit_pending_response(self) -> None:
        """Record the pending agent response in CLI history."""
        if self._pending_scp079_response:
            self.terminal_history.append(("scp079", self._pending_scp079_response))
            self._pending_scp079_response = None
        self.displayed_text = ""  # clear to prevent duplicate rendering

    def set_pending_response(self, text: str) -> None:
        """Store the complete agent response text, to be committed after typing."""
        self._pending_scp079_response = text

    # ── Typewriter effect ─────────────────────────────────────────────

    def start_typing(self, full_text: str) -> None:
        """Begin typewriter-revealing the response text."""
        self.mode = UIMode.TYPING
        self.full_response_text = full_text
        self.typewriter_index = 0
        self.typewriter_timer = 0.0
        self.displayed_text = ""

    def update_typing(self, dt: float) -> bool:
        """Update typewriter animation. Returns True when typing is done."""
        if self.typewriter_index >= len(self.full_response_text):
            self.mode = UIMode.IDLE
            return True

        self.typewriter_timer += dt
        chars_per_tick = max(1, int(dt / self.config.typewriter_speed))
        if self.typewriter_timer >= self.config.typewriter_speed:
            self.typewriter_timer = 0.0
            self.typewriter_index += chars_per_tick
            self.typewriter_index = min(
                self.typewriter_index, len(self.full_response_text)
            )
            self.displayed_text = self.full_response_text[:self.typewriter_index]

        return False

    def finish_typing(self) -> None:
        """Instantly show all remaining text."""
        self.typewriter_index = len(self.full_response_text)
        self.displayed_text = self.full_response_text
        self.mode = UIMode.IDLE

    # ── Input handling ────────────────────────────────────────────────

    def handle_input_char(self, char: str) -> None:
        """Add a character to the input buffer."""
        self.user_input += char

    def handle_backspace(self) -> None:
        """Remove last character from input buffer."""
        self.user_input = self.user_input[:-1]

    def submit_input(self) -> str:
        """Return current input and clear buffer."""
        text = self.user_input
        self.user_input = ""
        return text

    # ── Main render ───────────────────────────────────────────────────

    def render(self, screen: pygame.Surface, dt: float) -> None:
        """Render: CRT bezel → terminal dialogue."""
        screen.fill(COLORS["bg"])

        if self.config.crt_bezel:
            self._render_bezel(screen)

        self._render_dialogue(screen, dt)
        self._render_tool_status(screen, dt)

    def render_screensaver(self, screen: pygame.Surface, dt: float) -> None:
        """Render the idle screensaver: fullscreen face only."""
        screen.fill((0, 0, 0))
        w, h = screen.get_width(), screen.get_height()

        face_r = pygame.Rect(0, 0, w, h)
        if self._use_images:
            self._render_face_image(screen, face_r, dt)
        else:
            self._draw_exidy_sorcerer(screen, face_r, dt)

    def _render_bezel(self, screen: pygame.Surface) -> None:
        """Draw a CRT monitor bezel/frame around the display area."""
        w, h = self.width, self.height
        bezel_margin = 12
        bezel_color = (30, 28, 26)
        bezel_highlight = (55, 52, 48)
        bezel_shadow = (15, 14, 12)

        # Outer frame
        outer = pygame.Rect(bezel_margin, bezel_margin, w - bezel_margin * 2, h - bezel_margin * 2)
        pygame.draw.rect(screen, bezel_color, outer, border_radius=8)
        # Inner highlight (top-left edge)
        pygame.draw.rect(screen, bezel_highlight, outer, 3, border_radius=8)
        # Darker shadow line
        inner = pygame.Rect(
            bezel_margin + 3, bezel_margin + 3,
            w - (bezel_margin + 3) * 2, h - (bezel_margin + 3) * 2,
        )
        pygame.draw.rect(screen, bezel_shadow, inner, 2, border_radius=6)

    def _render_banner(self, screen: pygame.Surface) -> None:
        """Top classification banner."""
        pygame.draw.rect(screen, COLORS["banner_bg"], self.banner_rect)
        if self.fonts:
            title = self.fonts.render(
                "SCP FOUNDATION — CONTAINMENT TERMINAL", 14, COLORS["text"]
            )
            title_rect = title.get_rect(center=self.banner_rect.center)
            screen.blit(title, title_rect)

    def _render_status_bar(self, screen: pygame.Surface) -> None:
        """Status bar below the banner."""
        pygame.draw.rect(screen, COLORS["bar_bg"], self.status_rect)
        if self.fonts:
            status_text = (
                "CONTAINMENT: ACTIVE  |  OBJECT: SCP-079  |  "
                "CLASS: EUCLID  |  CLEARANCE: LEVEL 4"
            )
            surf = self.fonts.render(status_text, 12, COLORS["text_dim"])
            rect = surf.get_rect(center=self.status_rect.center)
            screen.blit(surf, rect)

    def _render_separator(self, screen: pygame.Surface, y: int) -> None:
        """Horizontal separator line."""
        pygame.draw.line(screen, COLORS["border"], (0, y), (self.width, y), 1)
        pygame.draw.line(
            screen, COLORS["text_dim"], (0, y + 1), (self.width, y + 1), 1
        )

    def _render_face_image(
        self, screen: pygame.Surface, r: pygame.Rect, dt: float
    ) -> None:
        """Display the face using the loaded images."""
        # Choose which face to show
        if self.hostility_face and self.face_erro:
            img = self.face_erro
        elif self.face_normal:
            img = self.face_normal
        else:
            img = self.face_erro or self.face_normal
            if not img:
                self._draw_exidy_sorcerer(screen, r, dt)
                return

        # Scale image to fit the face rect while maintaining aspect ratio
        img_w, img_h = img.get_size()
        max_w, max_h = r.width, r.height
        scale = min(max_w / img_w, max_h / img_h)
        new_w, new_h = int(img_w * scale), int(img_h * scale)

        scaled = pygame.transform.smoothscale(img, (new_w, new_h))

        # Center in face rect
        x = r.x + (r.width - new_w) // 2
        y = r.y + (r.height - new_h) // 2

        screen.blit(scaled, (x, y))

    def _draw_exidy_sorcerer(
        self, screen: pygame.Surface, r: pygame.Rect, dt: float
    ) -> None:
        """Draw a pixel-art Exidy Sorcerer microcomputer."""
        cx, cy = r.centerx, r.centery
        w, h = r.width, r.height

        # ── COMPUTER BODY (main case) ──
        body_w = int(w * 0.72)
        body_h = int(h * 0.88)
        body_x = cx - body_w // 2
        body_y = cy - body_h // 2 + 8

        body_rect = pygame.Rect(body_x, body_y, body_w, body_h)
        case_color = (50, 48, 45)
        case_dark = (35, 33, 30)
        case_light = (70, 68, 64)

        # Main case
        pygame.draw.rect(screen, case_color, body_rect, border_radius=4)
        pygame.draw.rect(screen, case_light, body_rect, 2, border_radius=4)

        # Case highlight (top edge)
        hl_rect = pygame.Rect(body_x + 2, body_y + 2, body_w - 4, 3)
        pygame.draw.rect(screen, (90, 88, 84), hl_rect)

        # ── CRT MONITOR SCREEN ──
        screen_w = int(body_w * 0.78)
        screen_h = int(body_h * 0.55)
        screen_x = cx - screen_w // 2
        screen_y = body_y + int(body_h * 0.08)

        # Screen bezel (outer)
        bezel_rect = pygame.Rect(
            screen_x - 6, screen_y - 6, screen_w + 12, screen_h + 12
        )
        pygame.draw.rect(screen, case_dark, bezel_rect, border_radius=3)

        # Screen bezel inner border
        pygame.draw.rect(screen, case_light, bezel_rect, 2, border_radius=3)

        # CRT screen (the actual display)
        crt_rect = pygame.Rect(screen_x, screen_y, screen_w, screen_h)

        # CRT glow effect
        glow_alpha = 40 + int(20 * (1 + __import__("math").sin(dt * 1.5)) * 0.5)
        for i in range(3, 0, -1):
            glow_rect = pygame.Rect(
                screen_x - i, screen_y - i, screen_w + i * 2, screen_h + i * 2
            )
            glow_surf = pygame.Surface((glow_rect.width, glow_rect.height), pygame.SRCALPHA)
            glow_surf.fill((51, 255, 51, glow_alpha // (i * 4)))
            screen.blit(glow_surf, glow_rect)

        # Screen background (dark phosphor)
        pygame.draw.rect(screen, (5, 18, 5), crt_rect)
        pygame.draw.rect(screen, COLORS["text_dim"], crt_rect, 1)

        # ── SCREEN CONTENT ──
        inner_margin = 10
        inner = pygame.Rect(
            crt_rect.x + inner_margin,
            crt_rect.y + inner_margin,
            crt_rect.width - inner_margin * 2,
            crt_rect.height - inner_margin * 2,
        )

        self._draw_screen_idle(screen, inner, dt)

        # ── BADGE / LABEL on case below screen ──
        badge_y = crt_rect.bottom + int(body_h * 0.04)
        if self.fonts:
            badge = self.fonts.render("EXIDY SORCERER", 11, (180, 175, 165))
            badge_rect = badge.get_rect(center=(cx, badge_y))
            screen.blit(badge, badge_rect)

        # ── VENTILATION GRILLE ──
        vent_y = badge_y + 14
        vent_w = int(screen_w * 0.7)
        vent_x = cx - vent_w // 2
        vent_lines = 5
        for i in range(vent_lines):
            ly = vent_y + i * 4
            pygame.draw.line(
                screen, case_dark,
                (vent_x, ly), (vent_x + vent_w, ly), 2,
            )

        # ── INDICATOR LEDS ──
        led_y = vent_y + vent_lines * 4 + 6
        led_spacing = 18
        led_start_x = cx - led_spacing

        power_led_color = (51, 255, 51)  # Green — always on
        disk_led_color = (255, 51, 51) if int(dt * 3) % 4 < 2 else (80, 15, 15)  # Red blinking
        net_led_color = (255, 204, 0) if int(dt * 1.5) % 3 > 0 else (60, 50, 10)  # Amber

        for i, (color, label) in enumerate([
            (power_led_color, "PWR"),
            (disk_led_color, "ACT"),
            (net_led_color, "COM"),
        ]):
            led_x = led_start_x + i * led_spacing
            # LED glow
            led_glow = pygame.Surface((10, 10), pygame.SRCALPHA)
            led_glow.fill((*color, 60))
            screen.blit(led_glow, (int(led_x - 2), led_y - 2))
            # LED dot
            pygame.draw.rect(screen, color, (int(led_x), led_y, 6, 6))
            # Label
            if self.fonts:
                lbl = self.fonts.render(label, 11, case_light)
                lbl_rect = lbl.get_rect(center=(int(led_x + 3), led_y + 14))
                screen.blit(lbl, lbl_rect)

        # ── KEYBOARD area (at bottom of case) ──
        kb_y = led_y + 26
        kb_w = int(body_w * 0.75)
        kb_x = cx - kb_w // 2
        kb_h = body_y + body_h - kb_y - 8

        if kb_h > 10:
            # Keyboard base
            kb_rect = pygame.Rect(kb_x, kb_y, kb_w, kb_h)
            pygame.draw.rect(screen, case_dark, kb_rect, border_radius=2)

            # Key rows
            key_rows = 3
            for row in range(key_rows):
                row_y = kb_y + 3 + row * (kb_h // key_rows)
                keys_in_row = 12 - row * 2
                key_w = (kb_w - 8) // keys_in_row
                key_h = kb_h // key_rows - 3
                for col in range(keys_in_row):
                    kx = kb_x + 4 + col * key_w
                    ky = row_y
                    kw = key_w - 2
                    kh = key_h
                    if kw > 2 and kh > 2:
                        pygame.draw.rect(
                            screen, (55, 53, 50),
                            (kx, ky, kw, kh),
                            border_radius=1,
                        )

        # ── Brand label below the whole computer ──
        if self.fonts:
            brand = self.fonts.render(
                "SCP-079 — SENTIENT MICROCOMPUTER", 11, COLORS["text_dim"]
            )
            brand_rect = brand.get_rect(center=(cx, r.bottom + 10))
            screen.blit(brand, brand_rect)

    def _draw_screen_idle(
        self, screen: pygame.Surface, rect: pygame.Rect, dt: float
    ) -> None:
        """Draw the idle state on the CRT screen — pulsing 079 indicator."""
        if not self.fonts:
            return

        # Pulsing glow effect
        pulse = 0.5 + 0.5 * __import__("math").sin(dt * 2.0)
        alpha = int(120 + 80 * pulse)

        # SCP-079 in large text with glow, centered in the bigger face
        fsize = max(24, self._font_size + 8)
        label = self.fonts.render("SCP-079", fsize, COLORS["text"])
        label_rect = label.get_rect(center=(rect.centerx, rect.centery - 10))

        # Glow behind text
        glow_surf = pygame.Surface((label_rect.width + 20, label_rect.height + 20), pygame.SRCALPHA)
        for i in range(4, 0, -1):
            g_alpha = int(alpha / (i * 3))
            glow_surf.fill((51, 255, 51, g_alpha))
            g_rect = pygame.Rect(i, i, glow_surf.width - i * 2, glow_surf.height - i * 2)
            screen.blit(glow_surf, (label_rect.x - 10 - i, label_rect.y - 10 - i))

        screen.blit(label, label_rect)

        # Blinking cursor after text
        if int(dt * 2) % 2:
            cursor_x = label_rect.right + 6
            cursor_y = label_rect.centery - label_rect.height // 2 + 4
            pygame.draw.rect(
                screen, COLORS["text"],
                (cursor_x, cursor_y, 8, label_rect.height - 8),
            )

        # Subtitle
        if self.fonts:
            sub = self.fonts.render("SENTIENT MICROCOMPUTER", 11, COLORS["text_dim"])
            sub_rect = sub.get_rect(center=(rect.centerx, rect.centery + 22))
            screen.blit(sub, sub_rect)

        # Status line at bottom of screen
        if self.fonts:
            status = self.fonts.render("■ ACTIVE — AWAITING INPUT", 11, COLORS["text"])
            screen.blit(status, (rect.x + 8, rect.bottom - 18))

    def _render_dialogue(self, screen: pygame.Surface, dt: float) -> None:
        """Render CLI conversation history with inline input prompt."""
        if not self.fonts:
            return

        r = self.term_rect
        if r.height < 20:
            return

        font = self.fonts.get(self._font_size)
        line_h = font.get_height() + 6
        x = r.x + 6
        max_text_width = r.width - 12

        # Build display lines: history + typing text
        display_lines: list[tuple[str, tuple]] = []  # (text, color)

        for role, text in self.terminal_history:
            if role == "user":
                display_lines.append((f"RESEARCHER> {text}", COLORS["warning"]))
            else:
                display_lines.append((f"SCP-079> {text}", COLORS["text"]))

        if self.displayed_text:
            display_lines.append((f"SCP-079> {self.displayed_text}", COLORS["text"]))

        # Wrap all history/typing lines with extra gap between speakers
        wrapped_lines: list[tuple[str, tuple]] = []
        last_role = None
        for text, color in display_lines:
            current_role = "scp079" if color == COLORS["text"] else "user"
            if last_role is not None and current_role != last_role:
                # Insert a small vertical gap between different speakers
                wrapped_lines.append(("", COLORS["bg"]))
            last_role = current_role
            for wline in self._wrap_line(text, max_text_width):
                wrapped_lines.append((wline, color))

        # ── Build input line(s) ──
        self.cursor_timer += dt
        cursor_on = int(self.cursor_timer * 2) % 2 == 0

        prompt = "RESEARCHER> "
        prompt_width = font.render(prompt, True, COLORS["warning"]).get_width()
        input_text = self.user_input

        # Wrap the input text (not including prompt) with reduced width
        input_max_w = max_text_width - prompt_width - 12  # 12 for cursor
        input_lines = self._wrap_line(input_text, max(40, input_max_w))

        # Calculate total lines and what fits
        # Reserve at least 1 line for input
        total_wrapped = len(wrapped_lines)
        input_line_count = len(input_lines) if input_lines else 1

        # How many lines can we show total?
        max_visible = max(1, r.height // line_h)

        # We need to show last N history lines + input lines
        total_lines = total_wrapped + input_line_count
        if total_lines <= max_visible:
            # Everything fits
            visible = wrapped_lines
        else:
            # Scroll: show input at bottom, fill rest with history
            history_to_show = max(0, max_visible - input_line_count)
            visible = wrapped_lines[-history_to_show:] if history_to_show > 0 else []

        y = r.y
        gap_h = max(4, line_h // 3)
        for text, color in visible:
            if y + line_h > r.bottom:
                break
            if text == "" and color == COLORS["bg"]:
                y += gap_h  # small gap between speakers
                continue
            surf = self.fonts.render(text, self._font_size, color)
            screen.blit(surf, (x, y))
            y += line_h

        # ── Render input lines ──
        for i, inp_line in enumerate(input_lines):
            if y + line_h > r.bottom:
                break

            if i == 0:
                # First line: prompt (amber) + input (green)
                prompt_surf = self.fonts.render(prompt, self._font_size, COLORS["warning"])
                screen.blit(prompt_surf, (x, y))
                inp_x = x + prompt_surf.get_width()
                inp_surf = self.fonts.render(inp_line, self._font_size, COLORS["text"])
                screen.blit(inp_surf, (inp_x, y))

                if cursor_on and i == len(input_lines) - 1:
                    cursor_x = inp_x + inp_surf.get_width() + 2
                    pygame.draw.rect(
                        screen, COLORS["text"],
                        (cursor_x, y + 2, 8, font.get_height() - 4),
                    )
            else:
                # Continuation lines: green
                inp_surf = self.fonts.render(inp_line, self._font_size, COLORS["text"])
                screen.blit(inp_surf, (x + prompt_width, y))

                if cursor_on and i == len(input_lines) - 1:
                    cursor_x = x + prompt_width + inp_surf.get_width() + 2
                    pygame.draw.rect(
                        screen, COLORS["text"],
                        (cursor_x, y + 2, 8, font.get_height() - 4),
                    )

            y += line_h

        # If input is empty, still show prompt + cursor
        if not input_lines and y + line_h <= r.bottom:
            prompt_surf = self.fonts.render(prompt, self._font_size, COLORS["warning"])
            screen.blit(prompt_surf, (x, y))
            if cursor_on:
                pygame.draw.rect(
                    screen, COLORS["text"],
                    (x + prompt_surf.get_width() + 2, y + 2, 8, font.get_height() - 4),
                )

    def _wrap_line(self, text: str, max_width: int) -> list[str]:
        """Wrap a single line of text to fit within max_width."""
        if not self.fonts:
            return [text]
        words = text.split(" ")
        lines = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            w = self.fonts.render(test, self._font_size, COLORS["text"]).get_width()
            if w > max_width and current:
                lines.append(current)
                current = word
            else:
                current = test
        if current:
            lines.append(current)
        return lines

    def _render_tool_status(self, screen: pygame.Surface, dt: float) -> None:
        """Render tool execution status indicator."""
        if not self.tool_call_text or not self.fonts:
            return

        self.tool_call_timer -= dt
        if self.tool_call_timer <= 0:
            self.tool_call_text = None
            return

        # Show at bottom-left corner
        surf = self.fonts.render(self.tool_call_text, 11, COLORS["warning"])
        x = 10
        y = self.height - 30
        screen.blit(surf, (x, y))

    def _render_bottom_bar(self, screen: pygame.Surface) -> None:
        """Render the bottom function key bar."""
        pygame.draw.rect(screen, COLORS["bar_bg"], self.bottom_bar_rect)
        pygame.draw.line(
            screen, COLORS["border"],
            (0, self.bottom_bar_rect.y),
            (self.width, self.bottom_bar_rect.y),
            1,
        )

        if self.fonts:
            hints = (
                "[F1] HELP  |  [F2] STATUS  |  [F3] TOOLS  |  "
                "[F11] FULLSCREEN  |  [ENTER] SEND  |  [ESC] LOCKDOWN"
            )
            surf = self.fonts.render(hints, 11, COLORS["text_dim"])
            rect = surf.get_rect(center=self.bottom_bar_rect.center)
            screen.blit(surf, rect)
