"""敌人状态面板 — 战斗设定「敌军状态 看得到」(exe 0x7b88e0), 实体 FUN_004cf98d.

state 10: 战斗进行中 (0x868abc == 9 且 0x7e26a8 == 1, 同状态栏 FUN_004cf1ed) 且设定开 → 建 56×(32×30) 面;
state 100: 每行可见高度每 tick +2 到 32; state 0x6e: 条件不再成立 → 每 tick -2, 全 0 销毁回 state 10.
(0x6e 里按敌人 flags 单独收起的那个循环下标写错了 (0x86976c + 槽号×4, 越界), 原版无效果, 不搬.)

FUN_004cf590 每敌一格 56×32: 字体类型 10 = 状态栏同一字体 (LOGFONT #10 新細明體 16px w500, FIXED_PITCH),
新細明體是比例字: 真机 (YouTube 实况录像) 量得数字步进 8、空格 4, 字形垂直居中于 y (Wine 把新細明體换成思源黑体, 截图里的 7/3 不作数).
HP "%6d" 在 (0, 8), MP "%6d" 在 (0, 0x18) (y = 垂直中线). HP 颜色对: > 最大/2 → 3, > 最大/4 → 5, < 1 → 1, 否则 2;
MP 颜色对 4, HP < 1 → 1. 敌人表 flags & 0x20 (隐藏属性) 两行都画 "     ?" (颜色对 3 / 4).
FUN_004cf84b: 实体可见 (flags & 0x40, 死亡闪烁 off 帧不画) 且高度 > 0 → 取格子上部 h 行,
贴在 (实体 x - 16, 实体 y - z - 23 - h): 底边固定在脚下 23 像素处, 内容从底边往上长出来. 在精灵之上画.
数值沿用单位的显示 HP (display_hp, 受击结算时才变) 与 MP.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from scenes.battle.status_bar import PAIR_DEAD, PAIR_GOOD, PAIR_MP, draw_text, hp_pair

if TYPE_CHECKING:
    from scenes.battle.scene import BattleScene

CELL_W, CELL_H = 0x38, 0x20
GROW = 2
SPACE = 4                 # 新細明體空格步进 (数字 8)
_cache: dict = {}


def _put(surf: pygame.Surface, cy: int, text: str, pair) -> None:
    """右对齐串: 前导空格每个 4px, 其余按状态栏 draw_text (步进 8, 居中)."""
    body = text.lstrip(' ')
    draw_text(surf, SPACE * (len(text) - len(body)), cy, body, pair)


def cell(u) -> pygame.Surface:
    """FUN_004cf590 的一格 (透明底)."""
    if u.type_flags & 0x20:
        key = ('?',)
    else:
        hp = u.display_hp
        key = (hp, u.mp, hp_pair(hp, u.max_hp), PAIR_DEAD if hp < 1 else PAIR_MP)
    s = _cache.get(key)
    if s is None:
        s = pygame.Surface((CELL_W, CELL_H), pygame.SRCALPHA)
        if len(key) == 1:
            _put(s, 8, "     ?", PAIR_GOOD)
            _put(s, 0x18, "     ?", PAIR_MP)
        else:
            _put(s, 8, f"{key[0]:6d}", key[2])
            _put(s, 0x18, f"{key[1]:6d}", key[3])
        if len(_cache) > 512:
            _cache.clear()
        _cache[key] = s
    return s


def tick(scene: "BattleScene") -> None:
    """每 battle tick: 战斗进行中且设定开 → 高度 +2 到 32, 否则 -2 到 0."""
    from core import game_settings
    from core.battle.tactics import Phase
    h = getattr(scene, '_enemy_panel_h', 0)
    if scene.battle.phase in (Phase.VICTORY, Phase.DEFEAT) or not game_settings.get("battle_enemy_status"):
        h = max(0, h - GROW)
    else:
        h = min(CELL_H, h + GROW)
    scene._enemy_panel_h = h


def draw(scene: "BattleScene", drawn_units) -> None:
    """drawn_units: 这一帧画了的单位 (units.unit_drawn); 位置 = units.draw_unit 记下的实体锚点."""
    h = getattr(scene, '_enemy_panel_h', 0)
    if h <= 0:
        return
    for u in drawn_units:
        if u.is_player:
            continue
        pos = getattr(u, '_panel_anchor', None)
        if pos is None:
            continue
        x, y = pos
        scene.surface.blit(cell(u), (x - 0x10, y - 0x17 - h), pygame.Rect(0, 0, CELL_W, h))
