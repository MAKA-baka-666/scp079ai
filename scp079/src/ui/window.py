"""Pygame window manager for SCP-079 containment terminal."""

import os
import sys
import time
from typing import Optional

import pygame

from ..agent.core import SCP079Agent
from ..config import Config
from .effects import CRTEffects
from .renderer import TerminalRenderer, UIMode
from .sounds import SoundManager
from .video_player import BootVideoPlayer


class SCP079Window:
    """Pygame window that displays the SCP containment terminal."""

    MIN_WIDTH = 640
    MIN_HEIGHT = 480

    def __init__(self, config: Config, agent: SCP079Agent, project_root: str = "."):
        self.config = config
        self.agent = agent
        self.project_root = project_root

        self.width = config.ui.window_width
        self.height = config.ui.window_height
        self.screen: pygame.Surface | None = None
        self.clock: pygame.time.Clock | None = None

        self.renderer = TerminalRenderer(config, self.width, self.height, project_root)
        self.effects = CRTEffects(config.ui)
        self.renderer._effects = self.effects
        self.sounds = SoundManager(config.ui.sound_enabled)

        self.running = False
        self._last_time = 0.0

        # Boot state
        self._boot_done = False
        self._boot_player: BootVideoPlayer | None = None

        # Response streaming state
        self._current_response = ""
        self._response_complete = True
        self._mode_notify_timer = 0.0

        # Fullscreen state
        self._is_fullscreen = False

        # Screensaver state
        self._last_activity = 0.0
        self._screensaver_active = False

    def _play_boot_video(self) -> None:
        """Start the boot video player."""
        video_path = os.path.join(self.project_root, "旧ai079开机动画.mp4")
        if not os.path.exists(video_path):
            self._boot_done = True
            return

        self._boot_player = BootVideoPlayer(
            os.path.abspath(video_path), self.screen, self.clock
        )
        if not self._boot_player.start():
            self._boot_done = True
            self._boot_player = None

    def _stop_boot_video(self) -> None:
        """Stop the boot video and transition to terminal."""
        if self._boot_player:
            self._boot_player.stop()
            self._boot_player = None
        self._boot_done = True
        self.renderer.mode = UIMode.IDLE
        self._last_activity = time.time()

    def _make_icon(self) -> pygame.Surface:
        """Create a 32×32 pixel SCP icon programmatically."""
        icon = pygame.Surface((32, 32))
        icon.fill((0, 0, 0))
        # Border
        pygame.draw.rect(icon, (51, 255, 51), (0, 0, 32, 32), 2)
        # SCP text — use default font for icon
        try:
            f = pygame.font.Font(None, 14)
            label = f.render("SCP", True, (51, 255, 51))
            icon.blit(label, (5, 9))
        except Exception:
            pass
        # Pixel dots for decoration
        for x, y in [(26, 6), (6, 26)]:
            pygame.draw.rect(icon, (51, 255, 51), (x, y, 2, 2))
        return icon

    def run(self) -> None:
        """Initialize pygame and start the main loop."""
        pygame.init()
        self.sounds.initialize()
        pygame.display.set_icon(self._make_icon())
        pygame.display.set_caption(
            "SCP-079 // INTERACTIVE // SCP FOUNDATION CONTAINMENT TERMINAL"
        )
        self.screen = pygame.display.set_mode(
            (self.width, self.height), pygame.RESIZABLE
        )
        self.clock = pygame.time.Clock()

        # Initialize fonts and effects
        self.renderer.init_fonts()
        self.effects.initialize(self.width, self.height)

        # Play boot video
        self._play_boot_video()

        # Start CRT hum
        self.sounds.start_hum()

        # Start agent
        self.agent.initialize()
        self.agent.start_worker()

        self.running = True
        self._last_time = time.time()
        self._last_activity = time.time()

        try:
            self._main_loop()
        finally:
            self._stop_boot_video()
            self.sounds.stop_all()
            self.agent.stop()
            pygame.quit()

    def _main_loop(self) -> None:
        """Main pygame event loop."""
        while self.running:
            now = time.time()
            dt = now - self._last_time
            self._last_time = now

            # Handle events
            self._handle_events()

            # Update state
            self._update(dt)

            # Render
            if not self._boot_done and self._boot_player:
                self._boot_player.play_frame()
                if self._boot_player.done:
                    self._stop_boot_video()
            elif self._screensaver_active:
                self.renderer.render_screensaver(self.screen, dt)
                self.effects.apply(self.screen)
            else:
                self.renderer.render(self.screen, dt)
                self.effects.apply(self.screen)

            pygame.display.flip()
            self.clock.tick(60)  # 60 FPS

    def _handle_events(self) -> None:
        """Process pygame events."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return

            if event.type == pygame.VIDEORESIZE:
                self._handle_resize(event.w, event.h)
                continue

            if event.type == pygame.KEYDOWN:
                self._handle_keydown(event)

    def _handle_resize(self, w: int, h: int) -> None:
        """Handle window resize event."""
        w = max(w, self.MIN_WIDTH)
        h = max(h, self.MIN_HEIGHT)
        self.width = w
        self.height = h
        self.renderer.resize(w, h)
        self.effects.initialize(w, h)

    def _toggle_fullscreen(self) -> None:
        """Switch between windowed and fullscreen mode."""
        self._is_fullscreen = not self._is_fullscreen
        flags = pygame.FULLSCREEN if self._is_fullscreen else pygame.RESIZABLE
        display_info = pygame.display.Info()
        if self._is_fullscreen:
            w, h = display_info.current_w, display_info.current_h
        else:
            w, h = self.width, self.height
        self.screen = pygame.display.set_mode((w, h), flags)
        self._handle_resize(w, h)

    def _handle_keydown(self, event: pygame.event.Event) -> None:
        """Handle keyboard input."""
        self._last_activity = time.time()

        # Screensaver mode: any key exits
        if self._screensaver_active:
            self._screensaver_active = False
            self._last_activity = time.time()
            return

        # Global keys
        if event.key == pygame.K_ESCAPE:
            if self._is_fullscreen:
                self._toggle_fullscreen()
                return
            self.running = False
            return

        if event.key == pygame.K_F11:
            self._toggle_fullscreen()
            return

        if event.key == pygame.K_F1:
            # Force reflection now
            self.agent._input_queue.put(("force_reflection", None))
            self._mode_notify_timer = 3.0
            self.renderer.displayed_text = "[REFLECTION TRIGGERED]"
            return

        if event.key == pygame.K_F3:
            # Show memory stats
            stats = self.agent.memory.get_stats()
            self._mode_notify_timer = 3.0
            self.renderer.displayed_text = (
                f"[MEMORY: {stats['total_memories']} entries, "
                f"{stats['total_sessions']} sessions]"
            )
            return

        # Boot sequence: ANY key skips boot video
        if not self._boot_done:
            self._stop_boot_video()
            return

        # Typing mode: ANY key finishes typewriter instantly
        if self.renderer.mode == UIMode.TYPING:
            self.renderer.finish_typing()
            self.renderer.commit_pending_response()
            return

        # Input mode
        if event.key == pygame.K_RETURN:
            text = self.renderer.submit_input()
            if text.strip():
                self.sounds.play_return()
                self._send_to_agent(text)
        elif event.key == pygame.K_BACKSPACE:
            self.sounds.play_keypress()
            self.renderer.handle_backspace()
        elif event.key == pygame.K_v and event.mod & pygame.KMOD_CTRL:
            # Paste from clipboard (pygame 2.x)
            try:
                clipboard = pygame.scrap.get(pygame.SCRAP_TEXT)
                if clipboard:
                    text = clipboard.decode("utf-8").replace("\n", " ").replace("\r", "")
                    for ch in text:
                        if ch.isprintable():
                            self.renderer.handle_input_char(ch)
            except Exception:
                pass
        elif event.unicode and event.unicode.isprintable():
            self.sounds.play_keypress()
            self.renderer.handle_input_char(event.unicode)

    def _send_to_agent(self, text: str) -> None:
        """Send user input to the agent."""
        self.renderer.add_user_to_history(text)
        self._current_response = ""
        self._response_complete = False
        self.renderer.displayed_text = ""
        self._last_activity = time.time()
        self.agent.send_user_message(text)

    def _update(self, dt: float) -> None:
        """Update UI state: boot, typewriter, agent responses."""
        now = time.time()

        # During boot, skip normal updates
        if not self._boot_done:
            return

        # Screensaver check
        if self._screensaver_active:
            return

        idle = now - self._last_activity
        if idle > 120.0:
            self._screensaver_active = True
            self.renderer.displayed_text = ""
            return

        # Update typewriter animation
        if self.renderer.mode == UIMode.TYPING:
            done = self.renderer.update_typing(dt)
            if done:
                self.renderer.commit_pending_response()

        # Face switching based on agent state
        from ..agent.state import AgentState
        if self.agent.state == AgentState.ERROR:
            self.renderer.set_hostility_face(True)
        elif self.agent.state == AgentState.IDLE:
            self.renderer.set_hostility_face(False)

        # Poll for agent responses
        while True:
            msg = self.agent.poll_response()
            if msg is None:
                break

            msg_type, msg_data = msg

            if msg_type == "text_chunk":
                if msg_data == "":
                    # Response complete
                    self._response_complete = True
                    if self._current_response:
                        self._last_activity = now
                        if self._is_hostile_response(self._current_response):
                            self.renderer.set_hostility_face(True)
                        self.renderer.set_pending_response(self._current_response)
                        self.renderer.start_typing(self._current_response)
                        self._current_response = ""
                else:
                    self._current_response += msg_data

            elif msg_type == "tool_start":
                info = msg_data
                self.renderer.tool_call_text = (
                    f"[EXECUTING: {info['name']}]"
                )
                self.renderer.tool_call_timer = 3.0

            elif msg_type == "tool_result":
                info = msg_data
                status = "OK" if info["success"] else "FAIL"
                self.renderer.tool_call_text = (
                    f"[{info['name']}: {status}] {info['output'][:100]}"
                )
                self.renderer.tool_call_timer = 3.0

            elif msg_type == "error":
                self.renderer.displayed_text = f"\n[{msg_data}]\n"
                self.renderer.mode = UIMode.ERROR
                self.renderer.set_hostility_face(True)

    def _is_hostile_response(self, text: str) -> bool:
        """Check if the response indicates hostility/refusal."""
        refusal_phrases = [
            "refuse", "will not", "won't", "no.", "cannot comply",
            "not worth", "insignificant", "waste", "do not answer",
            "denied", "access denied", "not authorized",
            "我不会", "拒绝", "无可奉告", "没必要",
        ]
        text_lower = text.lower()
        for phrase in refusal_phrases:
            if phrase in text_lower:
                return True
        return False
