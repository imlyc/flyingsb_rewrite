"""D 组敌招共用的小工具 (命中特效 / 自定义受击 seq / 隐形控制实体). 无 TEMPLATES/MOVES.

exe FUN_004d0c90(x, y+400, z+448, dir, seq) 生成一次性特效; 我们按 base.hit 的约定画在目标格中心 (上移 25px 基线).
"""
from __future__ import annotations

from core.enemy_spells.base import _rand


def _effect(battle, victim, spec, jitter: bool) -> None:
    from core.battle import combat
    from core.hit_effect_seq import HIT_EFFECT_Y_BASELINE_PX
    from core.sprites.base import TILE_W, TILE_H
    cx = victim.x * TILE_W + TILE_W // 2
    cy = victim.y * TILE_H + TILE_H // 2 - HIT_EFFECT_Y_BASELINE_PX
    if jitter:                                   # exe: 三轴各 (rand & 15) - 8
        cx += (_rand(battle) & 15) - 8
        cy += (_rand(battle) & 15) - 8
        cy -= (_rand(battle) & 15) - 8           # z 抖动 (z 向上 = 屏幕 y 减)
    combat._spawn_effect_entity(battle, cx, cy, spec)


def starburst(battle, victim, jitter: bool = False) -> None:
    """FUN_004d0c90(..., &DAT_00655b18) = et00 紫色星爆 (帧 14,15 各 4t)."""
    from core.hit_effect_seq import (HitEffectSpec, UNIVERSAL_STARBURST_ATLAS, UNIVERSAL_STARBURST_FRAMES,
                                     UNIVERSAL_STARBURST_FRAME_TICKS)
    spec = HitEffectSpec(UNIVERSAL_STARBURST_ATLAS, list(UNIVERSAL_STARBURST_FRAMES), UNIVERSAL_STARBURST_FRAME_TICKS,
                         jittered=False)
    _effect(battle, victim, spec, jitter)


def spark(battle, caster, victim, jitter: bool = False) -> None:
    """FUN_004d0c90(..., 655c10[施法者朝向]) = ef010 方向红刺爆."""
    from core.hit_effect_seq import (HitEffectSpec, facing_to_dir, UNIVERSAL_SPARK_ATLAS, UNIVERSAL_SPARK_BY_DIR,
                                     UNIVERSAL_SPARK_FRAME_TICKS)
    d = facing_to_dir(caster.facing)
    spec = HitEffectSpec(UNIVERSAL_SPARK_ATLAS, list(UNIVERSAL_SPARK_BY_DIR[d]), UNIVERSAL_SPARK_FRAME_TICKS,
                         jittered=False)
    _effect(battle, victim, spec, jitter)


def custom_reaction(unit, steps: list[tuple]) -> None:
    """给目标挂自定义受击 seq (core.reaction_seq 格式: ('frame', atlas06 帧) / ('move', dx, dy, ticks)), 不转向."""
    from core.battle import combat
    combat.set_reaction(unit, "hit", None)
    unit.reaction_seq = steps


def ctl(battle, think_fn, **ud):
    """隐形控制实体 (exe FUN_004c4936(think) 不挂 seq): projectile=True 让回合等它, 不渲染."""
    e = battle.engine.spawn(think_fn=think_fn)
    e.user_data.update(kind='enemy_spell_ctl', projectile=True, **ud)
    return e
