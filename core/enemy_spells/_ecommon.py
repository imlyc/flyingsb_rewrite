"""E 组 custom 敌招的公共辅助 (无 MOVES 登记). 2026-10-26.

exe 公共片段:
  OPP (表 6418dc) = 反向朝向 [1, 0, 3, 2]: 受击 seq 6557f0[6418dc[施法者朝向]] = 目标转向施法者.
  hit_unit(): -250 常见体 = FUN_004c4f20 复位 + 受击 seq + FUN_004d0c90 方向刺爆 655c10[d] (目标 x, y+400, z+448)
              (+ 655b18 et00 星爆) (+ FUN_004e52de 8 粒碎屑).
  shake(): FUN_004d8c81(ax, ay, dur) 地震 (首次生成时播 0xe3) — 实体 FUN_004d8b0c 未反编译, 按 son_transform 玄武
           同款实现 (每 t 镜头 ±amp 随机, dur 到 → 归零 + 停 0xe3), **近似**.
  angle_to(): FUN_004ce132 / 004ce25d (atan → 16 位角, 0 = 上, 0x4000 = 右; x += sin·r, y -= cos·r), 用浮点 atan2 **近似**
              exe 的分象限 atan 量化.
"""
from __future__ import annotations

import math

from core.enemy_spells.base import fx, FP, _pos, _rand, _sfx, _dir
from core.jet_skills import _sfx_stop

OPP = (1, 0, 3, 2)                       # 6418dc
SFX_QUAKE = 0xe3


def opp_dir(unit) -> int:
    return OPP[_dir(unit)]


def hit_unit(sp, v, *, face_caster: bool = False, spark: bool = True, spark_dir: int | None = None,
             star: bool = False, chiri: bool = False, jitter: bool = False) -> None:
    """-250 受击体. face_caster: 受击 seq 用 6557f0[6418dc[施法者朝向]] (目标转向施法者); 否则目标自身朝向.
    spark_dir: 刺爆方向 (默认施法者朝向). jitter: 刺爆/星爆 x/y/z 各 ±8 (rand&15 - 8, FUN_004db759 式)."""
    from core.battle import combat
    if not v.alive:
        return
    combat.set_reaction(v, "hit", sp.caster if face_caster else None)
    b = sp.battle
    v._b_hit_tick = b.engine._tick_id            # exe 受击标记起点 (b_common.hits_pending / cur_pos 用)
    d = _dir(sp.caster) if spark_dir is None else spark_dir
    if spark:
        _spark(b, d, v, jitter)
    if star:
        _star(b, v, jitter)
    if chiri:
        from core.pao_skills import _chiri
        _chiri(b, v)


def _jit(b) -> tuple[int, int]:
    """exe 求值序: z, y, x 各 rand&15 - 8 → 画面 (dx, dy) = (x, y - z)."""
    rz = (_rand(b) & 15) - 8
    ry = (_rand(b) & 15) - 8
    rx = (_rand(b) & 15) - 8
    return rx, ry - rz


def _spark(b, d: int, v, jitter: bool) -> None:
    from core.battle import combat
    from core.hit_effect_seq import (HitEffectSpec, UNIVERSAL_SPARK_ATLAS, UNIVERSAL_SPARK_BY_DIR,
                                     UNIVERSAL_SPARK_FRAME_TICKS, HIT_EFFECT_Y_BASELINE_PX)
    from core.pao_skills import hit_pos
    key = ('UP', 'DN', 'LF', 'RT')[d]
    spec = HitEffectSpec(UNIVERSAL_SPARK_ATLAS, list(UNIVERSAL_SPARK_BY_DIR[key]), UNIVERSAL_SPARK_FRAME_TICKS,
                         jittered=False)
    hx, hy = hit_pos(v)
    dx, dy = _jit(b) if jitter else (0, 0)
    combat._spawn_effect_entity(b, (hx >> 16) + dx, (hy >> 16) - HIT_EFFECT_Y_BASELINE_PX + dy, spec)


def _star(b, v, jitter: bool) -> None:
    from core.battle import combat
    from core.bosan_skills import STARBURST_SEQ
    from core.hit_effect_seq import HIT_EFFECT_Y_BASELINE_PX
    from core.pao_skills import hit_pos
    hx, hy = hit_pos(v)
    dx, dy = _jit(b) if jitter else (0, 0)
    combat._spawn_skill_extra_effect(b, (hx >> 16) + dx, (hy >> 16) - HIT_EFFECT_Y_BASELINE_PX + dy, STARBURST_SEQ)


def static_fx(b, think_fn, x: int, y: int, z: int, atlas: int, frame: int, **ud):
    """flags |= 0x40 + 0x134/0x138 = 静态图 (不挂 seq)."""
    return fx(b, think_fn, x, y, z, None, atlas=atlas, frame=frame, **ud)


def angle_to(dx: int, dy: int) -> int:
    """方向 (dx, dy) 的 16 位角 (0 上 / 0x4000 右 / 0x8000 下 / 0xc000 左)."""
    if dx == 0 and dy == 0:
        return 0
    return int(round(math.atan2(dx, -dy) / (2 * math.pi) * 0x10000)) & 0xffff


def dist_xy(e, tx: int, ty: int) -> int:
    """FUN_004cdf61 (m&0x70 == 0x30): sqrt(dx² + dy²), 16.16."""
    return int(math.sqrt(float(e.x - tx) ** 2 + float(e.y - ty) ** 2))


def stop_sfx(b, sid: int) -> None:
    _sfx_stop(b, sid)


def shake(b, ax: int, ay: int, dur: int) -> None:
    """FUN_004d8c81(ax, ay, dur). 共享一个地震实体 (exe DAT_0086a770), 再调只续期."""
    ent = getattr(b, '_e_quake', None)
    if ent is None or ent.user_data.get('quake') is None:
        ent = b.engine.spawn(think_fn=_quake_think)
        ent.user_data.update(quake=True, battle=b, age=0)
        b._e_quake = ent
        _sfx(b, SFX_QUAKE)
    ent.user_data.update(ax=ax, ay=ay, end=ent.user_data['age'] + dur)


def _quake_think(e, eng) -> None:
    ud = e.user_data
    if 'quake' not in ud:
        return
    b = ud['battle']
    ud['age'] += 1
    if ud['age'] >= ud['end']:
        b.shake_offset = (0, 0)
        stop_sfx(b, SFX_QUAKE)
        b._e_quake = None
        eng.destroy(e)
        return
    b.shake_offset = (b.rng.randint(-ud['ax'], ud['ax']), b.rng.randint(-ud['ay'], ud['ay']))


__all__ = ['OPP', 'opp_dir', 'hit_unit', 'static_fx', 'angle_to', 'dist_xy', 'stop_sfx', 'shake', 'FP', '_pos',
           '_rand', '_sfx', '_dir']
