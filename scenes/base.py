"""场景基类 + 场景切换约定."""

from __future__ import annotations

import pygame


class Scene:
    """场景接口.

    主循环每帧:
      for event: scene.handle_event(event)  # 返回 False 整个程序退出
      scene.update(dt_ms)
      scene.draw()
      若 scene.next_scene 非 None, 则切换 current = next_scene
    """

    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface
        self.next_scene: "Scene | None" = None

    def on_enter(self) -> None: ...
    def on_exit(self) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> bool:
        return True

    def update(self, dt_ms: int) -> None: ...
    def draw(self) -> None: ...
