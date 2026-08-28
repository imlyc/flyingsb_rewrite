"""主菜单场景."""

from __future__ import annotations

import os
from pathlib import Path

import pygame

from core.audio_manager import AudioManager
from core.save_manager import load_save
from scenes.base import Scene

CHINESE_FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]

# 原版存档: 默认 repo 上一级 origin/ 里的全剧情存档, 可用 FLYINGSB_SAVE 环境变量覆盖
DEFAULT_SAVE = Path(os.environ.get(
    "FLYINGSB_SAVE",
    Path(__file__).resolve().parents[2] / "origin" / "flyingsb"
    / "工具大全" / "存档" / "全剧情存档" / "0" / "Save1.dat",
))


def load_chinese_font(size: int) -> pygame.font.Font:
    for p in CHINESE_FONT_CANDIDATES:
        try:
            return pygame.font.Font(p, size)
        except (FileNotFoundError, OSError):
            continue
    return pygame.font.SysFont(None, size)


class TitleScene(Scene):
    """标题画面: 标题 + 3 个菜单项, 上下选择, 回车确认."""

    BG_COLOR = (20, 20, 40)
    TITLE_COLOR = (255, 215, 90)
    ITEM_COLOR = (220, 220, 220)
    ITEM_HIGHLIGHT = (255, 255, 255)
    ITEM_HIGHLIGHT_BG = (80, 60, 30)

    def __init__(self, surface: pygame.Surface, audio: AudioManager):
        super().__init__(surface)
        self.audio = audio
        self.title_font = load_chinese_font(64)
        self.item_font = load_chinese_font(36)
        self.items: list[tuple[str, callable]] = [
            ("竞技场", self._action_arena),
            ("新游戏", self._action_new_game),
            ("读取存档", self._action_load_save),
            ("退出", self._action_quit),
        ]
        self.selected = 0
        self._quit_requested = False

    def on_enter(self) -> None:
        try:
            self.audio.play_bgm("INTRO_.WAV")
        except FileNotFoundError as e:
            print(f"BGM 缺失: {e}")

    # ------- 输入 -------
    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.QUIT:
            return False
        if event.type != pygame.KEYDOWN:
            return True
        if event.key == pygame.K_ESCAPE:
            return False
        if event.key in (pygame.K_UP, pygame.K_w):
            self.selected = (self.selected - 1) % len(self.items)
        elif event.key in (pygame.K_DOWN, pygame.K_s):
            self.selected = (self.selected + 1) % len(self.items)
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
            self.items[self.selected][1]()
            if self._quit_requested:
                return False
        return True

    # ------- 菜单动作 -------
    def _action_new_game(self) -> None:
        # 延迟 import 避免 menu <-> world_map 循环导入
        from scenes.world_map.scene import WorldMapScene
        self.next_scene = WorldMapScene(self.surface, self.audio, save=None)

    def _action_load_save(self) -> None:
        from scenes.world_map.scene import WorldMapScene
        try:
            save = load_save(DEFAULT_SAVE)
            print(f"[读取存档] {DEFAULT_SAVE}  地点={save.location}  金钱={save.money}")
        except Exception as e:
            print(f"读取存档失败: {e}")
            return
        self.next_scene = WorldMapScene(self.surface, self.audio, save=save)

    def _action_arena(self) -> None:
        from scenes.arena import ArenaSetupScene
        self.next_scene = ArenaSetupScene(self.surface, self.audio)

    def _action_quit(self) -> None:
        self._quit_requested = True

    # ------- 渲染 -------
    def draw(self) -> None:
        self.surface.fill(self.BG_COLOR)
        w, h = self.surface.get_size()

        title = self.title_font.render("幻想西游记", True, self.TITLE_COLOR)
        self.surface.blit(title, title.get_rect(center=(w // 2, h // 3)))

        start_y = h // 2 + 20
        spacing = 60
        for i, (label, _) in enumerate(self.items):
            highlight = (i == self.selected)
            color = self.ITEM_HIGHLIGHT if highlight else self.ITEM_COLOR
            text = self.item_font.render(label, True, color)
            rect = text.get_rect(center=(w // 2, start_y + i * spacing))
            if highlight:
                bg = rect.inflate(40, 12)
                pygame.draw.rect(self.surface, self.ITEM_HIGHLIGHT_BG, bg, border_radius=6)
            self.surface.blit(text, rect)
