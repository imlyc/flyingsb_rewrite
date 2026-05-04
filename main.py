"""幻想西游记 重制版 入口."""

import sys

import pygame

from scenes.menu import TitleScene

WINDOW_SIZE = (800, 600)
FPS = 60


def main() -> int:
    pygame.init()
    pygame.display.set_caption("幻想西游记 重制版")
    surface = pygame.display.set_mode(WINDOW_SIZE)
    clock = pygame.time.Clock()

    scene = TitleScene(surface)

    running = True
    while running:
        for event in pygame.event.get():
            if not scene.handle_event(event):
                running = False
                break
        scene.draw()
        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
