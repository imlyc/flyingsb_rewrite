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
    v._b_hit_tick = spell.battle.engine._tick_id          # exe 受击 seq 起点 (cur_pos 用)
    if d is None:
        d = OPPOSITE[_dir(v)]
    _spark(spell.battle, d, v)
    if starburst:
        _starburst(spell.battle, v)


def ground(v) -> tuple[int, int]:
    """单位格中心 (16.16) = exe 单位 +8/+0xc (不含受击 seq 位移, 子实体出生定位用)."""
    from core.sprites.base import TILE_W, TILE_H
    return (v.x * TILE_W + TILE_W // 2) << 16, (v.y * TILE_H + TILE_H // 2) << 16


# 受击 seq 6557f0[朝向] 的位移 (背离朝向): 实录 (wine/captures/en16_t6_F4556.log 目标 y) 挂上当 tick 起 2 tick 4px,
# 再 4 tick 7px, 再 11 tick 9px, 第 17 tick 归位. 我们的 reaction_offset 是按 ms 插值的 UI 量, 子实体定位用这张表.
_HIT_DISP = ((2, 4), (6, 7), (17, 9))


def hit_disp(battle, v) -> int:
    """目标当前受击后退像素 (react() 记的起点; 没受击 / 已归位 = 0)."""
    t0 = getattr(v, '_b_hit_tick', None)
    if t0 is None:
        return 0
    k = battle.engine._tick_id - t0
    for end, px in _HIT_DISP:
        if 0 <= k < end:
            return px
    return 0


def cur_pos(battle, v) -> tuple[int, int]:
    """exe 目标 +8/+0xc (16.16): 格中心 + 受击 seq 当前位移 (受击后生成的子实体以后退后的位置为准)."""
    x, y = ground(v)
    px = hit_disp(battle, v)
    fx, fy = v.facing
    return x - fx * px * (1 << 16), y - fy * px * (1 << 16)


def finish_on_count(spell) -> None:
    """dispatcher 0x1e 看到子实体计数 (+0x78) 归零 (子实体 -200 后的下一 tick) → 0x28, 再下一 tick 开始渐亮.
    框架 finish() 为飘字 -20 多等 1 tick (_quiet < 2); 无飘字、只等计数的模板不该多等 → 预置 _quiet = 1.
    实录校准: en52_t19 (符号 -200 @250 → 0x28 @251 → 渐亮 @252), en16_t6 同."""
    spell.finish()
    spell._quiet = 1


HIT_FLAG_TICKS = 18     # 受击标记 +0x3c[i]: 挂受击 seq 的 tick 起, 第 18 tick dispatcher 才看到清零 (实录 en14_t5: 受击 @133 → 0x28 @151)


def hits_pending(spell) -> bool:
    """exe 0x1e 等的受击标记 (按 exe 受击 seq 时长, 不看我们按 ms 推进的 reaction_seq)."""
    now = spell.battle.engine._tick_id
    return any(getattr(v, '_b_hit_tick', None) is not None and now - v._b_hit_tick < HIT_FLAG_TICKS
               for v in spell.targets)
