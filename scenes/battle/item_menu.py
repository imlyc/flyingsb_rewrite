"""战斗用道具菜单 — 原版菜单系统 (FUN_0041d429) 在战斗里: 十字菜单 (窗口 0xf) ← → 道具列表窗口 4 mode 0xf + 说明栏 13.

exe 流程 (FUN_00434eff / FUN_0042534d / FUN_004a4f94):
  十字菜单 ← : 光标移到道具图标框 (x-0x32, y-0x12, x-0xe, y+0x12), 播 0x142, 图标转入收起 → 开窗口 4 (mode 0xf).
  列表: FUN_00423e2d(4) = 背包里 分类 0 且 道具表 +8 & 8 的道具 (全部可选), 标题「戰鬥用道具」(0x54e564[9]);
        光标位置 0x7b8f20 全局记忆 (不分角色); 弹出完毕开说明栏, 光标从道具图标框移到所选行.
  Enter: 播 0x142 收起; 光标扩回全画面; 菜单系统返回 5 + 道具 id → 战斗按道具定瞄准模板 (core.item_use.item_template).
  Esc:   播 0x143 收起 → 重开十字菜单.
窗口/光标/键全部复用 scenes.team_info (同一套 menu.cpp 逆向); 1 tick = 战斗 tick.
"""
from __future__ import annotations

import pygame

from core.attack_seq import ATTACK_TICK_MS
from scenes.team_info import MODE_BATTLE, SCREEN_H, SCREEN_W, W_LIST, WindowHost


def item_icon_box(ucx: int, ucy: int) -> tuple[int, int, int, int]:
    """十字菜单道具图标的光标框 (FUN_00434eff ← 键)."""
    return ucx - 0x32, ucy - 0x12, ucx - 0xE, ucy + 0x12


class BattleItemMenu(WindowHost):
    """战斗里的道具列表. done 后 result = 选中的道具 id (None = 取消)."""

    def __init__(self, audio, inv, start_box: tuple[int, int, int, int]) -> None:
        super().__init__(audio, inv)
        self.tick_ms = ATTACK_TICK_MS
        l, t, r, b = start_box
        self.cursor.cur = [l << 16, t << 16, r << 16, b << 16]
        self.cursor.dst = list(self.cursor.cur)
        self.chosen = False
        self.result: int | None = None
        self.mode = MODE_BATTLE
        self.open(W_LIST, mode=MODE_BATTLE)

    def item_chosen(self, item: int | None) -> None:
        """ListWin 收起完毕 (state 0x6e): 选中则光标扩回全画面 (exe SetRect 画面框)."""
        self.chosen = True
        self.result = item
        if item is not None:
            self.cursor.move_to(1, 1, SCREEN_W - 1, SCREEN_H - 1)

    @property
    def done(self) -> bool:
        """菜单系统等全部窗口关掉才返回结果 (FUN_0041d698)."""
        return self.chosen and not self.order

    def draw(self, surface: pygame.Surface) -> None:
        self.draw_windows(surface)
