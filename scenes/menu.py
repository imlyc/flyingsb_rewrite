"""主菜单场景."""

from __future__ import annotations

from enum import Enum, auto

import pygame

CHINESE_FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]


def load_chinese_font(size: int) -> pygame.font.Font:
    for p in CHINESE_FONT_CANDIDATES:
        try:
            return pygame.font.Font(p, size)
        except (FileNotFoundError, OSError):
            continue
    return pygame.font.SysFont(None, size)


class MenuAction(Enum):
    NEW_GAME = auto()
    LOAD_SAVE = auto()
    QUIT = auto()


MENU_ITEMS: list[tuple[str, MenuAction]] = [
    ("新游戏", MenuAction.NEW_GAME),
    ("读取存档", MenuAction.LOAD_SAVE),
    ("退出", MenuAction.QUIT),
]


class TitleScene:
    """标题画面: 标题 + 三个菜单项, 上下选择, 回车确认."""

    BG_COLOR = (20, 20, 40)
    TITLE_COLOR = (255, 215, 90)
    ITEM_COLOR = (220, 220, 220)
    ITEM_HIGHLIGHT = (255, 255, 255)
    ITEM_HIGHLIGHT_BG = (80, 60, 30)

    def __init__(self, surface: pygame.Surface):
        self.surface = surface
        self.title_font = load_chinese_font(64)
        self.item_font = load_chinese_font(36)
        self.selected = 0
        self.action: MenuAction | None = None  # 由 main loop 消费

    # ------- 输入 -------
    def handle_event(self, event: pygame.event.Event) -> bool:
        """返回 False 表示请求退出窗口."""
        if event.type == pygame.QUIT:
            return False
        if event.type != pygame.KEYDOWN:
            return True
        if event.key == pygame.K_ESCAPE:
            return False
        if event.key in (pygame.K_UP, pygame.K_w):
            self.selected = (self.selected - 1) % len(MENU_ITEMS)
        elif event.key in (pygame.K_DOWN, pygame.K_s):
            self.selected = (self.selected + 1) % len(MENU_ITEMS)
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
            self.action = MENU_ITEMS[self.selected][1]
        return True

    def consume_action(self) -> MenuAction | None:
        a, self.action = self.action, None
        return a

    # ------- 渲染 -------
    def draw(self) -> None:
        self.surface.fill(self.BG_COLOR)
        w, h = self.surface.get_size()

        title = self.title_font.render("幻想西游记", True, self.TITLE_COLOR)
        self.surface.blit(title, title.get_rect(center=(w // 2, h // 3)))

        start_y = h // 2 + 20
        spacing = 60
        for i, (label, _) in enumerate(MENU_ITEMS):
            highlight = (i == self.selected)
            color = self.ITEM_HIGHLIGHT if highlight else self.ITEM_COLOR
            text = self.item_font.render(label, True, color)
            rect = text.get_rect(center=(w // 2, start_y + i * spacing))
            if highlight:
                bg = rect.inflate(40, 12)
                pygame.draw.rect(self.surface, self.ITEM_HIGHLIGHT_BG, bg, border_radius=6)
            self.surface.blit(text, rect)
