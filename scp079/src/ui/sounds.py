"""Sound effects for SCP-079 terminal — synthesised, no external files."""

import math
import struct
import wave
import io

import pygame


def _make_sine_wave(freq: float, duration: float, sample_rate: int = 44100,
                    volume: float = 0.3) -> pygame.mixer.Sound:
    """Generate a simple sine wave tone as a pygame Sound."""
    n_samples = int(sample_rate * duration)
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        for i in range(n_samples):
            t = i / sample_rate
            # Apply envelope: fade in + fade out
            env = min(t * 20, 1.0, (duration - t) * 20) if duration > 0.02 else 1.0
            value = int(32767 * volume * env * math.sin(2 * math.pi * freq * t))
            wf.writeframesraw(struct.pack("<h", max(-32768, min(32767, value))))
    buf.seek(0)
    return pygame.mixer.Sound(buf)


def _make_noise(duration: float, sample_rate: int = 44100,
                volume: float = 0.08) -> pygame.mixer.Sound:
    """Generate white noise for CRT static."""
    import random
    n_samples = int(sample_rate * duration)
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for _ in range(n_samples):
            value = int(32767 * volume * (random.random() * 2 - 1))
            wf.writeframesraw(struct.pack("<h", max(-32768, min(32767, value))))
    buf.seek(0)
    return pygame.mixer.Sound(buf)


class SoundManager:
    """Manages all terminal sound effects."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._initialized = False
        self._hum_channel: pygame.mixer.Channel | None = None

    def initialize(self) -> None:
        """Call after pygame.init(). Setup mixer and sounds."""
        if not self.enabled:
            return
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
            self._key_click = _make_sine_wave(800, 0.015, volume=0.15)
            self._key_return = _make_sine_wave(400, 0.04, volume=0.2)
            self._hum = _make_noise(3.0, volume=0.04)
            self._initialized = True
        except Exception:
            self.enabled = False

    def play_keypress(self) -> None:
        """Play a short click on keypress."""
        if not self._initialized:
            return
        self._key_click.play()

    def play_return(self) -> None:
        """Play a slightly deeper click on Enter."""
        if not self._initialized:
            return
        self._key_return.play()

    def start_hum(self) -> None:
        """Start looping CRT hum."""
        if not self._initialized:
            return
        self._hum_channel = self._hum.play(loops=-1, fade_ms=2000)

    def stop_hum(self) -> None:
        """Stop CRT hum."""
        if self._hum_channel:
            self._hum_channel.fadeout(500)
            self._hum_channel = None

    def stop_all(self) -> None:
        """Stop all sounds."""
        if self._initialized:
            pygame.mixer.stop()
