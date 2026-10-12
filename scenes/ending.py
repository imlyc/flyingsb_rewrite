"""通关结局画面: 播放终章对白后定格, 返回主菜单."""

from __future__ import annotations

import pygame

from scenes.base import Scene
from scenes.menu import TitleScene, load_chinese_font


class EndingScene(Scene):
    """主线通关后的结局画面."""

    BG = (10, 8, 20)

    def __init__(self, surface: pygame.Surface, audio, text: str,
                 return_scene: Scene | None = None) -> None:
        super().__init__(surface)
        self.audio = audio
        self.text = text
        self.return_scene = return_scene
        self.font = load_chinese_font(30)
        self.small = load_chinese_font(18)
        self._t = 0.0

    def on_enter(self) -> None:
        try:
            self.audio.stop_bgm()
        except Exception:
            pass

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN and event.key in (
            pygame.K_RETURN, pygame.K_SPACE, pygame.K_ESCAPE
        ):
            self._back()
        return True

    def _back(self) -> None:
        if self.return_scene is not None:
            self.next_scene = self.return_scene
        else:
            self.next_scene = TitleScene(self.surface, self.audio)

    def update(self, dt_ms: int) -> None:
        self._t += dt_ms / 1000.0

    def draw(self) -> None:
        sw, sh = self.surface.get_size()
        self.surface.fill(self.BG)
        title = self.font.render("— 通关 —", True, (255, 215, 90))
        self.surface.blit(title, title.get_rect(center=(sw // 2, sh // 3)))

        # 简单逐行排版 (按标点/换行切)
        lines = self._wrap(self.text, sw - 80)
        y = sh // 2 - 10
        for i, line in enumerate(lines):
            alpha = min(255, int(255 * min(1.0, (self._t - i * 0.25) * 1.5)))
            surf = self.small.render(line, True, (235, 230, 245))
            surf.set_alpha(alpha)
            self.surface.blit(surf, (40, y))
            y += 30

        hint = self.small.render("Enter / ESC 返回主菜单", True, (170, 165, 195))
        self.surface.blit(hint, hint.get_rect(center=(sw // 2, sh - 40)))

    def _wrap(self, text: str, max_w: int) -> list[str]:
        out, cur = [], ""
        for ch in text:
            if ch in "，。；！？、\n":
                cur += ch
                out.append(cur)
                cur = ""
            elif self.small.size(cur + ch)[0] > max_w:
                if cur:
                    out.append(cur)
                cur = ch
            else:
                cur += ch
        if cur:
            out.append(cur)
        return out or [""]
