"""远程普攻 (八戒 24-31 / 破无 64-71 / 捕山 72-79) + 紫河第三形态 90, 2026-10-25 按 exe 逆向
(reverse_engineering/ranged_attack_decomp.txt, ranged_thinks_decomp.txt, pig_aoe_decomp.txt, pig_balls_decomp.txt).

各处理函数 (普攻表 @0x68ab90 的 fn) 都是 dispatcher: case 0 挂施法 seq, seq 的 -100 = 出手, -150 = 还有目标就重挂 (逐个射),
-110 = 结束 (只 八戒 4e53a7 / 紫河 90 用), -105 = 紫河 90 抛起. 我们把这些信号换成专用的 (RA_*), 走 on_signal.
命中三件套: 受击 seq 6557f0[目标朝向] (FUN_004c4f20 + 438d40), 方向刺爆 655c10[施法者朝向] (pao_skills._spark),
碎屑 FUN_004e52de ×8 (pao_skills._chiri); 飘字 FUN_004d05d8 (= son_transform._damage_only).

  八戒 24/28/29 (FUN_004ff407 / 4ff950 / 4ffe5a): 施法 67439c[dir], -100 → 0x13a + 火球 FUN_004ff2d6 飞向光标格
      (seq 67442c[dir], z+48, 朝向轴速度 8/6 · 16/12 · 32/24 px/t, 另一轴首 tick 吸附), 到达 → 首目标 -200 飘字 + -250:
      受击 + 刺爆 + 火爆 (x±6, y+24, z 72±8; 24/28 fire02 656014 / 29 fire01 655fa4) + 0x13b (29 两次).
  八戒 25-27 (FUN_004e53a7, seq 6747dc / 674f5c): 每个 -100 → 全目标 受击 (面向施法者) + 刺爆 + 碎屑; -110 → 全目标飘字.
  八戒 30 (FUN_00500682): 火球 FUN_0050055d (seq 674fec[dir], 朝向轴加速 0x3333/0x2666, 速度 ≤4 px/t 时每 t 身后 32px
      冒烟 674ffc 上升, 否则加速度翻倍), 到达 → -250: 0x13b×2, 光标格大火爆 fire01 + 四邻 fire02 (y+124, z 172±8),
      全目标受击 + 刺爆; -200 全目标飘字.
  八戒 31 (FUN_00500f26): 施法 67511c[dir], 火球 FUN_00500e0d (seq 67512c, 24/32 px/t), 到达 -250: 大火爆 →(完)→ 全目标受击
      + 四邻 fire02 (z48) →(4 个都完)→ 受击 + 四邻各 ±32px 4 个 fire03 656084 (16 个) →(都完)→ 全目标飘字.
  破无 64-71 (FUN_00507ca3): 施法 6780bc[dir], -100 → 200 + 箭 FUN_00507a8a (32/24 px/t, z+32) 射下一个目标,
      -150 → 还有目标则重挂 67823c[dir]; 箭到 → 0xbf, -200 飘字, -250 受击 + 刺爆 + 碎屑. 箭 seq 表: 677c8c 普通 /
      677e3c 古箭 / 677ecc 破無之箭·魔法箭.
  捕山 72-74 (FUN_005095a1(n)): 施法 67895c, -100 → 0x109, 全目标 飘字 + 受击 + 刺爆 + n×碎屑, 0x109 0xbd 0x109.
  捕山 75/76/78/79 (FUN_0050995d(n)): 施法 678b4c, -100 → 下一个目标 飘字 + 受击 + 刺爆 + n×碎屑, 0x109 0xbf;
      -150 → 还有目标则重挂 678d1c.
  捕山 77 雷射槍 (FUN_00509fed): 施法 678e1c, -100 → 0x14c + 光弹 FUN_00509dd3 (seq 678f0c[dir], 同箭速) 射下一个,
      -150 → 重挂 678ecc; 光弹到 → -200 飘字, -250 受击 + 刺爆 + 碎屑 + 0xbd.
  紫河 90 (FUN_0050fef1): 施法 67a7e4[dir] (跳扑). 每个 -100: 命中者 受击 (面向) + 三爪 655d30[目标朝向] (抖动) + 刺爆 +
      0x105, 闪避者 躲闪 seq 655960; -105: 命中者被抛起 (FUN_0050fe1c: vz 48 每 t -2, 0xf4), 落地 0xf0 → 再受击 +
      紫星 655b18 + 刺爆 + 飘字; -110: 施法者回格.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.anim_engine.bytecode import tuple_to_bytecode
from core.anim_engine.entity import SIG_END
from core.normal_attack_data import SEQ_TABLES, SEQS
from core.sprites.base import TILE_W, TILE_H

if TYPE_CHECKING:
    from core.anim_engine.engine import Engine
    from core.anim_engine.entity import Entity

FP = 1 << 16
RA_HIT, RA_RECAST, RA_END, RA_TOSS = -1016, -1017, -1018, -1019     # 代替 exe -100 / -150 / -110 / -105
_SIG_MAP = {-100: RA_HIT, -150: RA_RECAST, -110: RA_END, -105: RA_TOSS}

# 普攻 idx → (类型, 参数)
KINDS: dict[int, tuple] = {
    24: ('pig_ball', (8, 6, 0x656014, 1)), 28: ('pig_ball', (16, 12, 0x656014, 1)),
    29: ('pig_ball', (32, 24, 0x655fa4, 2)),
    25: ('pig_hitscan', 0x6747dc), 26: ('pig_hitscan', 0x674f5c), 27: ('pig_hitscan', 0x674f5c),
    30: ('pig_aoe5', None), 31: ('pig_aoe16', None),
    **{i: ('pao', 0x677c8c) for i in (64, 65, 66, 68, 69)}, 67: ('pao', 0x677e3c), 70: ('pao', 0x677ecc),
    71: ('pao', 0x677ecc),
    72: ('bosan_multi', 1), 73: ('bosan_multi', 2), 74: ('bosan_multi', 3),
    75: ('bosan_seq', 1), 76: ('bosan_seq', 2), 78: ('bosan_seq', 1), 79: ('bosan_seq', 2),
    77: ('bosan_laser', None),
    90: ('zihe3', None),
}
CAST_TABLE = {'pig_ball': 0x67439c, 'pig_aoe5': 0x67439c, 'pig_aoe16': 0x67511c, 'pao': 0x6780bc,
              'bosan_multi': 0x67895c, 'bosan_seq': 0x678b4c, 'bosan_laser': 0x678e1c, 'zihe3': 0x67a7e4}
RECAST_TABLE = {'pao': 0x67823c, 'bosan_seq': 0x678d1c, 'bosan_laser': 0x678ecc}

SFX_PIG_SHOT, SFX_PIG_HIT = 0x13a, 0x13b
SFX_ARROW, SFX_ARROW_HIT = 200, 0xbf
SFX_GUN, SFX_LASER = 0x109, 0x14c
SFX_ZIHE_HIT, SFX_TOSS, SFX_LAND = 0x105, 0xf4, 0xf0


def _sfx(battle, sid: int) -> None:
    battle.engine._emit('sound_play', None, sid)


def _rand(battle) -> int:
    return battle.rng.randrange(0x8000)


def _remap(seq: list[tuple]) -> list[tuple]:
    return [('jump', _SIG_MAP[t[1]]) if t[0] == 'jump' and t[1] in _SIG_MAP else t for t in seq]


def handles(idx: int | None) -> bool:
    return idx in KINDS


def cast_seq(idx: int, facing: tuple[int, int]) -> list[tuple]:
    from core.attack_seq import facing_to_atk_index
    kind, arg = KINDS[idx]
    table = arg if kind == 'pig_hitscan' else CAST_TABLE[kind]
    return _remap(SEQ_TABLES[table][facing_to_atk_index(facing)])


def _dir(u) -> int:
    from core.attack_seq import facing_to_atk_index
    return facing_to_atk_index(u.facing)


def _tile_center(tx: int, ty: int) -> tuple[int, int]:
    return (tx * TILE_W + TILE_W // 2) * FP, (ty * TILE_H + TILE_H // 2) * FP


def _pos(u) -> tuple[int, int]:
    x, y = _tile_center(u.x, u.y)
    ent = u.entity
    if ent is not None:
        x += ent.x
        y += ent.y
    return x, y


def _fx(battle, think, x, y, z_px_fp, seq, /, **ud) -> "Entity":
    e = battle.engine.spawn(think_fn=think)
    e.flags |= 0x40
    e.x, e.y = x, y
    e.user_data.update(kind='hit_effect', projectile=True, ez=z_px_fp, **ud)
    e.z = -z_px_fp
    if seq:
        e.atlas_slot, e.frame_idx = seq[0][1], seq[0][2]
        battle.engine.attach_seq(e, tuple_to_bytecode(seq))
    return e


# ---------------- 协调实体 ----------------
def _coord_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'ra' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    if not ud['released'] or ud['live'] > 0 or getattr(battle, 'float_pending', 0) > 0:
        return
    if any(v.reaction_seq is not None for v in ud['targets']):
        return
    ud['unit'] = caster
    caster.ra_coord = None
    eng._signal(e, SIG_END)
    eng.destroy(e)


def _victims(battle, caster) -> list:
    tiles = getattr(battle, '_pending_damage_range', None)
    out = []
    cand = sorted(tiles, key=lambda t: (t[1], t[0])) if tiles else []
    if not cand and caster.pending_attack_target is not None:
        t = caster.pending_attack_target
        cand = [(t.x, t.y)]
    for (x, y) in cand:
        o = battle.q.occupant(x, y)
        if o is not None and o.alive and o.is_player != caster.is_player and o not in out:
            out.append(o)
    return out


def on_attach(battle, caster) -> None:
    """begin_attack 挂上施法 seq 的同一刻: 建协调实体 (计数归零 + 受击/飘字播完 → SIG_END 收尾)."""
    idx = caster.attack_cur
    kind, arg = KINDS[idx]
    coord = battle.engine.spawn(think_fn=_coord_think)
    coord.flags = 0x800 | 0x10000
    coord.user_data.update(kind='ra_coord', projectile=True, ra=True, battle=battle, caster=caster, idx=idx,
                           atk_kind=kind, arg=arg, targets=_victims(battle, caster), live=0, n=0, released=False,
                           cursor=caster.pending_attack_cursor, stage=0)
    caster.ra_coord = coord


def _done(coord, k: int = 1) -> None:
    coord.user_data['live'] -= k


# ---------------- 命中件 ----------------
def _hit(battle, caster, v, *, face: bool = False, spark: bool = True, chiri: int = 0, birth: bool = True) -> None:
    from core.battle import combat
    from core.pao_skills import _spark, _chiri
    if not v.alive:
        return
    combat.set_reaction(v, "hit", caster if face else None)
    if spark:
        _spark(battle, caster, v)
    for _ in range(chiri):
        _chiri(battle, v, birth)


def _float(battle, caster, v) -> None:
    from core.son_transform import _damage_only
    _damage_only(battle, caster, v)


def _burst_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'burst' in ud and not e.is_playing():
        cb = ud.get('on_done')
        if cb is not None:
            cb()
        eng.destroy(e)


def _burst(battle, x, y, z, seq_addr, on_done=None) -> "Entity":
    return _fx(battle, _burst_think, x, y, z, SEQS[seq_addr], burst=True, on_done=on_done)


def _burst_at_target(battle, coord, v, seq_addr) -> None:
    """FUN_004d0d7b(x + rand%12-6, y+24, z 72±8, seq): 播完 -260 计数."""
    from core.pao_skills import hit_pos
    hx, hy = hit_pos(v)
    z = 0x480000 + (((_rand(battle) & 15) - 8) << 16)
    x = hx + (((_rand(battle) % 12) - 6) << 16)
    coord.user_data['live'] += 1
    _burst(battle, x, hy + 0x180000, z, seq_addr, on_done=lambda: _done(coord))


def _burst_tile(battle, coord, tx, ty, seq_addr, *, high: bool, jitter_x: bool = True, dx=0, dy=0, on_done=None):
    """格中心 (+dx/dy px) 火爆. high: y+124 z172±8 (画在格上方 48px), 否则 z48."""
    x, y = _tile_center(tx, ty)
    x += dx * FP
    y += dy * FP
    if high:
        z = 0xac0000 + (((_rand(battle) & 15) - 8) << 16)
        y += 0x7c0000
    else:
        z = 0x300000
    if jitter_x:
        x += ((_rand(battle) % 12) - 6) << 16
    coord.user_data['live'] += 1
    _burst(battle, x, y, z, seq_addr, on_done=on_done)


# ---------------- 弹 (FUN_004cdbc2 匀速/加速, 越过即钳) ----------------
def _move_axes(e: "Entity") -> bool:
    ud = e.user_data
    pos = [e.x, e.y]
    for i, (bit, v, a, t) in enumerate(((0x10, 'vx', 'ax', 'tx'), (0x20, 'vy', 'ay', 'ty'))):
        if not ud['axes'] & bit:
            continue
        ud[v] += ud[a] if pos[i] < ud[t] else -ud[a]
        pos[i] += ud[v]
        vv = ud[v]
        if (vv > 0 and pos[i] >= ud[t]) or (vv < 0 and pos[i] <= ud[t]) or vv == 0:
            ud['axes'] &= ~bit
            pos[i] = ud[t]
    e.x, e.y = pos
    return ud['axes'] == 0


def _proj_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'ra_proj' not in ud:
        return
    arrived = _move_axes(e)
    if ud.get('accel_trail'):                  # 八戒 30: FUN_00500499 先积分, 再按新速度判冒烟, 最后判到达
        if abs(ud['vx']) <= 0x40000 and abs(ud['vy']) <= 0x40000:
            _smoke(ud['battle'], e)
        else:
            ud['ax'] <<= 1
            ud['ay'] <<= 1
    if arrived:
        ud['on_arrive']()
        eng.destroy(e)


def _smoke_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'smoke' not in ud:
        return
    ud['ez'] += FP
    e.z = -ud['ez']
    if not e.is_playing():
        eng.destroy(e)


def _smoke(battle, ball: "Entity") -> None:
    """FUN_005003ae: 弹身后 32px 冒烟 (674ffc), z 每 t +1."""
    d = ball.user_data['d']
    off = {0: (0, 32), 1: (0, -32), 2: (32, 0), 3: (-32, 0)}[d]
    _fx(battle, _smoke_think, ball.x + off[0] * FP, ball.y + off[1] * FP, ball.user_data['ez'], SEQS[0x674ffc],
        smoke=True)


def _spawn_ball(battle, coord, caster, seq, *, speed=None, accel=None, accel_trail=False, on_arrive) -> None:
    """FUN_004ff2d6 / 50055d / 500e0d: 施法者处 z+48 飞向光标格中心; 只给朝向轴速度 (另一轴首 tick 吸附)."""
    cx, cy = coord.user_data['cursor']
    tx, ty = _tile_center(cx, cy)
    x0, y0 = _pos(caster)
    d = _dir(caster)
    vx = vy = ax = ay = 0
    if speed is not None:
        h, v = speed
        vy = {0: -v, 1: v}.get(d, 0) * FP
        vx = {2: -h, 3: h}.get(d, 0) * FP
    if accel is not None:
        ay = accel[1] if d in (0, 1) else 0
        ax = accel[0] if d in (2, 3) else 0
    e = _fx(battle, _proj_think, x0, y0, 0x300000, seq, ra_proj=True, battle=battle, d=d, vx=vx, vy=vy, ax=ax, ay=ay,
            tx=tx, ty=ty, axes=0x30, accel_trail=accel_trail, on_arrive=on_arrive)
    coord.user_data['live'] += 1
    e.user_data['on_arrive'] = lambda: (_done(coord), on_arrive())


def _ctrunc(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def _spawn_shot(battle, coord, caster, victim, seq_table, on_arrive) -> None:
    """FUN_00507a8a / 509dd3: 箭/光弹 32/24 px/t 直飞目标格, z+32, 首帧已走 1 步."""
    x0, y0 = _pos(caster)
    tx, ty = _tile_center(victim.x, victim.y)
    dx, dy = tx - x0, ty - y0
    if abs(dy) < abs(dx):
        vx = 0x200000 if dx >= 1 else -0x200000
        vy = _ctrunc(dy, max(1, abs(dx) >> 21))
        d = 2 if vx < 1 else 3
    else:
        vx = _ctrunc(dx, max(1, abs(dy) // 0x180000))
        vy = 0x180000 if dy >= 1 else -0x180000
        d = 0 if vy < 1 else 1
    seq = SEQ_TABLES[seq_table][d]
    e = _fx(battle, _proj_think, x0 + vx, y0 + vy, 0x200000, seq, ra_proj=True, battle=battle, d=d, vx=vx, vy=vy,
            ax=0, ay=0, tx=tx, ty=ty, axes=0x30)
    coord.user_data['live'] += 1
    e.user_data['on_arrive'] = lambda: (_done(coord), on_arrive())


# ---------------- 信号 ----------------
def on_signal(battle, caster, sig: int) -> bool:
    coord = getattr(caster, 'ra_coord', None)
    if coord is None or sig not in (RA_HIT, RA_RECAST, RA_END, RA_TOSS):
        return False
    ud = coord.user_data
    kind, arg, targets = ud['atk_kind'], ud['arg'], ud['targets']
    if sig == RA_HIT:
        HIT_HANDLERS[kind](battle, caster, coord)
    elif sig == RA_RECAST:
        if ud['n'] < len(targets):
            from core.attack_seq import facing_to_atk_index
            seq = _remap(SEQ_TABLES[RECAST_TABLE[kind]][facing_to_atk_index(caster.facing)])
            battle.engine.attach_seq(caster.entity, tuple_to_bytecode(seq))
        else:
            ud['released'] = True
    elif sig == RA_END:
        if kind == 'pig_hitscan':
            for v in targets:
                _float(battle, caster, v)
        elif kind == 'zihe3':
            pass                                        # 施法者回格 (我们的单位一直在格上)
        ud['released'] = True
    elif sig == RA_TOSS and kind == 'zihe3':
        _zihe_toss(battle, caster, coord)
    return True


def _pig_ball_hit(battle, caster, coord) -> None:
    ud = coord.user_data
    h, v, burst, n_sfx = ud['arg']
    _sfx(battle, SFX_PIG_SHOT)
    targets = ud['targets']

    def arrive():
        if targets:
            t0 = targets[0]
            _float(battle, caster, t0)
            _hit(battle, caster, t0)
            _burst_at_target(battle, coord, t0, burst)
            for _ in range(n_sfx):
                _sfx(battle, SFX_PIG_HIT)
        ud['released'] = True
    from core.attack_seq import facing_to_atk_index
    _spawn_ball(battle, coord, caster, SEQ_TABLES[0x67442c][facing_to_atk_index(caster.facing)], speed=(h, v),
                on_arrive=arrive)


def _pig_hitscan_hit(battle, caster, coord) -> None:
    from core.pao_skills import _chiri
    for v in coord.user_data['targets']:
        _hit(battle, caster, v, face=True)
        _chiri(battle, v, False)


def _pig_aoe5_hit(battle, caster, coord) -> None:
    ud = coord.user_data
    _sfx(battle, SFX_PIG_SHOT)

    def arrive():
        _sfx(battle, SFX_PIG_HIT)
        _sfx(battle, SFX_PIG_HIT)
        cx, cy = ud['cursor']
        _burst_tile(battle, coord, cx, cy, 0x655fa4, high=True, on_done=lambda: _done(coord))
        for ddx, ddy in ((-1, 0), (0, -1), (1, 0), (0, 1)):
            _burst_tile(battle, coord, cx + ddx, cy + ddy, 0x656014, high=True, on_done=lambda: _done(coord))
        for v in ud['targets']:
            _hit(battle, caster, v)
        for v in ud['targets']:                          # 同时到的 -200
            _float(battle, caster, v)
        ud['released'] = True
    from core.attack_seq import facing_to_atk_index
    _spawn_ball(battle, coord, caster, SEQ_TABLES[0x674fec][facing_to_atk_index(caster.facing)],
                speed=(0, 0), accel=(0x3333, 0x2666), accel_trail=True, on_arrive=arrive)


def _pig_aoe16_hit(battle, caster, coord) -> None:
    ud = coord.user_data
    _sfx(battle, SFX_PIG_SHOT)
    cx, cy = ud['cursor']
    targets = ud['targets']

    def hit_all():
        for v in targets:
            _hit(battle, caster, v)
        _sfx(battle, SFX_PIG_HIT)

    def stage(n, total, nxt):
        ud['stage_left'] = ud.get('stage_left', 0) - 1
        _done(coord)
        if ud['stage_left'] == 0:
            nxt()

    def stage3():
        hit_all()
        ud['stage_left'] = 16
        for ddx, ddy in ((-1, 0), (0, -1), (1, 0), (0, 1)):
            for ox, oy in ((32, 0), (0, 32), (-32, 0), (0, -32)):
                _burst_tile(battle, coord, cx + ddx, cy + ddy, 0x656084, high=False, jitter_x=False, dx=ox, dy=oy,
                            on_done=lambda: stage(0, 16, finish))

    def stage2():
        hit_all()
        ud['stage_left'] = 4
        for ddx, ddy in ((-1, 0), (0, -1), (1, 0), (0, 1)):
            _burst_tile(battle, coord, cx + ddx, cy + ddy, 0x656014, high=False, jitter_x=False,
                        on_done=lambda: stage(0, 4, stage3))

    def finish():
        for v in targets:
            _float(battle, caster, v)
        ud['released'] = True

    def arrive():
        _sfx(battle, SFX_PIG_HIT)
        ud['stage_left'] = 1
        _burst_tile(battle, coord, cx, cy, 0x655fa4, high=True, on_done=lambda: stage(0, 1, stage2))
        for v in targets:
            _hit(battle, caster, v)
    _spawn_ball(battle, coord, caster, SEQS[0x67512c], speed=(32, 24), on_arrive=arrive)


def _pao_hit(battle, caster, coord) -> None:
    ud = coord.user_data
    targets = ud['targets']
    _sfx(battle, SFX_ARROW)
    if ud['n'] >= len(targets):
        return
    v = targets[ud['n']]
    ud['n'] += 1

    def arrive():
        _sfx(battle, SFX_ARROW_HIT)
        _float(battle, caster, v)
        _hit(battle, caster, v, chiri=1)
    _spawn_shot(battle, coord, caster, v, ud['arg'], arrive)


def _bosan_multi_hit(battle, caster, coord) -> None:
    ud = coord.user_data
    _sfx(battle, SFX_GUN)
    for v in ud['targets']:
        _float(battle, caster, v)
        _hit(battle, caster, v, chiri=ud['arg'], birth=False)
    _sfx(battle, SFX_GUN)
    _sfx(battle, 0xbd)
    _sfx(battle, SFX_GUN)
    ud['released'] = True


def _bosan_seq_hit(battle, caster, coord) -> None:
    ud = coord.user_data
    targets = ud['targets']
    if ud['n'] < len(targets):
        v = targets[ud['n']]
        ud['n'] += 1
        _float(battle, caster, v)
        _hit(battle, caster, v, chiri=ud['arg'], birth=False)
    _sfx(battle, SFX_GUN)
    _sfx(battle, 0xbf)


def _bosan_laser_hit(battle, caster, coord) -> None:
    ud = coord.user_data
    targets = ud['targets']
    _sfx(battle, SFX_LASER)
    if ud['n'] >= len(targets):
        return
    v = targets[ud['n']]
    ud['n'] += 1

    def arrive():
        _float(battle, caster, v)
        _hit(battle, caster, v, chiri=1)
        _sfx(battle, 0xbd)
    _spawn_shot(battle, coord, caster, v, 0x678f0c, arrive)


# ---------------- 紫河第三形态 (FUN_0050fef1) ----------------
def _zihe_hit(battle, caster, coord) -> None:
    """每个 -100: 命中者 受击 (面向施法者) + 三爪 (抖动) + 刺爆 + 0x105; 闪避者 躲闪 seq."""
    from core.battle import combat
    from core.hit_effect_seq import pick_hit_effects, HIT_EFFECT_JITTER_PX, HIT_EFFECT_Y_BASELINE_PX
    ud = coord.user_data
    if 'dodged' not in ud:
        ud['dodged'] = {id(v): battle.rng.random() < combat.miss_chance(caster, v) for v in ud['targets']}
    for v in ud['targets']:
        if not v.alive:
            continue
        if ud['dodged'].get(id(v)):
            combat.set_reaction(v, "dodge", caster)
            continue
        _hit(battle, caster, v, face=True)
        spec = pick_hit_effects(None, None, (-v.facing[0], -v.facing[1]), 'CLAW')[0]
        cx, cy = _tile_center(v.x, v.y)
        ox = battle.rng.randint(-HIT_EFFECT_JITTER_PX, HIT_EFFECT_JITTER_PX)
        oy = battle.rng.randint(-HIT_EFFECT_JITTER_PX, HIT_EFFECT_JITTER_PX) - HIT_EFFECT_Y_BASELINE_PX
        combat._spawn_effect_entity(battle, (cx >> 16) + ox, (cy >> 16) + oy, spec)
        _sfx(battle, SFX_ZIHE_HIT)


def _toss_think(e: "Entity", eng: "Engine") -> None:
    """FUN_0050fe1c: 目标 z += vz, vz -= 2; 落地 → 0xf0, 再受击 + 紫星 + 刺爆 + 飘字."""
    ud = e.user_data
    if 'toss' not in ud:
        return
    v, coord, battle, caster = ud['victim'], ud['coord'], ud['battle'], ud['caster']
    ud['vz'] -= ud['g']
    ud['z'] += ud['vz']
    v.wind_lift = max(0, ud['z']) / FP            # 渲染: 本体上移 (影子留地面), 同白虎旋风
    if ud['z'] < 1:
        v.wind_lift = 0.0
        _sfx(battle, SFX_LAND)
        from core.bosan_skills import _starburst
        _hit(battle, caster, v, face=True)
        _starburst(battle, v)
        _float(battle, caster, v)
        _done(coord)
        eng.destroy(e)


def _zihe_toss(battle, caster, coord) -> None:
    ud = coord.user_data
    for v in ud['targets']:
        if not v.alive or ud.get('dodged', {}).get(id(v)):
            continue
        e = battle.engine.spawn(think_fn=_toss_think)
        e.flags = 0x800 | 0x10000
        e.user_data.update(kind='ra_toss', projectile=True, toss=True, victim=v, coord=coord, battle=battle,
                           caster=caster, z=0, vz=0x300000, g=0x20000)
        ud['live'] += 1
        _sfx(battle, SFX_TOSS)


HIT_HANDLERS = {'pig_ball': _pig_ball_hit, 'pig_hitscan': _pig_hitscan_hit, 'pig_aoe5': _pig_aoe5_hit,
                'pig_aoe16': _pig_aoe16_hit, 'pao': _pao_hit, 'bosan_multi': _bosan_multi_hit,
                'bosan_seq': _bosan_seq_hit, 'bosan_laser': _bosan_laser_hit, 'zihe3': _zihe_hit}
