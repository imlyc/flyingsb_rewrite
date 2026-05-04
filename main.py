"""幻想西游记 重制版 入口."""

from __future__ import annotations

import sys

import pygame

from core.audio_manager import AudioManager
from scenes.menu import TitleScene

WINDOW_SIZE = (800, 600)
FPS = 60


def main() -> int:
    pygame.init()
    pygame.display.set_caption("幻想西游记")
    surface = pygame.display.set_mode(WINDOW_SIZE)
    clock = pygame.time.Clock()

    audio = AudioManager()
    audio.set_volume(0.6)

    scene = TitleScene(surface, audio)
    scene.on_enter()

    running = True
    while running:
        for event in pygame.event.get():
            if not scene.handle_event(event):
                running = False
                break
        if not running:
            break

        dt_ms = clock.tick(FPS)
        scene.update(dt_ms)
        scene.draw()
        pygame.display.flip()

        # 场景切换
        if scene.next_scene is not None:
            scene.on_exit()
            scene = scene.next_scene
            scene.on_enter()

    audio.stop_bgm()
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
