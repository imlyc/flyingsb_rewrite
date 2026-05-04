"""幻想西游记 重制版 入口."""

from __future__ import annotations

import sys
from pathlib import Path

import pygame

from core.audio_manager import AudioManager
from core.save_manager import load_save, print_save
from scenes.menu import MenuAction, TitleScene

WINDOW_SIZE = (800, 600)
FPS = 60
DEFAULT_SAVE = Path(
    "/Users/imlyc/Work/flyingsb/origin/flyingsb/工具大全/存档/全剧情存档/0/Save1.dat"
)


def handle_action(action: MenuAction) -> bool:
    """返回 False 表示游戏退出."""
    if action == MenuAction.NEW_GAME:
        print("[TODO] 新游戏: 进入开场剧情")
    elif action == MenuAction.LOAD_SAVE:
        print(f"[读取存档] {DEFAULT_SAVE}")
        save = load_save(DEFAULT_SAVE)
        print_save(save)
    elif action == MenuAction.QUIT:
        return False
    return True


def main() -> int:
    pygame.init()
    pygame.display.set_caption("幻想西游记")
    surface = pygame.display.set_mode(WINDOW_SIZE)
    clock = pygame.time.Clock()

    audio = AudioManager()
    audio.set_volume(0.6)
    try:
        audio.play_bgm("INTRO_.WAV")
    except FileNotFoundError as e:
        print(f"BGM 缺失: {e}")

    scene = TitleScene(surface)

    running = True
    while running:
        for event in pygame.event.get():
            if not scene.handle_event(event):
                running = False
                break
        action = scene.consume_action()
        if action is not None:
            running = handle_action(action)

        scene.draw()
        pygame.display.flip()
        clock.tick(FPS)

    audio.stop_bgm()
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
