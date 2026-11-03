"""战斗菜单 — 原版菜单系统 (FUN_0041d429) 在战斗里: 十字菜单 (窗口 0xf) → 道具列表 (窗口 4 mode 0xf) / 特殊能力 (窗口 5 mode 0xf) + 说明栏 13.

exe 流程 (FUN_004a4f94 行动态, 0x7e2ddc = 1 期间不画移动范围):
  移动态 Esc: 开菜单系统 + 窗口 0xf (scenes.team_info.CrossWin): 光标从画面框缩到单位头顶, 4 图标转出.
  十字 ← / ↑: 光标移到该图标框, 图标转入 → 开道具列表 / 特殊能力; 这两个窗口 Esc 收起后重开窗口 0xf.
  道具列表: FUN_00423e2d(4) = 背包里 分类 0 且 道具表 +8 & 8 的道具, 标题「戰鬥用道具」, 光标 0x7b8f20 全局记忆.
  特殊能力: 同场外窗口, 战斗单位实时 MP / SG 决定亮灭, 光标按角色记忆 (0x7b82bc, 与场外共用).
  选中 (道具 / 技能): 播 0x142 收起, 光标扩回画面框; 全部窗口关掉后 FUN_0041d698 交结果:
    1 取消 → 回移动态 / 4 技能 → 技能瞄准 / 5 道具 → 道具瞄准 (模板按道具, core.item_use.item_template) / 6 结束回合.
窗口/光标/键全部复用 scenes.team_info (同一套 menu.cpp 逆向); 1 tick = 战斗 tick.
"""
from __future__ import annotations

import pygame

from core.attack_seq import ATTACK_TICK_MS
from core.character import CHARACTER_NAMES
from scenes.team_info import W_CROSS, Member, WindowHost

_RECORD = {v: k for k, v in CHARACTER_NAMES.items()}
RESULT_CANCEL, RESULT_SKILL, RESULT_ITEM, RESULT_END = 1, 4, 5, 6      # FUN_0041d698 低 16 位


def cross_center(scene, unit) -> tuple[int, int]:
    """窗口 0xf 中心 (画面坐标): 单位实体 (格中心, 高度 0) 上移 0x20."""
    from core.sprites.base import TILE_H, TILE_W
    cam_x, cam_y = int(scene._cam_x), int(scene._cam_y)
    return unit.x * TILE_W - cam_x + TILE_W // 2, unit.y * TILE_H - cam_y + TILE_H // 2 - 0x20


class BattleMenu(WindowHost):
    """战斗菜单系统. done 后 result = (RESULT_*, 技能 / 道具 id 或 None)."""

    def __init__(self, audio, inv, unit, center: tuple[int, int]) -> None:
        super().__init__(audio, inv)
        self.tick_ms = ATTACK_TICK_MS
        self.battle_unit = unit
        self.member = Member(unit.name, None, _RECORD.get(unit.name, -1))
        self.cross_center = center
        self.result: tuple[int, int | None] | None = None
        self.open(W_CROSS)

    def cross_result(self, code: int) -> None:
        """窗口 0xf 收起完毕: 1 取消 / 6 结束回合."""
        self.result = (code, None)

    def skill_chosen(self, skill: int) -> None:
        self.result = (RESULT_SKILL, skill)

    def item_chosen(self, item: int | None) -> None:
        """道具列表收起完毕 (state 0x6e): Esc 重开窗口 0xf; 选中则光标扩回画面框 (exe SetRect 画面框)."""
        if item is None:
            self.open(W_CROSS)
            return
        self.result = (RESULT_ITEM, item)
        l, t, r, b = self.view
        self.cursor.move_to(l + 1, t + 1, r - 1, b - 1)

    @property
    def done(self) -> bool:
        """菜单系统等全部窗口关掉才返回结果 (FUN_0041d698)."""
        return self.result is not None and not self.order

    def draw(self, surface: pygame.Surface) -> None:
        self.draw_windows(surface)
