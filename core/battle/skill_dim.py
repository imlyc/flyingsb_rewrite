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
# 自定义调色板渐变的 dispatcher (FUN_0040b0c5 60 步): 凤凰掌 实录 渐暗 40 tick / 渐亮 38 tick (颜色是自定义表, 暂仍用黑)
SKILL_DIM_TICKS = {0x17: (40, 38)}


def _dim_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'dim' not in ud:
        return
    battle = ud['battle']
    ud['tick'] += 1
    total = ud['ticks']
    t = min(ud['tick'], total)
    frac = t / total
    battle.dim_level = frac if ud['dir'] > 0 else 1.0 - frac
    if ud['tick'] >= total:
        battle.dim_level = 1.0 if ud['dir'] > 0 else 0.0
        cb = ud.get('on_done')
        eng.destroy(e)
        if cb is not None:
            cb()


def _spawn(battle, direction: int, on_done: Callable | None, ticks: int) -> "Entity":
    e = battle.engine.spawn(think_fn=_dim_think)
    e.flags = 0x800 | 0x10000                       # alive + think, 不渲染
    e.user_data.update(kind='skill_dim', projectile=True, dim=True, battle=battle,
                       dir=direction, tick=0, on_done=on_done, ticks=max(1, ticks))
    return e


def start_skill_dim(battle, on_done: Callable, skill_id: int | None = None) -> "Entity":
    """渐暗 (默认 DIM_TICKS, 自定义调色板技能见 SKILL_DIM_TICKS) 后调 on_done (= 挂 cast seq). projectile=True 让回合/输入门控等它."""
    return _spawn(battle, +1, on_done, SKILL_DIM_TICKS.get(skill_id, (DIM_TICKS, DIM_TICKS))[0])


def end_skill_dim(battle, on_done: Callable | None = None, skill_id: int | None = None) -> "Entity | None":
    """技能收尾: 渐亮后调 on_done. 没暗过就不做 (返回 None)."""
    if getattr(battle, 'dim_level', 0.0) <= 0.0:
        return None
    return _spawn(battle, -1, on_done, SKILL_DIM_TICKS.get(skill_id, (DIM_TICKS, DIM_TICKS))[1])
