"""捕山 5 技能 (skill 0x34..0x38) + 地雷触发, 2026-10-23 按 exe 逆向 (reverse_engineering/bosan_decomp.txt,
bosan_thinks_decomp.txt, bosan_mine_decomp.txt, fn_4a6efe.txt).
资源: 施法 cpusa_g0 (fm 30, 雷射/喷火) / cpusa_m0 (32, 投掷) / cpusa_m1 (33, 埋雷); 手榴彈 epusa00 (280); 炸药 epusa01 (281);
光束 epusa02 (282); 火焰 firez (305); 地雷 eg (240); 爆炸 fire02 (310) / fire01 (309); 碎屑 ds_chiri (227).

  0x34 手榴彈 / 0x36 黃色炸藥 (FUN_0050a848 / 50afe5, 模板同破无): 施法 seq 678ffc[dir] (cpusa_m0), -100 播 0xf2 / 0x102 →
       每目标一颗 (FUN_0050a5be / 50ad5b): 生在施法者 z+32, 抛物线飞向目标: |dx|>|dy| 横 ±8 竖 dy/(|dx|/8), 否则竖 ±6 横 dx/(|dy|/6);
       z 弹簧 (目标 32, 加速度 0.2 / 0.3), 初速 = 步数·a/2 (上抛); seq 67915c / 6792bc[dir]; 预走 1 步.
       到达 → -200 红字 + -250: 受击 (目标自身朝向) + 方向刺爆 655c10[施法者朝向] + 爆炸 (目标 x, y+400, z+432) fire02 + 0xd6 / fire01 + 0xf6.
       0x14 → 0x1e 自毁, 施法者 2 拍后待机 (同破无).
  0x35 裝置地雷 (FUN_0050bdff): 确认时在光标格 (正前一格, 须空格无雷, 最多 30) 建地雷实体 (FUN_004a30f4, 不可见);
       施法 seq 67957c[dir] (cpusa_m1: 先走进那格 48/64px, 6 帧, -100, 退回, -200); -100 播 0x10e + 地雷显形 (eg 帧 0); -200 收尾.
       触发 (FUN_004a4f94 敌方行动 case 4): 敌人移动完站在雷上 (类型非 0x10000000) → 本回合改执行招式 247 (FUN_0050bff2):
       固定 444 伤害, 受击方向 = 表 6418dc[自身朝向] (=反向, 转身), 方向刺爆 655c10[自身朝向], fire01 火爆 (x±6, y+124, z+172),
       立即红字, 0xf6, 移除地雷; 等火爆播完 + 飘字落定 → 回合结束 (不再攻击). 我方单位不触发.
  0x37 雷射光 (FUN_0050b93c): 施法 seq 6793ac[dir] (cpusa_g0), -100 → 光束控制器 (FUN_0050b8f7, 88 tick, 播 0xe4):
       每 tick 在施法者 (x, y+600, z+624) + 方向偏移处生一段光 (epusa02, 帧 = 全局帧计数%3 (+3 竖向), 32px/t 沿朝向飞,
       出生 tick 不动, 出屏 [-100,740]×[-100,580] 自毁); age%20==0 → -250 全目标 受击 (面向施法者) + 方向刺爆 + 8 碎屑;
       age 88 → 停 0xe4, -200 全目标红字, 自毁.
  0x38 火炎發射機 (FUN_0050c63b): 施法 seq 6795fc[dir] (cpusa_g0 2 帧), -100 → 喷火控制器 (FUN_0050c565, 播 0xba):
       age<6 或 age%3==0 时在施法者 + 方向偏移 (上下 16 / 左右 24, z+32) 生火焰 (FUN_0050c2ac, seq 67960c firez, 环绕模式:
       rx = (age/3)·24, ry = (age/3)·18 沿角 φ 外扩); φ 从朝向角起每 t +0x147, 偏离 >0x1000 反向 (左右扫 ±22.5°);
       age%32==0 且 >30 → -250 全目标 受击 (面向施法者) + 刺爆 + et00 星爆 + 碎屑 + 0xbd; age 128 → 停 0xba, -200 红字, 自毁.
实现同 core.pao_skills: 施法 seq 的 -100 换成 BOSAN_SIG (埋雷的 -200 换成 BOSAN_END), 经 skill_seq.SKILL_CAST_SIGNAL_HANDLERS 转发.
数值 (伤害) 仍是占位公式; 地雷 444 是 exe 固定值.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from core.anim_engine.bytecode import tuple_to_bytecode
from core.anim_engine.entity import SIG_END
from core.sprites.base import TILE_W, TILE_H

if TYPE_CHECKING:
    from core.anim_engine.engine import Engine
    from core.anim_engine.entity import Entity

FP = 1 << 16
BOSAN_SIG = -1011               # = exe -100
BOSAN_END = -1012               # = 埋雷 seq 末尾的 -200
BOSAN_SKILLS = (0x34, 0x35, 0x36, 0x37, 0x38)

CPUSA_G0, CPUSA_M0, CPUSA_M1 = 30, 32, 33
EPUSA00, EPUSA01, EPUSA02, FIREZ, EG, FIRE01, FIRE02 = 280, 281, 282, 305, 240, 309, 310

SFX_GRENADE, SFX_DYNAMITE = 0xf2, 0x102          # -100
SFX_GRENADE_HIT, SFX_DYNAMITE_HIT = 0xd6, 0xf6   # -250
SFX_MINE_SET = 0x10e
SFX_MINE_BOOM = 0xf6
SFX_LASER = 0xe4
SFX_FLAME = 0xba
SFX_FLAME_HIT = 0xbd

MINE_DAMAGE = 0x1bc             # 444 固定
MINE_MAX = 30
END_DELAY = 2                   # 0x1e 自毁一拍 + 施法者下一拍待机 (同破无)
THROW_Z = 32
LASER_TICKS = 0x58
LASER_HIT_EVERY = 20
LASER_SPEED = 32
FLAME_TICKS = 0x80
FLAME_HIT_EVERY = 32
FLAME_SWEEP_SPEED = 0x147
FLAME_SWEEP_MAX = 0x1000
FLAME_BASE_ANGLE = {0: 0, 1: 0x8000, 2: 0xc000, 3: 0x4000}
FLAME_OFFSET = {0: (0, -16), 1: (0, 16), 2: (-24, 0), 3: (24, 0)}
VIEW_W, VIEW_H = 640, 480


# ---------------- 施法 seq (exe 字节逐 op 转录) ----------------
def _throw(d: int) -> list[tuple]:
    """678ffc[dir] (cpusa_m0, 每方向 5 帧): +0 5t, +1 12t, +3 3t, -100, +4 12t, +0."""
    b = d * 5
    return [('fm', CPUSA_M0, b, 5), ('fm', CPUSA_M0, b + 1, 12), ('fm', CPUSA_M0, b + 3, 3), ('jump', BOSAN_SIG),
            ('fm', CPUSA_M0, b + 4, 12), ('fm', CPUSA_M0, b, 0), ('exit',)]


MINE_STEP = {0: (0, -48), 1: (0, 48), 2: (-64, 0), 3: (64, 0)}


def _mine(d: int) -> list[tuple]:
    """67957c[dir] (cpusa_m1, 每方向 6 帧): 走进前一格, 帧 +0..+5 (3,3,5,6,8,15t), -100, +5 5t, 退回, +0, -200."""
    b = d * 6
    sx, sy = MINE_STEP[d]
    return ([('move', sx, sy, 0)] + [('fm', CPUSA_M1, b + i, t) for i, t in enumerate((3, 3, 5, 6, 8, 15))]
            + [('jump', BOSAN_SIG), ('fm', CPUSA_M1, b + 5, 5), ('move', -sx, -sy, 0), ('fm', CPUSA_M1, b, 0),
               ('jump', BOSAN_END), ('exit',)])


LASER_RECOIL = {0: (0, 4), 1: (0, -4), 2: (4, 0), 3: (-4, 0)}


def _laser(d: int) -> list[tuple]:
    """6793ac[dir] (cpusa_g0, 每方向 8 帧): +0..+2 3t, +3 12t, -100, 后坐 4px."""
    b = d * 8
    rx, ry = LASER_RECOIL[d]
    return ([('fm', CPUSA_G0, b + i, 3) for i in range(3)] + [('fm', CPUSA_G0, b + 3, 12), ('jump', BOSAN_SIG),
            ('move', rx, ry, 0), ('exit',)])


def _flame(d: int) -> list[tuple]:
    """6795fc[dir]: +0, +1 各 3t, -100."""
    b = d * 8
    return [('fm', CPUSA_G0, b, 3), ('fm', CPUSA_G0, b + 1, 3), ('jump', BOSAN_SIG), ('exit',)]


SKILL_BOSAN_THROW = [_throw(d) for d in range(4)]
SKILL_BOSAN_MINE = [_mine(d) for d in range(4)]
SKILL_BOSAN_LASER = [_laser(d) for d in range(4)]
SKILL_BOSAN_FLAME = [_flame(d) for d in range(4)]
BOSAN_SEQS = {0x34: SKILL_BOSAN_THROW, 0x35: SKILL_BOSAN_MINE, 0x36: SKILL_BOSAN_THROW,
              0x37: SKILL_BOSAN_LASER, 0x38: SKILL_BOSAN_FLAME}

GRENADE_SEQS = [[('fm', EPUSA00, f, 1) for f in fr] + [('loop',)]                      # @0x67915c
                for fr in ((0, 1, 2, 3, 5, 6, 7, 8), (8, 7, 6, 5, 3, 2, 1, 0),
                           (4, 10, 11, 12, 9, 13, 14, 15), (15, 14, 13, 9, 12, 11, 10, 4))]
DYNAMITE_SEQS = [[('fm', EPUSA01, f, 2) for f in fr] + [('loop',)]                     # @0x6792bc
                 for fr in ((8, 10, 11, 12, 14, 16, 17, 18), (19, 17, 16, 14, 13, 11, 10, 8),
                            (0, 1, 2, 3, 4, 5, 6, 7), (7, 6, 5, 4, 3, 2, 1, 0))]
FIRE02_SEQ = [('fm', FIRE02, f, 1) for f in range(11)] + [('exit',)]                   # @0x656014
FIRE01_SEQ = [('fm', FIRE01, f, 1) for f in range(11)] + [('exit',)]                   # @0x655fa4
FLAME_SEQ = [('fm', FIREZ, f, 1) for f in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 10)] + [('exit',)]   # @0x67960c
STARBURST_SEQ = [('fm', 215, 14, 4), ('fm', 215, 15, 4), ('exit',)]                   # @0x655b18 et00


# ---------------- 工具 ----------------
def _sfx(battle, sid: int) -> None:
    battle.engine._emit('sound_play', None, sid)


def _sfx_stop(battle, sid: int) -> None:
    battle.engine._emit('sound_stop', None, sid)


def _tile_center(tx: int, ty: int) -> tuple[int, int]:
    return (tx * TILE_W + TILE_W // 2) * FP, (ty * TILE_H + TILE_H // 2) * FP


def _caster_pos(caster) -> tuple[int, int]:
    ent = caster.entity
    x, y = _tile_center(caster.x, caster.y)
    return x + (ent.x if ent is not None else 0), y + (ent.y if ent is not None else 0)


def _rand(battle) -> int:
    return battle.rng.randrange(0x8000)


def _dir(unit) -> int:
    from core.attack_seq import facing_to_atk_index
    return facing_to_atk_index(unit.facing)


def _ctrunc(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def _fx(bt, think_fn, x: int, y: int, z_px: int, seq, /, **ud) -> "Entity":
    e = bt.engine.spawn(think_fn=think_fn)
    e.atlas_slot, e.frame_idx = seq[0][1], seq[0][2]
    e.flags |= 0x40
    e.x, e.y, e.z = x, y, -(z_px << 16)
    e.user_data.update(kind='hit_effect', projectile=True, **ud)
    bt.engine.attach_seq(e, tuple_to_bytecode(seq))
    return e


def _seq_end_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004d0dcf: seq 完自毁; 带 on_end 回调 (地雷火爆完 → dispatcher +0x3c 清)."""
    if 'fx_end' not in e.user_data or e.is_playing():
        return
    cb = e.user_data.get('on_end')
    if cb is not None:
        cb()
    eng.destroy(e)


def _victims(battle, caster) -> list:
    out = []
    tiles = getattr(battle, '_pending_damage_range', None)
    if tiles:
        for (x, y) in sorted(tiles, key=lambda t: (t[1], t[0])):
            t = battle.q.occupant(x, y)
            if t is not None and t.alive and t.is_player != caster.is_player:
                out.append(t)
    else:
        t = caster.pending_attack_target
        if t is not None and t.alive and t is not caster:
            out.append(t)
    return out


# ---------------- -250 公共 ----------------
def _spark(battle, d: int, victim) -> None:
    """FUN_004d0c90(目标 x, y+400, z+448, 655c10[d]) = ef010 方向刺爆."""
    from core.battle import combat
    from core.hit_effect_seq import (HitEffectSpec, UNIVERSAL_SPARK_ATLAS, UNIVERSAL_SPARK_BY_DIR,
                                     UNIVERSAL_SPARK_FRAME_TICKS, HIT_EFFECT_Y_BASELINE_PX)
    key = ('UP', 'DN', 'LF', 'RT')[d]
    spec = HitEffectSpec(UNIVERSAL_SPARK_ATLAS, list(UNIVERSAL_SPARK_BY_DIR[key]), UNIVERSAL_SPARK_FRAME_TICKS, jittered=False)
    cx = victim.x * TILE_W + TILE_W // 2
    cy = victim.y * TILE_H + TILE_H // 2 - HIT_EFFECT_Y_BASELINE_PX
    combat._spawn_effect_entity(battle, cx, cy, spec)


def _starburst(battle, victim) -> None:
    """FUN_004d0c90(..., 655b18) = et00 星爆 帧 14,15 (无抖动)."""
    from core.battle import combat
    from core.hit_effect_seq import HIT_EFFECT_Y_BASELINE_PX
    cx = victim.x * TILE_W + TILE_W // 2
    cy = victim.y * TILE_H + TILE_H // 2
    combat._spawn_skill_extra_effect(battle, cx, cy - HIT_EFFECT_Y_BASELINE_PX, STARBURST_SEQ)


def _hit(battle, caster, victim, *, face_caster: bool, chiri: bool, starburst: bool = False) -> None:
    """受击 seq (face_caster: 表 6418dc[施法者朝向] = 面朝施法者; 否则目标自身朝向) + 刺爆 655c10[施法者朝向] (+ 星爆 / 碎屑)."""
    from core.battle import combat
    from core.pao_skills import _chiri
    if not victim.alive:
        return
    combat.set_reaction(victim, "hit", caster if face_caster else None)
    _spark(battle, _dir(caster), victim)
    if starburst:
        _starburst(battle, victim)
    if chiri:
        _chiri(battle, victim)


def _damage(battle, caster, victims) -> None:
    from core.son_transform import _damage_only
    for v in victims:
        _damage_only(battle, caster, v)


# ---------------- 协调实体 (dispatcher 收尾) ----------------
def _coord_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'bosan' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    if not ud['fired'] or ud['live'] > 0:
        return
    if getattr(battle, 'float_pending', 0) > 0:
        return
    if any(v.reaction_seq is not None for v in ud['victims']):
        return
    ud['end_wait'] = ud.get('end_wait', 0) + 1
    if ud['end_wait'] <= ud.get('end_delay', END_DELAY):
        return
    caster.cast_hold = False
    ud['unit'] = caster
    eng._signal(e, SIG_END)
    eng.destroy(e)


def _spawn_coord(battle, caster, victims) -> "Entity":
    e = battle.engine.spawn(think_fn=_coord_think)
    e.flags = 0x800 | 0x10000
    e.user_data.update(kind='bosan_coord', projectile=True, bosan=True, battle=battle, caster=caster,
                       sid=caster.pending_skill_id, victims=victims, live=0, fired=False)
    return e


# ---------------- 手榴彈 / 黃色炸藥 ----------------
def _throw_think(e: "Entity", eng: "Engine") -> None:
    """FUN_0050a533: z 弹簧 (mode 0x41) + x,y 匀速钳 (FUN_004cdbc2); 到达 → -200 + -250."""
    from core.pao_skills import _cdbc2
    ud = e.user_data
    if 'throw' not in ud:
        return
    ud['vz'] += -ud['az'] if ud['ez'] >= ud['tz'] else ud['az']
    ud['ez'] += ud['vz']
    e.z = -ud['ez']
    if not _cdbc2(e):
        return
    cd = ud['coord'].user_data
    battle, caster, victim, sid = cd['battle'], cd['caster'], ud['victim'], cd['sid']
    cd['live'] -= 1
    _damage(battle, caster, [victim])                                           # -200
    _hit(battle, caster, victim, face_caster=False, chiri=False)               # -250
    vx, vy = _tile_center(victim.x, victim.y)
    _fx(battle, _seq_end_think, vx, vy + (400 << 16), 432, FIRE02_SEQ if sid == 0x34 else FIRE01_SEQ, fx_end=True)
    _sfx(battle, SFX_GRENADE_HIT if sid == 0x34 else SFX_DYNAMITE_HIT)
    eng.destroy(e)


def _spawn_throw(battle, coord, caster, victim, sid: int) -> None:
    """FUN_0050a5be / 50ad5b."""
    x0, y0 = _caster_pos(caster)
    tx, ty = _tile_center(victim.x, victim.y)
    dx, dy = tx - x0, ty - y0
    az = 0x3333 if sid == 0x34 else 0x4ccc
    if abs(dy) < abs(dx):
        vx = 8 * FP if dx >= 1 else -8 * FP
        steps = max(1, abs(dx) >> 19)
        vy = _ctrunc(dy, steps)
        d = 2 if vx < 1 else 3
    else:
        steps = max(1, abs(dy) // (6 * FP))
        vx = _ctrunc(dx, steps)
        vy = 6 * FP if dy >= 1 else -6 * FP
        d = 0 if vy < 1 else 1
    seq = (GRENADE_SEQS if sid == 0x34 else DYNAMITE_SEQS)[d]
    vz = (steps * az) // 2
    e = battle.engine.spawn(think_fn=_throw_think)
    e.atlas_slot, e.frame_idx = seq[0][1], seq[0][2]
    e.flags |= 0x40
    e.user_data.update(kind='hit_effect', projectile=True, throw=True, coord=coord, victim=victim,
                       vx=vx, vy=vy, tx=tx, ty=ty, axes=0x30, ez=THROW_Z * FP, tz=THROW_Z * FP, vz=vz, az=az)
    # 预走 1 步 (FUN_004c3211 mode 0x71: x,y 匀速, z 弹簧)
    e.x, e.y = x0 + vx, y0 + vy
    ud = e.user_data
    ud['vz'] += -az if ud['ez'] >= ud['tz'] else az
    ud['ez'] += ud['vz']
    e.z = -ud['ez']
    battle.engine.attach_seq(e, tuple_to_bytecode(seq))
    coord.user_data['live'] += 1


# ---------------- 雷射光 ----------------
def _view_origin(battle, caster) -> tuple[int, int]:
    """屏幕左上角的世界 px (exe +0x120/+0x124 屏幕坐标用). 无 UI 时以施法者为屏中心."""
    view = getattr(battle, 'view_center_world', None)
    if view is None:
        cx, cy = _tile_center(caster.x, caster.y)
        view = (cx >> 16, cy >> 16)
    return view[0] - VIEW_W // 2, view[1] - VIEW_H // 2


LASER_OFF = {0: (0, -62, 0), 1: (-4, 24, 0), 2: (-40, 0, 10), 3: (46, 0, 4)}
LASER_V = {0: (0, -LASER_SPEED), 1: (0, LASER_SPEED), 2: (-LASER_SPEED, 0), 3: (LASER_SPEED, 0)}


def _segment_think(e: "Entity", eng: "Engine") -> None:
    """FUN_0050b4f8: 出生 tick 不动; 之后匀速 + 帧 = 全局帧计数%3 (+3 竖向); 出屏自毁."""
    ud = e.user_data
    if 'segment' not in ud or ud['born'] == eng._tick_id:
        return
    e.x += ud['vx'] * FP
    e.y += ud['vy'] * FP
    e.frame_idx = eng._tick_id % 3 + (3 if ud['d'] < 2 else 0)
    ox, oy = ud['origin']
    sx = (e.x >> 16) - ox
    sy = ((e.y + e.z) >> 16) - oy
    if sx < -100 or sx > VIEW_W + 100 or sy < -100 or sy > VIEW_H + 100:
        eng.destroy(e)


def _spawn_segment(battle, caster, d: int, origin) -> None:
    """FUN_0050b5ee."""
    x, y = _caster_pos(caster)
    ox, oy, oz = LASER_OFF[d]
    vx, vy = LASER_V[d]
    e = battle.engine.spawn(think_fn=_segment_think)
    e.atlas_slot = EPUSA02
    e.frame_idx = battle.engine._tick_id % 3 + (3 if d < 2 else 0)
    e.flags |= 0x40
    e.x, e.y = x + (ox << 16), y + ((600 + oy) << 16)
    e.z = -((624 + oz) << 16)
    e.user_data.update(kind='hit_effect', projectile=True, segment=True, d=d, vx=vx, vy=vy,
                       born=battle.engine._tick_id, origin=origin)


def _laser_think(e: "Entity", eng: "Engine") -> None:
    """FUN_0050b867."""
    ud = e.user_data
    if 'laser' not in ud:
        return
    cd = ud['coord'].user_data
    battle, caster = cd['battle'], cd['caster']
    age = ud['age']
    _spawn_segment(battle, caster, _dir(caster), _view_origin(battle, caster))
    if age % LASER_HIT_EVERY == 0:                                     # -250
        for v in cd['victims']:
            _hit(battle, caster, v, face_caster=True, chiri=True)
    if age == LASER_TICKS:
        _sfx_stop(battle, SFX_LASER)
        cd['live'] -= 1
        _damage(battle, caster, cd['victims'])                         # -200
        eng.destroy(e)
        return
    ud['age'] += 1


# ---------------- 火炎發射機 ----------------
def _flame_particle_think(e: "Entity", eng: "Engine") -> None:
    """FUN_0050c230: rx = (age/3)·24, ry = (age/3)·18 沿 φ 外扩 (mode 2), seq 完自毁."""
    ud = e.user_data
    if 'flame' not in ud:
        return
    ud['age'] += 1
    k = ud['age'] // 3
    a = ud['phi'] / 65536 * 2 * math.pi
    e.x = ud['cx'] + int(math.sin(a) * FP) * (k * 24)
    e.y = ud['cy'] - int(math.cos(a) * FP) * (k * 18)
    if not e.is_playing():
        eng.destroy(e)


def _flamer_think(e: "Entity", eng: "Engine") -> None:
    """FUN_0050c34c."""
    ud = e.user_data
    if 'flamer' not in ud:
        return
    cd = ud['coord'].user_data
    battle, caster = cd['battle'], cd['caster']
    age = ud['age']
    if age < 6 or age % 3 == 0:
        d = _dir(caster)
        x, y = _caster_pos(caster)
        ox, oy = FLAME_OFFSET[d]
        cx, cy = x + (ox << 16), y + (oy << 16)
        _fx(battle, _flame_particle_think, cx, cy, 32, FLAME_SEQ, flame=True, cx=cx, cy=cy, phi=ud['phi'] & 0xffff, age=0)
    ud['phi'] += ud['speed']
    if abs(ud['phi'] - ud['base']) > FLAME_SWEEP_MAX:
        ud['speed'] = -ud['speed']
    if age % FLAME_HIT_EVERY == 0 and age > 30:                       # -250
        for v in cd['victims']:
            _hit(battle, caster, v, face_caster=True, chiri=True, starburst=True)
        _sfx(battle, SFX_FLAME_HIT)
    if age == FLAME_TICKS:
        _sfx_stop(battle, SFX_FLAME)
        cd['live'] -= 1
        _damage(battle, caster, cd['victims'])                         # -200
        eng.destroy(e)
        return
    ud['age'] += 1


# ---------------- 地雷 ----------------
def _mine_noop(e: "Entity", eng: "Engine") -> None:
    pass


def can_place_mine(battle, tile: tuple[int, int]) -> bool:
    """FUN_004a6efe 埋雷校验: 格可通行 + 无人 + 无雷 + 总数 < 30."""
    mines = getattr(battle, 'mines', {})
    x, y = tile
    return (battle.map.in_bounds(x, y) and battle.map.passable(x, y) and battle.q.occupant(x, y) is None
            and tile not in mines and len(mines) < MINE_MAX)


def _place_mine(battle, tile: tuple[int, int]) -> None:
    """-100: 地雷显形 (eg 帧 0) + 0x10e."""
    if not hasattr(battle, 'mines'):
        battle.mines = {}
    x, y = _tile_center(*tile)
    e = battle.engine.spawn(think_fn=_mine_noop)
    e.atlas_slot, e.frame_idx = EG, 0
    e.flags |= 0x40
    e.x, e.y, e.z = x, y, 0
    e.state_code = 20                      # 常驻但不阻塞回合推进 (PROJ_STATE_DONE)
    e.user_data.update(kind='hit_effect', projectile=True, mine=True, draw_order=-10)
    battle.mines[tile] = e
    _sfx(battle, SFX_MINE_SET)


def mine_at(battle, unit) -> bool:
    return (unit.x, unit.y) in getattr(battle, 'mines', {})


def _mine_coord_think(e: "Entity", eng: "Engine") -> None:
    """FUN_0050bff2 case 10: 火爆播完 (+0x3c) 且飘字落定 (+0x3e) → 自毁 → 该敌回合结束."""
    ud = e.user_data
    if 'mine_coord' not in ud:
        return
    battle, unit = ud['battle'], ud['unit_hit']
    if ud['burst_live'] or getattr(battle, 'float_pending', 0) > 0:
        return
    eng.destroy(e)
    battle.post_attack_anim(unit)


def trigger_mine(battle, unit) -> None:
    """敌人站在雷上 (FUN_004a4f94 case 4 → 招式 247 FUN_0050bff2): 444 固定伤害, 转身受击, 刺爆, fire01 火爆, 红字, 0xf6, 移除地雷."""
    from core.battle import combat
    from core.battle.data import DamageEvent
    mine = battle.mines.pop((unit.x, unit.y))
    battle.engine.destroy(mine)                                            # FUN_004a30a2
    d = _dir(unit)
    old = unit.hp
    unit.hp = max(0, old - MINE_DAMAGE)
    unit.shown_hp_override = old
    unit.settle_pending = True
    unit.facing = (-unit.facing[0], -unit.facing[1])                       # 受击 seq = 6557f0[6418dc[自身朝向]] (反向)
    unit.reaction_saved_facing = None
    combat.set_reaction(unit, "hit", None)
    _spark(battle, d, unit)
    coord = battle.engine.spawn(think_fn=_mine_coord_think)
    coord.flags = 0x800 | 0x10000
    coord.user_data.update(kind='mine_coord', projectile=True, mine_coord=True, battle=battle, unit_hit=unit, burst_live=1)

    def _burst_done():
        coord.user_data['burst_live'] = 0
    rng_x = (_rand(battle) % 12) - 6
    vx, vy = _tile_center(unit.x, unit.y)
    _fx(battle, _seq_end_think, vx + (rng_x << 16), vy + (124 << 16), 172, FIRE01_SEQ, fx_end=True, on_end=_burst_done)
    combat.push_damage_event(battle, unit, DamageEvent(MINE_DAMAGE, unit.hp, unit.x, unit.y))
    _sfx(battle, SFX_MINE_BOOM)
    battle._log(f"{unit.name} 踩中地雷: {MINE_DAMAGE} ({unit.hp}/{unit.max_hp})")


# ---------------- 施法 seq 信号入口 ----------------
def on_cast_signal(battle, caster, sig: int) -> bool:
    if sig not in (BOSAN_SIG, BOSAN_END):
        return False
    sid = caster.pending_skill_id
    ent = caster.entity
    if sid == 0x35:
        if sig == BOSAN_SIG:
            _place_mine(battle, caster.pending_attack_cursor)
        else:                                                              # -200 → +0x78=0 → 自毁 (无飘字)
            coord = _spawn_coord(battle, caster, [])
            coord.user_data.update(fired=True, end_delay=0)
        return True
    if sig != BOSAN_SIG:
        return True
    victims = _victims(battle, caster)
    coord = _spawn_coord(battle, caster, victims)
    ent.user_data['bosan_coord'] = coord
    if sid in (0x34, 0x36):
        _sfx(battle, SFX_GRENADE if sid == 0x34 else SFX_DYNAMITE)
        for v in victims:
            _spawn_throw(battle, coord, caster, v, sid)
    elif sid == 0x37:
        c = battle.engine.spawn(think_fn=_laser_think)
        c.flags = 0x800 | 0x10000
        c.user_data.update(kind='laser_ctl', projectile=True, laser=True, coord=coord, age=0)
        coord.user_data['live'] += 1
        _sfx(battle, SFX_LASER)
    elif sid == 0x38:
        base = FLAME_BASE_ANGLE[_dir(caster)]
        c = battle.engine.spawn(think_fn=_flamer_think)
        c.flags = 0x800 | 0x10000
        c.user_data.update(kind='flame_ctl', projectile=True, flamer=True, coord=coord, age=0, phi=base, base=base,
                           speed=FLAME_SWEEP_SPEED)
        coord.user_data['live'] += 1
        _sfx(battle, SFX_FLAME)
    coord.user_data['fired'] = True
    return True
