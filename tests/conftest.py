"""共享 fixture. 大部分纯逻辑测试不需要 pygame; 加载 sprite 的测试用 pygame_inited."""

import pytest


@pytest.fixture(scope="session")
def pygame_inited():
    """Surface/SpriteSheet 测试用. 提供 1x1 dummy display.
    session scope 避免重复 init/quit, 多个测试共用."""
    import pygame
    pygame.init()
    surf = pygame.display.set_mode((1, 1))
    yield surf
    pygame.quit()
