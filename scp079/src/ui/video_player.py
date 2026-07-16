"""Boot video player using OpenCV to decode MP4 into pygame frames."""

import time

import cv2
import numpy as np
import pygame


class BootVideoPlayer:
    """Plays an MP4 video frame-by-frame inside a pygame window."""

    def __init__(self, video_path: str, screen: pygame.Surface, clock: pygame.time.Clock):
        self._path = video_path
        self._screen = screen
        self._clock = clock
        self._cap: cv2.VideoCapture | None = None
        self._fps: float = 30.0
        self._sw: int = 0
        self._sh: int = 0
        self._done = False

    @property
    def done(self) -> bool:
        return self._done

    def start(self) -> bool:
        """Open video and prepare. Returns False if video can't be opened."""
        self._cap = cv2.VideoCapture(self._path)
        if not self._cap.isOpened():
            self._done = True
            return False

        self._fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
        self._sw = self._screen.get_width()
        self._sh = self._screen.get_height()
        return True

    def play_frame(self) -> None:
        """Read and render one frame. Call once per main-loop tick."""
        if self._done or not self._cap:
            return

        ret, frame = self._cap.read()
        if not ret:
            self.stop()
            return

        # BGR → RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        # Rotate for pygame surface array (shape: H,W,C → W,H,C)
        frame_t = np.transpose(frame_rgb, (1, 0, 2))
        surf = pygame.surfarray.make_surface(frame_t)
        # Scale to fit window
        scaled = pygame.transform.smoothscale(surf, (self._sw, self._sh))
        self._screen.blit(scaled, (0, 0))

        # Pace to video FPS
        self._clock.tick(self._fps)

    def stop(self) -> None:
        """Release resources."""
        self._done = True
        if self._cap:
            self._cap.release()
            self._cap = None
