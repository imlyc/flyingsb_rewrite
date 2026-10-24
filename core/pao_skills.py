"""破无 5 技能 (skill 0x2f..0x33), 2026-10-23 按 exe 逆向 (reverse_engineering/pao_decomp.txt, pao_thinks_decomp.txt).
资源: 施法 cpao_g0 (fm 27, 每方向 11 帧); 箭 eobj (330); 火爆 fire00 (308) / fire01 (309); 雷击 esund (293);
雷环 ds_mag13 (230); 命中碎屑 ds_chiri (227).

dispatcher 模板 FUN_00508253 (三角箭/火炎箭/三角火箭/雷箭) / FUN_00508a21 (亂箭, 只差施法 seq), 参数 = 箭的 4 方向 seq 表:
  case 0: **无渐变**, 挂施法 seq 6780bc[dir] (亂箭 67850c[dir]); seq 的 -100 → 对每个目标 FUN_00507a8a 发一支箭 + 播 200 (0xc8) → 0x14.
  箭 (FUN_00507a18): 生在施法者 (x, y, z+32), 飞向目标格中心: |dx|>|dy| 时 横 ±32 px/t, 竖 = dy/步数 (步数 = |dx|/32);
       否则 竖 ±24, 横 = dx/(|dy|/24); 方向 (上 0 / 下 1 / 左 2 / 右 3) 由速度定, seq = 表[方向]; 出生先走 1 步;
       FUN_004cdbc2 两轴都到 → 播 0xbf, 以**目标**为来源发 -200 + -250, 自毁.
  -200: 该目标红字 (FUN_004d05d8). -250: 该目标 受击 seq 6557f0 + 方向刺爆 655c10[**施法者**朝向] (目标 x, y+400, z+448)
       + FUN_004e52de 8 粒碎屑 (目标 x, y+400, z+436; vx,vy = rand·16/65536 - 4 px/t, vz 从 0 每 t -0.8, z<392 自毁;
       首次 think 才挂 seq 66a870 = ds_chiri 帧 8-15 各 1t).
  各招 -250 的附加 (先于模板): 火炎箭 火爆 fire00 (seq 655f28) + 0xd6; 三角火箭 火爆 fire01 (655fa4) + 0xd7
       (火爆在 目标 x + rand%12-6, y+124, z+172); 雷箭 FUN_0050893f 雷击 esund (seq 67824c 帧 0-5) 在目标 + 0xf6,
       雷击播完 → FUN_004d66cc 4 道雷环 ds_mag13 (seq 656b0c 帧 5-11): 绕目标 (mode 2) 起角 (rand&0xff)·64 + k·0x4000,
       半径 rx/ry 每 t 各 +4+rand&3, seq 完自毁.
  0x14: 箭全发出 + 全部 -200 到齐 + 飘字 -20 归零 + 受击播完 → 0x1e 直接自毁 (**不走渐亮**).
实现同 core.pig_skills: 施法 seq 的 -100 换成专用信号 PAO_SIG, 经 skill_seq.SKILL_CAST_SIGNAL_HANDLERS 转到 on_cast_signal.
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
PAO_SIG = -1010
PAO_SKILLS = (0x2f, 0x30, 0x31, 0x32, 0x33)

CPAO_G0 = 27
EOBJ, FIRE00, FIRE01, ESUND, DS_MAG13, DS_CHIRI = 330, 308, 309, 293, 230, 227

SFX_SHOOT = 200                 # 0xc8 -100 发箭
SFX_ARROW_HIT = 0xbf            # 箭到达
SFX_FIRE_ARROW = 0xd6           # 火炎箭 -250
SFX_TRI_FIRE = 0xd7             # 三角火箭 -250
SFX_THUNDER = 0xf6              # 雷箭 雷击
SFX_RAIN = 0x10d                # 亂箭 施法 seq 内

ARROW_Z = 32
END_DELAY = 2
ARROW_VX, ARROW_VY = 32, 24
HIT_Y, HIT_Z = 400, 448         # FUN_004d0c90 (x, y+0x190, z+0x1c0) 约定: 画在 y-48
CHIRI_Y, CHIRI_Z, CHIRI_Z_END = 400, 436, 392
CHIRI_COUNT = 8
CHIRI_GRAVITY = 0xcccc
BURST_Y, BURST_Z = 124, 172


# ---------------- 施法 seq (exe 字节逐 op 转录) ----------------
def _cast(d: int) -> list[tuple]:
    """6780bc[dir]: 帧 d*11+0..5 各 3t, +6 停 8t, +7, -100, +8..+10, -150."""
    b = d * 11
    return ([('fm', CPAO_G0, b + i, 3) for i in range(6)] + [('fm', CPAO_G0, b + 6, 8), ('fm', CPAO_G0, b + 7, 3),
            ('jump', PAO_SIG)] + [('fm', CPAO_G0, b + i, 3) for i in (8, 9, 10)] + [('jump', -150), ('exit',)])


RAIN_SPIN = {0: (28, 17, 39), 1: (39, 6, 28), 2: (17, 39, 6), 3: (6, 28, 17)}   # 亂箭 转身 3 帧 (其它方向的拉弓帧)


def _rain_cast(d: int) -> list[tuple]:
    """67850c[dir]: 帧 +0..+6 各 3t, 播 0x10d, 转一圈 3 帧, +6 停 12t, +7, -100, +8..+10."""
    b = d * 11
    return ([('fm', CPAO_G0, b + i, 3) for i in range(7)] + [('sound', SFX_RAIN, 0x0411)]
            + [('fm', CPAO_G0, f, 3) for f in RAIN_SPIN[d]] + [('fm', CPAO_G0, b + 6, 12), ('fm', CPAO_G0, b + 7, 3),
            ('jump', PAO_SIG)] + [('fm', CPAO_G0, b + i, 3) for i in (8, 9, 10)] + [('exit',)])


SKILL_PAO_CAST = [_cast(d) for d in range(4)]
SKILL_PAO_RAIN = [_rain_cast(d) for d in range(4)]
PAO_SEQS = {0x2f: SKILL_PAO_CAST, 0x30: SKILL_PAO_CAST, 0x31: SKILL_PAO_CAST, 0x32: SKILL_PAO_CAST, 0x33: SKILL_PAO_RAIN}

ARROW_PLAIN = [[('fm', EOBJ, f, 0), ('exit',)] for f in (17, 16, 19, 18)]                     # @0x677c8c
ARROW_FIRE = [[('fm', EOBJ, f, 1) for f in fr] + [('loop',)]                                    # @0x677d1c
              for fr in ((5, 4, 3), (2, 1, 0), (8, 7, 6), (9, 10, 11))]
ARROW_THUNDER = [[('fm', EOBJ, f, 1) for f in fr] + [('loop',)]                                 # @0x677dac
                 for fr in ((32, 33, 34), (37, 36, 35), (38, 39, 40), (43, 42, 41))]
ARROW_RAIN = [[('fm', EOBJ, f, 1) for f in fr] + [('loop',)]                                    # @0x677ecc
              for fr in ((56, 57, 58), (59, 60, 61), (62, 63, 64), (65, 66, 67))]
ARROW_SEQS = {0x2f: ARROW_PLAIN, 0x30: ARROW_FIRE, 0x31: ARROW_FIRE, 0x32: ARROW_THUNDER, 0x33: ARROW_RAIN}

FIRE00_SEQ = [('fm', FIRE00, f, 1) for f in range(12)] + [('exit',)]       # @0x655f28
FIRE01_SEQ = [('fm', FIRE01, f, 1) for f in range(11)] + [('exit',)]       # @0x655fa4
THUNDER_SEQ = [('fm', ESUND, f, 1) for f in range(6)] + [('exit',)]        # @0x67824c
RING_SEQ = [('fm', DS_MAG13, f, 1) for f in range(5, 12)] + [('exit',)]    # @0x656b0c
CHIRI_SEQ = [('fm', DS_CHIRI, f, 1) for f in range(8, 16)] + [('exit',)]   # @0x66a870


# ---------------- 工具 ----------------
def _sfx(battle, sid: int) -> None:
    battle.engine._emit('sound_play', None, sid)


def _tile_center(tx: int, ty: int) -> tuple[int, int]:
    return (tx * TILE_W + TILE_W // 2) * FP, (ty * TILE_H + TILE_H // 2) * FP


def _caster_pos(caster) -> tuple[int, int]:
    ent = caster.entity
    x, y = _tile_center(caster.x, caster.y)
    return x + (ent.x if ent is not None else 0), y + (ent.y if ent is not None else 0)


def _rand(battle) -> int:
    """exe rand() 0..0x7fff."""
    return battle.rng.randrange(0x8000)


def _fx(bt, think_fn, x: int, y: int, z_px: int, seq, /, **ud) -> "Entity":
    battle = bt
    e = battle.engine.spawn(think_fn=think_fn)
    e.atlas_slot, e.frame_idx = seq[0][1], seq[0][2]
    e.flags |= 0x40
    e.x, e.y, e.z = x, y, -(z_px << 16)
    e.user_data.update(kind='hit_effect', projectile=True, **ud)
    battle.engine.attach_seq(e, tuple_to_bytecode(seq))
    return e


def _seq_end_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004d0dcf: seq 播完自毁 (火爆)."""
    if 'fx_end' in e.user_data and not e.is_playing():
        eng.destroy(e)


# ---------------- 命中 (-250) ----------------
def _spark(battle, caster, victim) -> None:
    """FUN_004d0c90(目标 x, y+400, z+448, 655c10[施法者朝向]) = ef010 方向刺爆."""
    from core.battle import combat
    from core.hit_effect_seq import (HitEffectSpec, facing_to_dir, UNIVERSAL_SPARK_ATLAS, UNIVERSAL_SPARK_BY_DIR,
                                     UNIVERSAL_SPARK_FRAME_TICKS, HIT_EFFECT_Y_BASELINE_PX)
    d = facing_to_dir(caster.facing)
    spec = HitEffectSpec(UNIVERSAL_SPARK_ATLAS, list(UNIVERSAL_SPARK_BY_DIR[d]), UNIVERSAL_SPARK_FRAME_TICKS, jittered=False)
    cx = victim.x * TILE_W + TILE_W // 2
    cy = victim.y * TILE_H + TILE_H // 2 - HIT_EFFECT_Y_BASELINE_PX
    combat._spawn_effect_entity(battle, cx, cy, spec)


def _chiri_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004e528c: 首次 think 挂 seq; 之后 x,y 匀速, z 加速度 0.8 朝 0 落, z < 392 自毁."""
    ud = e.user_data
    if 'chiri' not in ud:
        return
    e.x += ud['vx']
    e.y += ud['vy']
    ud['vz'] -= CHIRI_GRAVITY
    ud['ez'] += ud['vz']
    e.z = -ud['ez']
    if ud['ez'] < (CHIRI_Z_END << 16) + 1:
        eng.destroy(e)


def _chiri(battle, victim) -> None:
    """FUN_004e52de: 8 粒碎屑."""
    vx0, vy0 = _tile_center(victim.x, victim.y)
    for _ in range(CHIRI_COUNT):
        vx = _rand(battle) * 16 - 0x40000
        vy = _rand(battle) * 16 - 0x40000
        e = battle.engine.spawn(think_fn=_chiri_think)
        e.atlas_slot, e.frame_idx = DS_CHIRI, 8
        e.flags |= 0x40
        e.x, e.y = vx0, vy0 + (CHIRI_Y << 16)
        e.user_data.update(kind='hit_effect', projectile=True, chiri=True, vx=vx, vy=vy, vz=0, ez=CHIRI_Z << 16)
        e.z = -e.user_data['ez']
        # 实录 pao_2f: 出生当 tick 已挂 seq 且首帧只停 1 t, 物理也已走 1 步 (首帧 z 435) → 寿命 10
        battle.engine.attach_seq(e, tuple_to_bytecode(CHIRI_SEQ))
        _chiri_think(e, battle.engine)


def _ring_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004d661e: 半径各 +4+rand&3, 绕目标 (mode 2), seq 完自毁."""
    ud = e.user_data
    if 'ring' not in ud:
        return
    battle = ud['battle']
    ud['rx'] += 4 + (_rand(battle) & 3)
    ud['ry'] += 4 + (_rand(battle) & 3)
    _ring_place(e)
    if not e.is_playing():
        eng.destroy(e)


def _ring_place(e: "Entity") -> None:
    ud = e.user_data
    a = ud['phi'] / 65536 * 2 * math.pi
    e.x = ud['cx'] + int(math.sin(a) * FP) * ud['rx']
    e.y = ud['cy'] - int(math.cos(a) * FP) * ud['ry']


def _thunder_think(e: "Entity", eng: "Engine") -> None:
    """FUN_005088f1: 雷击播完 → 4 道雷环 (FUN_004d66cc), 自毁."""
    ud = e.user_data
    if 'thunder' not in ud or e.is_playing():
        return
    battle, victim = ud['battle'], ud['victim']
    cx, cy = _tile_center(victim.x, victim.y)
    ox, oy = victim.reaction_offset                 # FUN_004d66cc 以目标**当前**位置为中心 (受击 seq 正把他推开)
    cx, cy = cx + int(ox * FP), cy + int(oy * FP)
    phi = ((_rand(battle) & 0xff) << 16) >> 10
    for _ in range(4):
        r = _fx(battle, _ring_think, cx, cy, 0, RING_SEQ, ring=True, battle=battle, cx=cx, cy=cy, phi=phi & 0xffff,
                rx=0, ry=0)
        _ring_place(r)
        _ring_think(r, battle.engine)       # 实录 pao_32: 出生当 tick 已外扩一步 (雷环下标在雷击之后, 同 tick think)
        phi += 0x4000
    eng.destroy(e)


def _on_hit(battle, caster, victim, sid: int) -> None:
    """箭到达: -200 (红字) 再 -250 (各招附加 → 受击 + 刺爆 + 碎屑)."""
    from core.son_transform import _damage_only
    from core.battle import combat
    _damage_only(battle, caster, victim)
    cx, cy = _tile_center(victim.x, victim.y)
    if sid in (0x30, 0x31):
        x = cx + (((_rand(battle) % 12) - 6) << 16)
        _fx(battle, _seq_end_think, x, cy + (BURST_Y << 16), BURST_Z, FIRE00_SEQ if sid == 0x30 else FIRE01_SEQ,
            fx_end=True)
        _sfx(battle, SFX_FIRE_ARROW if sid == 0x30 else SFX_TRI_FIRE)
    elif sid == 0x32:
        _fx(battle, _thunder_think, cx, cy, 0, THUNDER_SEQ, thunder=True, battle=battle, victim=victim)
        _sfx(battle, SFX_THUNDER)
    combat.set_reaction(victim, "hit", None)
    _spark(battle, caster, victim)
    _chiri(battle, victim)


# ---------------- 箭 ----------------
def _cdbc2(e: "Entity") -> bool:
    ud = e.user_data
    for axis, v_key, t_key, bit in (('x', 'vx', 'tx', 0x10), ('y', 'vy', 'ty', 0x20)):
        if not ud['axes'] & bit:
            continue
        v, t = ud[v_key], ud[t_key]
        p = getattr(e, axis) + v
        if (v > 0 and p >= t) or (v < 0 and p <= t) or v == 0:
            p = t
            ud['axes'] &= ~bit
        setattr(e, axis, p)
    return ud['axes'] == 0


def _arrow_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'pao_arrow' not in ud or not _cdbc2(e):
        return
    coord = ud['coord']
    cd = coord.user_data
    cd['live'] -= 1
    cd['arrived'] += 1
    _sfx(cd['battle'], SFX_ARROW_HIT)
    _on_hit(cd['battle'], cd['caster'], ud['victim'], cd['sid'])
    eng.destroy(e)


def _ctrunc(a: int, b: int) -> int:
    """C 整数除法 (向 0 截断)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def _spawn_arrow(battle, coord, caster, victim, sid: int) -> None:
    """FUN_00507a8a."""
    x0, y0 = _caster_pos(caster)
    tx, ty = _tile_center(victim.x, victim.y)
    dx, dy = tx - x0, ty - y0
    if abs(dy) < abs(dx):
        vx = ARROW_VX * FP if dx >= 1 else -ARROW_VX * FP
        steps = max(1, abs(dx) >> 21)
        vy = _ctrunc(dy, steps)
        d = 2 if vx < 1 else 3
    else:
        steps = max(1, abs(dy) // (ARROW_VY * FP))
        vx = _ctrunc(dx, steps)
        vy = ARROW_VY * FP if dy >= 1 else -ARROW_VY * FP
        d = 0 if vy < 1 else 1
    seq = ARROW_SEQS[sid][d]
    e = battle.engine.spawn(think_fn=_arrow_think)
    e.atlas_slot, e.frame_idx = EOBJ, seq[0][2]
    e.flags |= 0x40
    e.x, e.y = x0 + vx, y0 + vy                  # FUN_004c3211 预走 1 步
    e.z = -(ARROW_Z << 16)
    e.user_data.update(kind='hit_effect', projectile=True, pao_arrow=True, coord=coord, victim=victim,
                       vx=vx, vy=vy, tx=tx, ty=ty, axes=0x30)
    battle.engine.attach_seq(e, tuple_to_bytecode(seq))
    coord.user_data['live'] += 1


# ---------------- 协调实体 (dispatcher 0x14 收尾) ----------------
def _coord_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'pao' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    if not ud['fired'] or ud['live'] > 0:
        return
    if getattr(battle, 'float_pending', 0) > 0:
        return
    if any(v.reaction_seq is not None for v in ud['victims']):
        return
    # 0x14 → 0x1e 停一拍才自毁, 施法者再下一拍回待机 (实录 pao_2f: 0x1e @77, 自毁 78, idle 79)
    ud['end_wait'] = ud.get('end_wait', 0) + 1
    if ud['end_wait'] <= END_DELAY:
        return
    caster.cast_hold = False
    ud['unit'] = caster
    eng._signal(e, SIG_END)
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
        if t is not None and t.alive:
            out.append(t)
    return out


def on_cast_signal(battle, caster, sig: int) -> bool:
    """施法 seq 的 PAO_SIG (= exe -100): 对每个目标发一支箭 + 播 200."""
    if sig != PAO_SIG:
        return False
    e = battle.engine.spawn(think_fn=_coord_think)
    e.flags = 0x800 | 0x10000
    sid = caster.pending_skill_id
    victims = _victims(battle, caster)
    e.user_data.update(kind='pao_coord', projectile=True, pao=True, battle=battle, caster=caster, sid=sid,
                       victims=victims, live=0, arrived=0, fired=False)
    for v in victims:
        _spawn_arrow(battle, e, caster, v, sid)
    e.user_data['fired'] = True
    _sfx(battle, SFX_SHOOT)
    return True
