"""幻想西游记 重制版 入口."""

from __future__ import annotations

import sys

import pygame

from core.audio_manager import AudioManager
from scenes.base import Scene
from scenes.menu import TitleScene

WINDOW_SIZE = (640, 480)          # 原版逻辑分辨率; 显示时整数倍放大 (pygame.SCALED)
FPS = 60


def switch_scene(scene: Scene) -> Scene:
    """切到 scene.next_scene 并返回新场景.

    只清**旧**场景的 next_scene (不清会导致回跳/闪屏)。
    ⚠ **不能清新场景的**: 有些场景在构造 / on_enter 之前就挂好了待切场景 ——
      新游戏时 enter_location 自动弹序章、进店铺地图自动开店; 清掉序章就不会自动播。
    """
    nxt = scene.next_scene
    scene.next_scene = None
    scene.on_exit()
    nxt.on_enter()
    return nxt


def main() -> int:
    pygame.init()
    pygame.display.set_caption("幻想西游记")
    surface = pygame.display.set_mode(WINDOW_SIZE, pygame.SCALED)
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

        # 场景切换 (见 switch_scene 的说明: 不能清新场景预挂的 next_scene).
        # 连着切: 新场景若已预挂了下一个 (新游戏 → 世界地图 → 自动序章), 中间那个不画一帧 (否则小森林闪一下)
        while scene.next_scene is not None:
            scene = switch_scene(scene)

    audio.stop_bgm()
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
