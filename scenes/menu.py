"""主菜单 / 标题画面 (最小占位)."""

import pygame


class TitleScene:
    """800x600 标题画面, 显示游戏名, 按 ESC 退出."""

    def __init__(self, surface: pygame.Surface):
        self.surface = surface
        # macOS 上常见的中文字体路径
        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
        ]
        self.font = None
        for p in candidates:
            try:
                self.font = pygame.font.Font(p, 48)
                break
            except (FileNotFoundError, OSError):
                continue
        if self.font is None:
            self.font = pygame.font.SysFont(None, 48)

    def draw(self) -> None:
        self.surface.fill((0, 0, 0))
        text = self.font.render("幻想西游记 重制版", True, (255, 255, 255))
        rect = text.get_rect(center=self.surface.get_rect().center)
        self.surface.blit(text, rect)

    def handle_event(self, event: pygame.event.Event) -> bool:
        """返回 False 表示请求退出."""
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return False
        return True
