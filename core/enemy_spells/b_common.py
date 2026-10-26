"""B 组敌招模块的公共小工具 (t4dafa6 / t4d2769 / t4d194c / t4d3a4b / t4d30e0 共用), 无 TEMPLATES/MOVES."""
from __future__ import annotations

from core.enemy_spells.base import _dir

OPPOSITE = (1, 0, 3, 2)          # exe 表 DAT_006418dc: 朝向 → 反向


def react(spell, v, d: int | None = None, starburst: bool = False) -> None:
    """模板 -250: FUN_004c4f20 复位 + 受击 seq 6557f0[目标朝向] + FUN_004d0c90(目标 x, y+400, z+448, 655c10[d]) ef010 刺爆.
    d=None → 6418dc[目标朝向] (面朝目标反向); starburst → 再加 655b18 et00 星爆 (FUN_004dafa6).
    特效位置走 bosan._spark (受击后退后的位置, 已对过原版)."""
    from core.battle import combat
    from core.bosan_skills import _spark, _starburst
    if not v.alive:
        return
    combat.set_reaction(v, "hit", None)
    if d is None:
        d = OPPOSITE[_dir(v)]
    _spark(spell.battle, d, v)
    if starburst:
        _starburst(spell.battle, v)


def ground(v) -> tuple[int, int]:
    """单位格中心 (16.16) = exe 单位 +8/+0xc (不含受击 seq 位移, 子实体出生定位用)."""
    from core.sprites.base import TILE_W, TILE_H
    return (v.x * TILE_W + TILE_W // 2) << 16, (v.y * TILE_H + TILE_H // 2) << 16
