"""猪八戒 5 技能 (skill 0x19..0x1d), 2026-10-23 按 exe 逆向 (reverse_engineering/pig_decomp.txt, pig_thinks_decomp.txt,
motion_decomp.txt). 资源: 施法姿 cjupa_g0 (fm 14) / cjupa_g2 (fm 16); 火球 ejupa00 (273); 星弹 ejupa02 (275);
猪弹+回血爆 ejupa03 (276); 火爆 fire02 (310).

共同 dispatcher 骨架 (FUN_00501f38 / 5025dc / 502ce3 / 503273 / 50399a):
  case 0: **无调色板渐变**, 直接挂施法 seq (施法者 0x10000 清 = 非待机); seq 每个 -100 发一颗弹 → state 0x14;
  弹 (FUN_004cdbc2 匀速, 越过目标即钳, 两轴都到 → 发 -200 + -250 自毁): -200 = 目标格火爆 FUN_004d0d7b
  (x = 格 x + rand%12-6, y = 格 y + 124, z = 172 + rand&15-8 → 画在格上方 48px), 火爆 seq 完发 -210;
  -250 = 每个目标 FUN_004c4f20 + 受击 seq 6557f0[dir] (**无命中特效**); -210 = 飘字 (回血白字 / 伤害红字);
  0x14 等弹/火爆/飘字计数归零且所有受击 seq 播完 (-10..-12 清位) → 0x1e FUN_004d0cd8(0) (没暗过即过) → 自毁.

逐技能:
  0x19 回復豬彈: seq 67439c[dir] 1 发. 猪弹 ejupa03 帧=dir, 上下 9 / 左右 12 px/t, 出生先走 2 步, 播 0x13a;
       到达播 0xaf. 火爆 seq 675138 (ejupa03 帧 4-7 各 2t). -210 → 目标回血白字.
  0x1a 火炎砲: seq 675464[dir] 2 发 (每发 -100 播 0x13a). 火球 seq 67442c[dir] (ejupa00 3 帧循环), 24/32 px/t, 先走 1 步.
       -250 播 0x13b ×2. 火爆 fire02 seq 656014 (帧 0-10 各 1t). 第 2 个 -210 → 全目标红字.
  0x1b 擴散火炎砲: seq 675474 (cjupa_g2, 不分方向) 12 发 (每发 -100 播 0x10a). 星弹 ejupa02 帧 0, 24/32 px/t,
       第 n 发飞向 施法者格 + 偏移表[n] (下 2/3/4, 右 2/3/4, 上, 左), 方向表 [1,1,1,3,3,3,0,0,0,2,2,2].
       -250 = 该格目标 受击 + **立即红字**; -200 火爆在该格; -210 不处理.
  0x1c 連續火炎砲: seq 675bc4[dir] 4 发, 同火炎砲; -200 播 0x13b; 第 4 个 -210 → 红字.
  0x1d 颱風火炎砲: seq 675bd4 (cjupa_g2) 开头播 0x10b, 36 发每 2t 一发, 末尾停 0x10b. 第 n 发 FUN_0050387e: 星弹 ejupa02 帧 0,
       环绕模式 0x32 (FUN_004c3211 mode 2: x = cx + sin φ·rx, y = cy - cos φ·ry, z 不动 = 施法者 z+48), 中心 = 施法者,
       φ = (0x19555 - (n%12)·0x10000/12) & 0xffff (12 方向, 0x10000 = 一圈), rx 64→每 t +32, ry 48→每 t +24, 半径 r = n/12+1 格:
       rx ≥ 64r+32 或 ry ≥ 48r+24 → 原地火爆 (seq 656014, z 48) 并自毁; 每个火爆完 -210 计数, 第 36 个 → 全目标 受击 + 红字.
实现: 施法 seq 的 -100 用专用信号 PIG_SIG (避免 tactics 当普攻 IMPACT 结算), tactics 经 skill_seq.SKILL_CAST_SIGNAL_HANDLERS
转到 on_cast_signal; 协调实体 (不渲染, projectile 门控) 计数并在收尾发 SIG_END (带 unit) → tactics.post_attack_anim.
数值 (伤害/回血量) 仍是我们的占位公式.
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
PIG_SIG = -1009                     # 施法 seq 里代替 exe -100 的专用信号
PIG_SKILLS = (0x19, 0x1a, 0x1b, 0x1c, 0x1d)

CJUPA_G0, CJUPA_G2 = 14, 16
EJUPA00, EJUPA02, EJUPA03, FIRE02 = 273, 275, 276, 310

SFX_SHOT = 0x13a                    # 猪弹/火球 发射
SFX_PIG_ARRIVE = 0xaf               # 猪弹到达
SFX_FIRE_HIT = 0x13b                # 火炎砲 -250 ×2 / 連續火炎砲 -200
SFX_SPREAD_SHOT = 0x10a             # 擴散火炎砲 每发
SFX_TYPHOON = 0x10b                 # 颱風火炎砲 (seq 内 play / stop)

PROJ_Z = 48                         # 弹 z = 施法者 z + 0x30
BURST_Y_OFF = 124                   # 火爆 y + 0x7c
BURST_Z = 172                       # 火爆 z 0xac ± 8
# exe 方向下标 (+0x110): 0 上 / 1 下 / 2 左 / 3 右 (= core.attack_seq.facing_to_atk_index)
PIG_SPEED = {0: (0, -9), 1: (0, 9), 2: (-12, 0), 3: (12, 0)}       # FUN_00501de3
FIRE_SPEED = {0: (0, -24), 1: (0, 24), 2: (-32, 0), 3: (32, 0)}    # FUN_005024ae / 502b9d
RECOIL = {0: (0, 1), 1: (0, -1), 2: (1, 0), 3: (-1, 0)}             # 施法 seq 后坐方向 (背离朝向)

# 擴散火炎砲 偏移表 / 方向表 (FUN_00502ce3 局部数组)
SPREAD_OFFSETS = [(0, 2), (0, 3), (0, 4), (2, 0), (3, 0), (4, 0), (0, -2), (0, -3), (0, -4), (-2, 0), (-3, 0), (-4, 0)]
SPREAD_DIRS = [1, 1, 1, 3, 3, 3, 0, 0, 0, 2, 2, 2]

TYPHOON_COUNT = 36
TYPHOON_RX0, TYPHOON_RY0 = 64, 48   # +0x190 / +0x194 初值
TYPHOON_DRX, TYPHOON_DRY = 32, 24   # 每 tick 增量


# ---------------- 施法 seq (exe 字节码逐 op 转录, 见 tools.verify_seqs) ----------------
def _shot(d: int, first_wait: int) -> list[tuple]:
    """cjupa_g0 一发: 帧 d*4+0 (wait) → 后坐 8 → 发射 → 帧 +1 后坐 4+2 → 帧 +2,+3 → 回位 14 → 帧 +0."""
    rx, ry = RECOIL[d]
    f = d * 4
    return [('fm', CJUPA_G0, f, first_wait), ('move', 8 * rx, 8 * ry, 0), ('jump', PIG_SIG),
            ('fm', CJUPA_G0, f + 1, 3), ('move', 4 * rx, 4 * ry, 2), ('move', 2 * rx, 2 * ry, 1),
            ('fm', CJUPA_G0, f + 2, 3), ('fm', CJUPA_G0, f + 3, 3), ('move', -14 * rx, -14 * ry, 0),
            ('fm', CJUPA_G0, f, 0)]


def _shots(waits: list[int]) -> list[list[tuple]]:
    return [sum((_shot(d, w) for w in waits), []) + [('exit',)] for d in range(4)]


def _spread_seq() -> list[tuple]:
    """seq 0x675474 (cjupa_g2 不分方向): 4 组 × 3 发, 每组首帧停 10t (首组 3t)."""
    out: list[tuple] = []
    groups = [(10, 3, (11, 12), (13, 14), (15, 16)), (28, 10, (29, 30), (31, 32), (33, 34)),
              (1, 10, (2, 3), (4, 5), (6, 7)), (19, 10, (20, 21), (22, 23), (24, 25))]
    for first, wait, *pairs in groups:
        out.append(('fm', CJUPA_G2, first, wait))
        for a, b in pairs:
            out += [('jump', PIG_SIG), ('fm', CJUPA_G2, a, 3), ('fm', CJUPA_G2, b, 3)]
    return out + [('fm', CJUPA_G2, 26, 3), ('fm', CJUPA_G2, 9, 15), ('exit',)]


def _typhoon_seq() -> list[tuple]:
    """seq 0x675bd4: 帧 9 停 15t + 播 0x10b, 36 发每 2t (12 帧循环 ×3), 停 0x10b, 帧 9 停 15t."""
    ring = [11, 13, 15, 29, 31, 33, 2, 4, 6, 20, 22, 24]
    out: list[tuple] = [('fm', CJUPA_G2, 9, 15), ('sound', SFX_TYPHOON, 0x0411)]
    for _ in range(3):
        for f in ring:
            out += [('jump', PIG_SIG), ('fm', CJUPA_G2, f, 2)]
    return out + [('sound', SFX_TYPHOON, 0x0412), ('fm', CJUPA_G2, 9, 15), ('exit',)]


SKILL_PIG_HEAL = _shots([12])                    # 0x19 @0x67439c
SKILL_PIG_FIRE = _shots([12, 12])                # 0x1a @0x675464
SKILL_PIG_SPREAD = [_spread_seq()] * 4           # 0x1b @0x675474
SKILL_PIG_CONTINUOUS = _shots([12, 5, 5, 5])     # 0x1c @0x675bc4
SKILL_PIG_TYPHOON = [_typhoon_seq()] * 4         # 0x1d @0x675bd4
PIG_SEQS = {0x19: SKILL_PIG_HEAL, 0x1a: SKILL_PIG_FIRE, 0x1b: SKILL_PIG_SPREAD,
            0x1c: SKILL_PIG_CONTINUOUS, 0x1d: SKILL_PIG_TYPHOON}
SHOTS = {0x19: 1, 0x1a: 2, 0x1b: 12, 0x1c: 4, 0x1d: TYPHOON_COUNT}
FLOAT_AT_BURST = {0x1a: 2, 0x1c: 4, 0x1d: TYPHOON_COUNT}    # 第 N 个 -210 才飘字

FIRE_BALL_SEQS = [[('fm', EJUPA00, f, 1) for f in fr] + [('loop',)]          # @0x67442c[dir]
                  for fr in ((6, 7, 8), (9, 10, 11), (0, 1, 2), (3, 4, 5))]
PIG_BURST_SEQ = [('fm', EJUPA03, f, 2) for f in (4, 5, 6, 7)] + [('exit',)]   # @0x675138
FIRE_BURST_SEQ = [('fm', FIRE02, f, 1) for f in range(11)] + [('exit',)]     # @0x656014


# ---------------- 工具 ----------------
def _sfx(battle, sid: int) -> None:
    battle.engine._emit('sound_play', None, sid)


def _tile_center(tx: int, ty: int) -> tuple[int, int]:
    return (tx * TILE_W + TILE_W // 2) * FP, (ty * TILE_H + TILE_H // 2) * FP


def _caster_pos(caster) -> tuple[int, int]:
    """施法者当前世界坐标 (exe +0x8/+0xc: 含 seq move 的后坐偏移)."""
    ent = caster.entity
    x, y = _tile_center(caster.x, caster.y)
    return x + (ent.x if ent is not None else 0), y + (ent.y if ent is not None else 0)


def _targets(battle, caster) -> list:
    """dispatcher 目标表 DAT_00869c48: 范围内的敌人 (回復豬彈 = 队友)."""
    heal = caster.pending_skill_id == 0x19
    out = []
    tiles = getattr(battle, '_pending_damage_range', None)
    if tiles:
        for (x, y) in tiles:
            t = battle.q.occupant(x, y)
            if t is not None and t.alive and (t.is_player == caster.is_player) == heal:
                out.append(t)
    else:
        t = caster.pending_attack_target
        if t is not None and t.alive:
            out.append(t)
    return out


def _react(battle, caster, victims) -> None:
    """-250: 受击 seq (不转向, 无特效)."""
    from core.jah_skills import _hit
    for v in victims:
        _hit(battle, caster, v, fx=None)


def _damage(battle, caster, victims) -> None:
    from core.son_transform import _damage_only
    for v in victims:
        _damage_only(battle, caster, v)


def _heal(battle, caster, victims) -> None:
    """-210 (回復豬彈): 每个目标回血白字 (FUN_004d074e)."""
    from core.battle.combat import push_damage_event
    from core.battle.data import DamageEvent
    from core.skill_seq import heal_amount
    amt = heal_amount(caster, 0x19)
    for t in victims:
        if not t.alive:
            continue
        before = t.hp
        t.hp = min(t.max_hp, t.hp + amt)
        push_damage_event(battle, t, DamageEvent(t.hp - before, t.hp, t.x, t.y, heal=True))
        battle._log(f"{caster.name} → {t.name}: 回复 {t.hp - before} HP ({t.hp}/{t.max_hp})")


# ---------------- 协调实体 (= dispatcher 计数 + 0x14 收尾判定) ----------------
def _coord_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'pig' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    if ud['fired'] < ud['shots'] or ud['live'] > 0:
        return
    if getattr(battle, 'float_pending', 0) > 0:
        return
    if any(v.reaction_seq is not None for v in ud['victims']):
        return
    caster.cast_hold = False
    ud['unit'] = caster
    eng._signal(e, SIG_END)
    eng.destroy(e)


def _spawn_coord(battle, caster) -> "Entity":
    sid = caster.pending_skill_id
    e = battle.engine.spawn(think_fn=_coord_think)
    e.flags = 0x800 | 0x10000
    e.user_data.update(kind='pig_coord', projectile=True, pig=True, battle=battle, caster=caster, sid=sid,
                       victims=_targets(battle, caster), shots=SHOTS[sid], fired=0, live=0, bursts_done=0)
    return e


# ---------------- 火爆 ----------------
def _burst_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'burst' not in ud or e.is_playing():
        return
    coord = ud['coord']
    cd = coord.user_data
    cd['live'] -= 1
    _on_burst_done(cd)                       # -210
    eng.destroy(e)


def _on_burst_done(cd: dict) -> None:
    battle, caster, sid = cd['battle'], cd['caster'], cd['sid']
    cd['bursts_done'] += 1
    if sid == 0x19:
        _heal(battle, caster, cd['victims'])
    elif sid in FLOAT_AT_BURST and cd['bursts_done'] == FLOAT_AT_BURST[sid]:
        if sid == 0x1d:
            _react(battle, caster, cd['victims'])
        _damage(battle, caster, cd['victims'])


def _spawn_burst(battle, coord, x: int, y: int, z_px: int, seq) -> None:
    b = battle.engine.spawn(think_fn=_burst_think)
    b.atlas_slot, b.frame_idx = seq[0][1], seq[0][2]
    b.flags |= 0x40
    b.x, b.y, b.z = x, y, -(z_px << 16)
    b.user_data.update(kind='hit_effect', projectile=True, burst=True, coord=coord)
    coord.user_data['live'] += 1
    battle.engine.attach_seq(b, tuple_to_bytecode(seq))


def _spawn_tile_burst(battle, coord, tile: tuple[int, int], seq) -> None:
    """FUN_004d0d7b 在目标格: x ± rand%12-6, y + 124, z 172 ± 8 (exe 先取 z 的随机, 再取 x 的)."""
    rng = battle.rng
    z = BURST_Z + (rng.randrange(16) - 8)
    tx, ty = _tile_center(*tile)
    x = tx + ((rng.randrange(1 << 15) % 12 - 6) << 16)
    _spawn_burst(battle, coord, x, ty + (BURST_Y_OFF << 16), z, seq)


# ---------------- 直线弹 (FUN_004cdbc2) ----------------
def _cdbc2(e: "Entity") -> bool:
    """匀速朝目标, 越过即钳并清该轴位; 速度 0 的轴首步直接钳到目标. 返回是否两轴都到."""
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


def _proj_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'pig_proj' not in ud:
        return
    if not _cdbc2(e):
        return
    coord = ud['coord']
    cd = coord.user_data
    battle, caster, sid = cd['battle'], cd['caster'], cd['sid']
    cd['live'] -= 1
    if sid == 0x19:
        _sfx(battle, SFX_PIG_ARRIVE)
    # -200: 目标格火爆
    if sid == 0x1c:
        _sfx(battle, SFX_FIRE_HIT)
    _spawn_tile_burst(battle, coord, ud['tile'], PIG_BURST_SEQ if sid == 0x19 else FIRE_BURST_SEQ)
    # -250
    if sid == 0x1b:
        hit = [v for v in cd['victims'] if (v.x, v.y) == ud['tile']]
        _react(battle, caster, hit)
        _damage(battle, caster, hit)
    else:
        if sid == 0x1a:
            _sfx(battle, SFX_FIRE_HIT)
            _sfx(battle, SFX_FIRE_HIT)
        _react(battle, caster, cd['victims'])
    eng.destroy(e)


def _spawn_line_proj(battle, coord, caster, d: int, tile: tuple[int, int], speed: dict, pre_steps: int) -> "Entity":
    vx, vy = speed[d]
    e = battle.engine.spawn(think_fn=_proj_think)
    e.flags |= 0x40
    e.x, e.y = _caster_pos(caster)
    e.z = -(PROJ_Z << 16)
    tx, ty = _tile_center(*tile)
    e.user_data.update(kind='hit_effect', projectile=True, pig_proj=True, coord=coord, tile=tile,
                       vx=vx * FP, vy=vy * FP, tx=tx, ty=ty, axes=0x30)
    for _ in range(pre_steps):               # FUN_004c3211 预走 (加速度 0 = 匀速, 不钳)
        e.x += e.user_data['vx']
        e.y += e.user_data['vy']
    coord.user_data['live'] += 1
    return e


# ---------------- 颱風火炎砲 环绕弹 (FUN_005037ce, FUN_004c3211 mode 2) ----------------
def _orbit_place(e: "Entity") -> None:
    ud = e.user_data
    a = ud['phi'] / 65536 * 2 * math.pi
    e.x = ud['cx'] + int(math.sin(a) * FP) * ud['rx']
    e.y = ud['cy'] - int(math.cos(a) * FP) * ud['ry']


def _orbit_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'pig_orbit' not in ud:
        return
    ud['rx'] += TYPHOON_DRX
    ud['ry'] += TYPHOON_DRY
    _orbit_place(e)
    if ud['rx'] >= ud['rx_end'] or ud['ry'] >= ud['ry_end']:
        coord = ud['coord']
        coord.user_data['live'] -= 1
        _spawn_burst(coord.user_data['battle'], coord, e.x, e.y, PROJ_Z, FIRE_BURST_SEQ)
        eng.destroy(e)


def _spawn_orbit(battle, coord, caster, n: int) -> None:
    r = n // 12 + 1
    e = battle.engine.spawn(think_fn=_orbit_think)
    e.atlas_slot, e.frame_idx = EJUPA02, 0
    e.flags |= 0x40
    cx, cy = _caster_pos(caster)
    e.z = -(PROJ_Z << 16)
    e.user_data.update(kind='hit_effect', projectile=True, pig_orbit=True, coord=coord, cx=cx, cy=cy,
                       phi=(0x19555 - ((n % 12) << 16) // 12) & 0xffff, rx=TYPHOON_RX0, ry=TYPHOON_RY0,
                       rx_end=r * TILE_W + TILE_W // 2, ry_end=r * TILE_H + TILE_H // 2)
    _orbit_place(e)                          # 出生调一次 FUN_004c3211
    coord.user_data['live'] += 1


# ---------------- 施法 seq 信号入口 (exe -100) ----------------
def on_cast_signal(battle, caster, sig: int) -> bool:
    """tactics 把施法者 seq 的 PIG_SIG 转到这里: 每次发一颗弹. 返回 True = 已处理."""
    if sig != PIG_SIG:
        return False
    from core.attack_seq import facing_to_atk_index
    ent = caster.entity
    coord = ent.user_data.get('pig_coord')
    if coord is None:
        coord = _spawn_coord(battle, caster)
        ent.user_data['pig_coord'] = coord
    cd = coord.user_data
    sid = cd['sid']
    n = cd['fired']
    cd['fired'] += 1
    d = facing_to_atk_index(caster.facing)
    cursor = caster.pending_attack_cursor or (caster.x, caster.y)
    if sid == 0x19:
        p = _spawn_line_proj(battle, coord, caster, d, cursor, PIG_SPEED, 2)
        p.atlas_slot, p.frame_idx = EJUPA03, d
        _sfx(battle, SFX_SHOT)
    elif sid in (0x1a, 0x1c):
        _sfx(battle, SFX_SHOT)
        p = _spawn_line_proj(battle, coord, caster, d, cursor, FIRE_SPEED, 1)
        p.atlas_slot, p.frame_idx = EJUPA00, FIRE_BALL_SEQS[d][0][2]
        battle.engine.attach_seq(p, tuple_to_bytecode(FIRE_BALL_SEQS[d]))
    elif sid == 0x1b:
        _sfx(battle, SFX_SPREAD_SHOT)
        ox, oy = SPREAD_OFFSETS[n]
        p = _spawn_line_proj(battle, coord, caster, SPREAD_DIRS[n], (caster.x + ox, caster.y + oy), FIRE_SPEED, 1)
        p.atlas_slot, p.frame_idx = EJUPA02, 0
    elif sid == 0x1d:
        _spawn_orbit(battle, coord, caster, n)
    return True
