"""技能施放期间的战场暗化 (exe 各技能 dispatcher 共同流程, 2026-10-22 原版实录 + FUN_004d0cd8 反编译):
state 0: `FUN_004d0cd8(1, 0x1e)` 启动调色板渐变 (除 50..145 号色 (角色/特效色段) 外全部变黑, 30 步, 实测 Wine ≈ 21 tick
≈ 480ms), **渐变完成才** case 10 挂 cast seq; 结束 state 0x28: `FUN_004d0cd8(0, 0x1e)` 渐回原调色板 (再 ≈ 20 tick) 后才收尾.
我们是真彩渲染, 等价做法: 地形层上盖一层黑色 alpha (0→1→0), 单位/特效不受影响; 时序按 ms 换算成 tick.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from core.attack_seq import ATTACK_TICK_MS

if TYPE_CHECKING:
    from core.anim_engine.engine import Engine
    from core.anim_engine.entity import Entity

DIM_FADE_MS = 480                                   # exe 30 步 × 16ms
DIM_TICKS = max(1, round(DIM_FADE_MS / ATTACK_TICK_MS))


def _dim_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'dim' not in ud:
        return
    battle = ud['battle']
    ud['tick'] += 1
    t = min(ud['tick'], DIM_TICKS)
    frac = t / DIM_TICKS
    battle.dim_level = frac if ud['dir'] > 0 else 1.0 - frac
    if ud['tick'] >= DIM_TICKS:
        battle.dim_level = 1.0 if ud['dir'] > 0 else 0.0
        cb = ud.get('on_done')
        eng.destroy(e)
        if cb is not None:
            cb()


def _spawn(battle, direction: int, on_done: Callable | None) -> "Entity":
    e = battle.engine.spawn(think_fn=_dim_think)
    e.flags = 0x800 | 0x10000                       # alive + think, 不渲染
    e.user_data.update(kind='skill_dim', projectile=True, dim=True, battle=battle,
                       dir=direction, tick=0, on_done=on_done)
    return e


def start_skill_dim(battle, on_done: Callable) -> "Entity":
    """渐暗 DIM_TICKS 后调 on_done (= 挂 cast seq). projectile=True 让回合/输入门控等它."""
    return _spawn(battle, +1, on_done)


def end_skill_dim(battle) -> "Entity | None":
    """技能收尾: 渐亮 DIM_TICKS. 没暗过就不做."""
    if getattr(battle, 'dim_level', 0.0) <= 0.0:
        return None
    return _spawn(battle, -1, None)
