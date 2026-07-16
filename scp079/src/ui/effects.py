"""CRT display post-processing effects."""

import random

import pygame


class CRTEffects:
    """Manages CRT visual effects: scanlines, noise, flicker, glow."""

    def __init__(self, config):
        self.config = config
        self._noise_surface: pygame.Surface | None = None
        self._scanline_surface: pygame.Surface | None = None
        self._vignette_surface: pygame.Surface | None = None
        self._flicker_alpha = 0
        self._flicker_timer = 0
        self._width = 0
        self._height = 0

    def initialize(self, width: int, height: int) -> None:
        """Pre-render reusable scanline, vignette, and noise surfaces."""
        self._width = width
        self._height = height
        self._build_scanlines()
        self._build_vignette()
        self._noise_surface = pygame.Surface((width, height), pygame.SRCALPHA)

    def _build_vignette(self) -> None:
        """Build radial vignette overlay: transparent center, dark edges."""
        w, h = self._width, self._height
        intensity = getattr(self.config, "vignette_intensity", 0.35)
        if intensity <= 0:
            self._vignette_surface = None
            return

        self._vignette_surface = pygame.Surface((w, h), pygame.SRCALPHA)
        cx, cy = w / 2, h / 2
        # Max distance from center to a corner
        max_dist = ((cx) ** 2 + (cy) ** 2) ** 0.5

        # Draw concentric filled circles with increasing alpha
        steps = 80
        for i in range(steps):
            ratio = i / steps
            # Non-linear falloff: stronger at edges
            alpha = int(255 * intensity * (ratio ** 1.8))
            r = int(max_dist * (1.0 - ratio * 0.85))
            if r > 0:
                pygame.draw.ellipse(
                    self._vignette_surface,
                    (0, 0, 0, alpha),
                    (int(cx - r), int(cy - r), int(r * 2), int(r * 2)),
                )

    def _build_scanlines(self) -> None:
        """Build scanline overlay: 2px alternating intensity."""
        w, h = self._width, self._height
        self._scanline_surface = pygame.Surface((w, h), pygame.SRCALPHA)
        opacity_strong = int(self.config.scanline_opacity * 255)
        opacity_weak = int(self.config.scanline_opacity * 255 * 0.5)
        for y in range(0, h, 2):
            alpha = opacity_strong if (y // 2) % 2 == 0 else opacity_weak
            if alpha > 0:
                pygame.draw.line(
                    self._scanline_surface,
                    (0, 0, 0, alpha),
                    (0, y), (w, y),
                )

    def apply(self, screen: pygame.Surface) -> None:
        """Apply all CRT effects to the screen in-place."""
        w, h = screen.get_size()
        if w != self._width or h != self._height:
            self.initialize(w, h)

        if self._vignette_surface:
            screen.blit(self._vignette_surface, (0, 0))
        if self.config.scanlines:
            self._apply_scanlines(screen)
        if self.config.noise_amount > 0:
            self._apply_noise(screen)
        if self.config.glow_intensity > 0:
            self._apply_flicker(screen)

    def apply_phosphor_glow(self, surface: pygame.Surface) -> pygame.Surface:
        """Apply phosphor glow effect: downsample→upsample blur.
        Returns a new Surface with the glow. Does NOT modify the input."""
        if not getattr(self.config, "phosphor_glow", True):
            return surface
        w, h = surface.get_size()
        if w < 10 or h < 10:
            return surface
        # Downscale
        small = pygame.transform.smoothscale(surface, (max(1, w // 3), max(1, h // 3)))
        # Upscale back
        blurred = pygame.transform.smoothscale(small, (w, h))
        # Blend: 30% blurred + original
        glow = pygame.Surface((w, h), pygame.SRCALPHA)
        glow.blit(blurred, (0, 0))
        glow.set_alpha(80)
        result = surface.copy()
        result.blit(glow, (0, 0))
        return result

    def _apply_scanlines(self, screen: pygame.Surface) -> None:
        screen.blit(self._scanline_surface, (0, 0))

    def _apply_noise(self, screen: pygame.Surface) -> None:
        """Apply random noise pixels for CRT grain effect."""
        # Flicker timer for noise refresh
        self._flicker_timer += 1
        if self._flicker_timer % 3 != 0:
            return  # Only refresh noise every 3 frames for performance

        width, height = screen.get_size()
        noise_count = int(width * height * self.config.noise_amount * 0.3)

        # Clear noise surface and draw random dots
        self._noise_surface.fill((0, 0, 0, 0))
        for _ in range(noise_count):
            x = random.randint(0, width - 1)
            y = random.randint(0, height - 1)
            alpha = random.randint(20, 80)
            self._noise_surface.set_at((x, y), (255, 255, 255, alpha))

        screen.blit(self._noise_surface, (0, 0))

    def _apply_flicker(self, screen: pygame.Surface) -> None:
        """Subtle brightness flicker to simulate CRT instability."""
        self._flicker_timer += 1
        if self._flicker_timer % 10 == 0:
            self._flicker_alpha = random.randint(0, int(self.config.glow_intensity * 40))

        if self._flicker_alpha > 0:
            flicker = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            flicker.fill((255, 255, 255, self._flicker_alpha))
            screen.blit(flicker, (0, 0))
            self._flicker_alpha = max(0, self._flicker_alpha - 1)
