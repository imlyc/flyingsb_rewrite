"""美娜 10 技能 (skill 0x0a..0x13), 2026-10-24 按 exe 逆向 (reverse_engineering/mina_decomp.txt, mina_thinks_decomp.txt,
mina_leaves_decomp.txt; 运动积分器 FUN_004c3211 / FUN_004cdbc2 见 motion_decomp.txt).

共同: 渐暗 → case 10 施法者挂 seq 6720bc[dir] (ps+2 一帧停 15t → -100 → exit, 姿势保持到收尾) → -100 各招:
  0x0a 小回復 (模板 FUN_004d4ee0)  = 乐神杰特 恢復樂章 光柱 (core.jet_skills._spawn_heal_pillars).
  0x0b 療毒 (FUN_004f9b77): 每目标接受姿 655aa8 + 控制体 FUN_004f9ade (0xca): 每 t 一粒 e00 闪光 (FUN_004f999e/4f97d5:
       目标处 z64 起, 半径每 t +1 环绕外扩, z 弹簧 (vz 4..7 每 t -0.5) 先升后落; vz 恰 0 → 外扩减为 0.3/t, 落地或 96t 后灭),
       第 24t → -200 目标回待机 (清中毒).
  0x0c 聖水 (FUN_004fa741): 每目标 eicefoc1 水花 (seq 672100, 0xec 首目标), 播完隐身, 之后 16t 每 t 一滴 e00 水珠
       (FUN_004fa3b0/4f9f6d: 绕目标 z+48 三轴椭圆, 半径 8t 内外扩, 再转慢, 88t 后收缩; 每 22t 后段撒 e00 星; 0x148 首目标每滴);
       最后一滴收到 0 → -200: eicefoc2 水花 (x±6 y+24 z72±8) + 红字 + 受击 6557f0[自身朝向] (0xc4 首目标).
  0x0d 移血 (FUN_004faf34): 每目标 64 片羽毛 (FUN_004fada8/4fab62: 绕目标 z+48 随机三轴椭圆, 半径随机 ±1 游走, 角 +0x200/t,
       80t 后 6 等分匀速飞到施法者 z+48; 0x12d / 0x112@20t / 0x12f) + 受击 (面向施法者) + et00 星 655ad0 (±8 抖动);
       全部羽毛到达 → 目标红字 + 施法者受击 6557f0[自身朝向] + 白字 (吸到的总量).
  0x0e 大恢復 (模板 FUN_004d568f): 每目标接受姿 + 4 个 ds_mag03 光点 (FUN_004d554c/4d529a, 同光柱但 4 个一组 0x4000 间隔,
       不撒羽毛), 0xc9; 收到 0 → -200 白字 (0xca 首目标); 外扩 >599 → -250 计数.
  0x0f 甦生 (模板 FUN_004fb91a) = 乐神杰特 回生舞步 (core.jet_skills._spawn_revive).
  0x10 封魔 (模板 FUN_004d4346): 每目标控制体 FUN_004d4132: age 8 起 16 次 (间隔 11,10,..,1) -250: 受击 6557f4 (固定朝下)
       + ef010 刺爆 655c10[0] + e_silenc 小图标 (x±12, 行中心+1, z52±8, 帧 rand&3, 0xea); 再 32t 大图标 (帧 8, 0xea×3);
       再 32t → -200, 图标全灭.  状态: 沉默 0x400 (只置位).
  0x11 超回復 (模板 FUN_004d62bc) = 乐神杰特 回復優卡 (core.jet_skills._spawn_yuka).
  0x12 重生 (FUN_004fbb9c) = 乐神杰特 強力慢曲 (seq 670818 + FUN_004f07e9; core.jet_skills._spawn_slow).
  0x13 召喚精靈 (FUN_004fdc32): FUN_004a6efe 从范围内随机挑一个单位: 我方 → 回血精灵 (FUN_004fc8a4, 0x8f, ps_CUN00),
       敌方 → 攻击精灵 (FUN_004fd730, 0x90, ps_CDE00). 精灵 8 方向 seq 6722c8[(φ·8>>16)+3 & 7].
       攻击: 施法者头上 (y-10) 螺旋升到 z64 (半径 48/36 每 t -0.75/-0.56, 角 0x800/t), 弹簧悬停, 朝目标连射 8 枚 ds_ice
       冰锥 (间隔 28,24,..,4; 原地播 9 帧再 24/32 px/t 直飞, 0xce), 命中 -250 受击 + et00 星 + 0xbd, 末枚 -200 红字;
       再 32t 飞回施法者.
       回血: 绕目标椭圆 (80×60) 4 个点各 32t 匀速飞 (0x111), 再螺旋收缩上升 (0xc9) 到 z96 → -200 白字, 飞回.
       精灵每 4t 撒 e00 闪光 (FUN_004fc1a3/4fc0c3); 回血精灵螺旋段每 t 两片落羽 (FUN_004fbfb6/4fbf4a).
实现: 施法 seq 的 -100 换成专用信号 MINA_SIG (skill_seq.SKILL_CAST_SIGNAL_HANDLERS), 协调实体沿用 jet_skills 的
(_coord_think: 计数归零 + 受击/飘字播完 → SIG_END 收尾渐亮). 数值 (伤害/回血) 走我们的公式, exe 公式另做.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.anim_engine.bytecode import tuple_to_bytecode
from core import jet_skills as J
from core.jet_skills import FP, E00, DS_MAG03, FEATHER_SEQS, MAG_SEQ, SPARKLE_FALL_SEQ, HEAL_POSE_SEQS
from core.jet_skills import _fx, _set_z, _rand, _sin, _cos, _pos, _sfx, _dir, _done, _hold_pose, _release_pose

if TYPE_CHECKING:
    from core.anim_engine.engine import Engine
    from core.anim_engine.entity import Entity

MINA_SKILLS = tuple(range(0x0a, 0x14))
MINA_SIG = -1013                     # 施法 seq 里代替 exe -100
EICEFOC1, EICEFOC2, ET00, E_SILENC, DS_ICE = 301, 302, 215, 220, 232
PS_ANGEL, PS_DEVIL = 'ps_CUN00', 'ps_CDE00'       # ps_ 登记表 0xd0 / 0xd8 (6×4 网格, 锚点 32,82)

ST_POISON, ST_SILENCE = 0x100, 0x400

# ---------------- seq ----------------
MINA_CAST = [[('idle', 2, f, 15), ('jump', MINA_SIG), ('exit',)] for f in (3, 7, 11, 15)]     # 6720bc[dir]
MINA_SEQS = {sid: MINA_CAST for sid in MINA_SKILLS}
HOLY_SPLASH_SEQ = [('fm', EICEFOC1, f, 1) for f in range(7)] + [('exit',)]                    # 672100
HOLY_DROP_SEQ = [('fm', E00, f, 1) for f in range(10, 16)] + [('loop',)]                     # 672148
HOLY_STAR_SEQ = [('fm', E00, f, 1) for f in range(10, 16)] + [('exit',)]                     # 672188
HOLY_HIT_SEQ = [('fm', EICEFOC2, f, 1) for f in range(6)] + [('exit',)]                      # 6565b8
DRAIN_STAR_SEQ = [('fm', ET00, 8, 4), ('fm', ET00, 9, 4), ('exit',)]                         # 655ad0
ICE_V_SEQ = [('fm', DS_ICE, f, 1) for f in (3, 2, 1, 0, 5, 6, 7, 4, 8)] + [('exit',)]        # 656c18 (上下)
ICE_H_SEQ = [('fm', DS_ICE, f, 1) for f in (3, 2, 1, 0, 5, 6, 7, 4, 11)] + [('exit',)]       # 656bbc (左右)
SPIRIT_FRAMES = [(0, 1, 2), (3, 4, 5), (18, 19, 20), (21, 22, 23), (6, 7, 8), (9, 10, 11), (12, 13, 14), (15, 16, 17)]  # 6722c8
DIR4_TO_8 = (0, 4, 6, 2)

SFX_HEAL_A, SFX_HEAL_B = 0xc9, 0xca
SFX_HOLY, SFX_HOLY_DROP, SFX_HOLY_HIT = 0xec, 0x148, 0xc4
SFX_DRAIN, SFX_DRAIN_20, SFX_DRAIN_GO = 0x12d, 0x112, 0x12f
SFX_SEAL = 0xea
SFX_SPIRIT_ATK, SFX_SPIRIT_HEAL, SFX_ICE, SFX_ICE_HIT, SFX_ANGEL_MOVE = 0x90, 0x8f, 0xce, 0xbd, 0x111


# ---------------- exe 运动积分器 ----------------
def _i32(v: int) -> int:
    return ((v + 0x80000000) & 0xffffffff) - 0x80000000


def _getz(e: "Entity") -> int:
    return e.user_data.get('ez', 0)


def _c3211(e: "Entity") -> None:
    """FUN_004c3211. ud: m (0x168), vx/vy/vz (0x16c..), ax/ay/az (0x178..), tx/ty/tz (0x184..), rx/ry/rz (400..),
    px/py/pz (0x19c..). m&1 弹簧 (v += ±a 朝 t; p += v); m&2 绝对环绕 (p = t + sin/-cos/cos · r); m&4 增量环绕."""
    ud = e.user_data
    m = ud['m']
    x, y, z = e.x, e.y, _getz(e)
    if m & 1:
        if m & 0x10:
            ud['vx'] += ud['ax'] if x < ud['tx'] else -ud['ax']
            x += ud['vx']
        if m & 0x20:
            ud['vy'] += ud['ay'] if y < ud['ty'] else -ud['ay']
            y += ud['vy']
        if m & 0x40:
            ud['vz'] += ud['az'] if z < ud['tz'] else -ud['az']
            z += ud['vz']
    elif m & 2:
        if m & 0x10:
            x = _i32(ud['tx'] + _i32(_sin(ud['px']) * ud['rx']))
        if m & 0x20:
            y = _i32(ud['ty'] - _i32(_cos(ud['py']) * ud['ry']))
        if m & 0x40:
            z = _i32(ud['tz'] + _i32(_cos(ud['pz']) * ud['rz']))
    elif m & 4:
        if m & 0x10:
            x = _i32(x + _i32(_sin(ud['px']) * ud['rx']))
        if m & 0x20:
            y = _i32(y - _i32(_cos(ud['py']) * ud['ry']))
        if m & 0x40:
            z = _i32(z + _i32(_cos(ud['pz']) * ud['rz']))
    else:
        return
    e.x, e.y = x, y
    _set_z(e, z)


def _cdbc2(e: "Entity") -> bool:
    """FUN_004cdbc2 (m&1 才动): 弹簧 + 越过目标即钳位并清该轴位. 返回 三轴都到 (m & 0x70 == 0)."""
    ud = e.user_data
    m = ud['m']
    if not m & 1:
        return (m & 0x70) == 0
    pos = [e.x, e.y, _getz(e)]
    for i, (bit, v, a, t) in enumerate(((0x10, 'vx', 'ax', 'tx'), (0x20, 'vy', 'ay', 'ty'), (0x40, 'vz', 'az', 'tz'))):
        if not m & bit:
            continue
        ud[v] += ud[a] if pos[i] < ud[t] else -ud[a]
        pos[i] += ud[v]
        vv = ud[v]
        if (vv > 0 and pos[i] >= ud[t]) or (vv < 0 and pos[i] <= ud[t]) or vv == 0:
            ud['m'] &= ~bit
            pos[i] = ud[t]
    e.x, e.y = pos[0], pos[1]
    _set_z(e, pos[2])
    return (ud['m'] & 0x70) == 0


def _motion(**kw) -> dict:
    d = dict(m=0, vx=0, vy=0, vz=0, ax=0, ay=0, az=0, tx=0, ty=0, tz=0, rx=0, ry=0, rz=0, px=0, py=0, pz=0)
    d.update(kw)
    return d


def _ctrunc(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def _wrap16(v: int) -> int:
    return v & 0xffff


def _unit_z(u) -> int:
    ent = u.entity
    return -ent.z if (ent is not None and u.reaction_seq is None) else 0


# ---------------- 目标 / 公共 ----------------
def _targets(battle, caster, sid: int) -> list:
    enemy = sid in (0x0c, 0x0d, 0x10)
    revive = sid in (0x0f, 0x12)
    out = []
    tiles = getattr(battle, '_pending_damage_range', None)
    cand = [(x, y) for (x, y) in sorted(tiles, key=lambda t: (t[1], t[0]))] if tiles else []
    if not cand:
        t = caster.pending_attack_target
        cand = [(t.x, t.y)] if t is not None else []
    for (x, y) in cand:
        for u in battle.all_units:
            if (u.x, u.y) != (x, y) or u in out:
                continue
            if sid == 0x13:
                if u.alive:
                    out.append(u)
            elif enemy:
                if u.alive and u.is_player != caster.is_player:
                    out.append(u)
            elif u.is_player == caster.is_player and (u.alive or revive):
                if sid == 0x0f and u.alive:
                    continue
                out.append(u)
    return out


def _new_coord(battle, caster, sid, targets) -> "Entity":
    coord = battle.engine.spawn(think_fn=J._coord_think)
    coord.flags = 0x800 | 0x10000
    coord.user_data.update(kind='mina_coord', projectile=True, jet=True, battle=battle, caster=caster, sid=sid,
                           targets=targets, live=0, seq_signal=True, birth_think=False)
    return coord


def on_cast_signal(battle, caster, sig: int) -> bool:
    if sig != MINA_SIG:
        return False
    sid = caster.pending_skill_id
    if sid == 0x13:
        target = getattr(caster, 'mina_spirit_target', None)
        targets = [target] if target is not None else []
    else:
        targets = _targets(battle, caster, sid)
    _apply_statuses(battle, caster, sid, targets)
    coord = _new_coord(battle, caster, sid, targets)
    SPAWN[sid](battle, caster, coord, targets)
    return True


def on_attach(battle, caster) -> None:
    """case 10: 召喚精靈 在挂 seq 的同一刻按 (已定的) 目标阵营播起手音."""
    if caster.pending_skill_id != 0x13:
        return
    cand = _targets(battle, caster, 0x13)
    t = cand[battle.rng.randrange(len(cand))] if cand else None
    caster.mina_spirit_target = t
    if t is not None:
        _sfx(battle, SFX_SPIRIT_HEAL if t.is_player == caster.is_player else SFX_SPIRIT_ATK)


def _apply_statuses(battle, caster, sid: int, targets: list) -> None:
    from core.battle.status import apply_status, clear_status, has_status
    for t in targets:
        if sid == 0x0b and has_status(t, ST_POISON):
            clear_status(t, ST_POISON)
        elif sid == 0x10 and not (t.type_flags & (0x20 | ST_SILENCE)):
            apply_status(t, ST_SILENCE, 3)
            battle._log(f"{t.name} 沉默 (3 回合)")


def _hit_pose(victim, face=None, fixed_idx: int | None = None) -> None:
    """受击 seq 6557f0[dir]. face=单位 → 面朝它 (表 6418dc[其朝向]); fixed_idx → 固定那一项 (封魔 6557f4 = 朝下)."""
    from core.battle import combat
    if not victim.alive:
        return
    if fixed_idx is None:
        combat.set_reaction(victim, "hit", face)
        return
    saved = victim.facing
    victim.facing = ((0, -1), (0, 1), (-1, 0), (1, 0))[fixed_idx]
    combat.set_reaction(victim, "hit", None)
    victim.reaction_saved_facing = saved if victim.reaction_saved_facing is None else victim.reaction_saved_facing
    victim.facing = saved


def _seq_end_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004d0dcf: seq 播完自毁."""
    if 'fx_end' in e.user_data and not e.is_playing():
        eng.destroy(e)


def _effect_at(battle, x: int, y: int, z: int, seq) -> "Entity":
    """FUN_004d0d7b: 给定世界坐标 (16.16, z 正 = 高) 挂 seq, 播完自毁."""
    return _fx(battle, _seq_end_think, x, y, z, seq, fx_end=True)


def _damage(battle, caster, victim) -> int:
    from core.son_transform import _damage_only
    before = victim.hp
    _damage_only(battle, caster, victim)
    return max(0, before - victim.hp)


# ---------------- 0x0e 大恢復 (FUN_004d568f / 4d554c / 4d529a) ----------------
def _bigheal_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'bigheal' not in ud:
        return
    battle = ud['battle']
    st = ud['state']
    if st == 0:
        _set_z(e, _getz(e) + FP)
        ud['spd'] = min(ud['spd'] + 0x20, 0x1000)
        ud['py'] = _wrap16(ud['py'] + ud['spd'])
        ud['px'] = ud['py']
        _c3211(e)
        if ud['age'] % 2 == 0:
            J._spawn_rise(battle, e)
        if _getz(e) > 0x600000:
            ud['state'] = 10
    elif st == 10:
        ud['py'] = _wrap16(ud['py'] + ud['spd'])
        ud['px'] = ud['py']
        ud['rx'] = ud['ry']
        ud['ry'] -= 1
        _c3211(e)
        if ud['rx'] < 1:
            if ud.get('lead'):
                t = ud['target']
                if ud['first']:
                    _sfx(battle, SFX_HEAL_B)
                _release_pose(t)
                J._heal(battle, ud['coord'].user_data['caster'], t)
            ud['rz'] = 0
            ud['state'] = 20
    else:
        ud['rz'] += 10
        ud['ry'] += ud['rz']
        ud['rx'] = ud['ry']
        _c3211(e)
        J._spawn_rise(battle, e)
        if ud['rx'] > 599:
            if ud.get('lead'):
                _done(ud['coord'])
            eng.destroy(e)
            return
    ud['age'] += 1


def _spawn_bigheal(battle, caster, coord, targets) -> None:
    for i, t in enumerate(targets):
        if t.is_player:
            _hold_pose(battle, t, HEAL_POSE_SEQS, coord)
        cx, cy = _pos(t)
        phi = ((_rand(battle) & 0x3ff) << 16) >> 10
        for k in range(4):
            e = _fx(battle, _bigheal_think, cx, cy, 0, MAG_SEQ, bigheal=True, battle=battle, coord=coord, target=t,
                    state=0, age=0, spd=0x400, lead=(k == 3), first=(i == 0),
                    **_motion(m=0x32, tx=cx, ty=cy, rx=0x20, ry=0x18, px=phi, py=phi))
            _c3211(e)
            phi = _wrap16(phi + 0x4000)
        coord.user_data['live'] += 1
    _sfx(battle, SFX_HEAL_A)


# ---------------- 0x0b 療毒 (FUN_004f9b77 / 4f9ade / 4f999e / 4f97d5) ----------------
def _cure_particle_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'cure' not in ud:
        return
    ud['v170'] += ud['v16c']
    ud['ry'] = ud['v170'] >> 16
    ud['rx'] = ud['ry']
    ud['m'] = 0x32
    _c3211(e)
    ud['m'] = 0x41
    _c3211(e)
    if ud['state'] == 0:
        if ud['vz'] == 0:
            ud['v16c'] = 0x4ccc
            ud['az'] = 0x2666
            ud['end'] = ud['age'] + 0x60
            ud['state'] = 10
    elif _getz(e) < 1 or ud['age'] == ud['end']:
        _done(ud['coord'])
        eng.destroy(e)
        return
    ud['age'] += 1


def _spawn_cure_particle(battle, coord, t) -> None:
    """FUN_004f999e(目标, 1)."""
    cx, cy = _pos(t)
    phi = ((_rand(battle) & 0x3ff) << 16) >> 10
    vz = ((_rand(battle) & 3) + 4) << 16
    e = _fx(battle, _cure_particle_think, cx, cy, 64 * FP, SPARKLE_FALL_SEQ, cure=True, coord=coord, state=0, age=0,
            end=-1, v16c=FP, v170=0, **_motion(tx=cx, ty=cy, tz=0, px=phi, py=phi, vz=vz, az=0x8000))
    coord.user_data['live'] += 1                       # 粒子出生 -300 计数 (+0x7c)
    _cure_particle_think(e, battle.engine)             # 池序在控制体之后 → 出生 tick 就 think (实录 mina_0b 首帧 z 67..70)


def _cure_ctrl_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'cure_ctrl' not in ud:
        return
    battle, t = ud['battle'], ud['target']
    _spawn_cure_particle(battle, ud['coord'], t)
    if ud['age'] == ud['n']:
        _release_pose(t)                               # -200: 目标回待机
        _done(ud['coord'])
        eng.destroy(e)
        return
    ud['age'] += 1


def _spawn_cure(battle, caster, coord, targets) -> None:
    for t in targets:
        _hold_pose(battle, t, HEAL_POSE_SEQS, coord)
        e = battle.engine.spawn(think_fn=_cure_ctrl_think)
        e.flags = 0x800 | 0x10000
        e.user_data.update(kind='mina_cure', projectile=True, cure_ctrl=True, battle=battle, coord=coord, target=t,
                           age=0, n=0x18)
        coord.user_data['live'] += 1
        _sfx(battle, SFX_HEAL_B)


# ---------------- 0x0c 聖水 (FUN_004fa741 / 4fa6b9 / 4fa603 / 4fa3b0 / 4f9f6d) ----------------
def _holy_drop_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'holy' not in ud:
        return
    battle, t = ud['battle'], ud['target']
    cx, cy = _pos(t)
    ud['tx'], ud['ty'], ud['tz'] = cx, cy, _unit_z(t) + 48 * FP
    st = ud['state']
    if st == 0:
        ud['py'] = _wrap16(ud['py'] - ud['spd'] + 0x10000)
        ud['px'] = ud['py']
        _c3211(e)
        ud['rx'], ud['ry'], ud['rz'] = ud['v16c'] >> 16, ud['v170'] >> 16, ud['v178'] >> 16
        ud['v16c'] += ud['a180']
        ud['v170'] += ud['a174']
        ud['v178'] += ud['a164']
        if ud['age'] == 8:
            ud['state'] = 10
    elif st == 10:
        ud['py'] = _wrap16(ud['py'] - ud['spd'] + 0x10000)
        ud['px'] = ud['py']
        ud['spd'] = max(ud['spd'] - 0x40, 0x40)
        _c3211(e)
        if ud['age'] == 0x58:
            ud['a180'] <<= 1
            ud['a174'] <<= 1
            ud['a164'] <<= 1
            ud['state'] = 20
        if ud['age'] % 0x16 > 0xe:
            _effect_at(battle, e.x, e.y, _getz(e), HOLY_STAR_SEQ)
    else:
        ud['rx'], ud['ry'], ud['rz'] = ud['v16c'] >> 16, ud['v170'] >> 16, ud['v178'] >> 16
        ud['v16c'] -= ud['a180']
        ud['v170'] -= ud['a174']
        ud['v178'] -= ud['a164']
        ud['py'] = _wrap16(ud['py'] - ud['spd'] + 0x10000)
        ud['px'] = ud['py']
        _c3211(e)
        if ud['ry'] < 1:
            if ud.get('lead'):
                _holy_hit(battle, ud['coord'], t)
                if ud['first']:
                    _sfx(battle, SFX_HOLY_HIT)
            eng.destroy(e)
            return
    ud['age'] += 1


def _holy_hit(battle, coord, t) -> None:
    """dispatcher -200: eicefoc2 水花 + 红字 + 受击 6557f0[自身朝向]."""
    cx, cy = _pos(t)
    x = cx + (((_rand(battle) % 12) - 6) << 16)
    z = _unit_z(t) + 0x480000 + (((_rand(battle) & 15) - 8) << 16)
    _effect_at(battle, x, cy + 0x180000, z, HOLY_HIT_SEQ)
    _damage(battle, coord.user_data['caster'], t)
    _hit_pose(t)
    _done(coord)


def _spawn_holy_drop(battle, coord, t, first: bool) -> "Entity":
    """FUN_004fa3b0(目标, 1)."""
    cx, cy = _pos(t)
    tz = _unit_z(t) + 48 * FP
    px = (_rand(battle) << 16) // 0x7fff
    py = (_rand(battle) << 16) // 0x7fff
    pz = (_rand(battle) << 16) // 0x7fff
    rx = _sin(pz) * 0x30
    ry = _sin(pz) << 5
    spd = (((_rand(battle) & 31) << 16) >> 12) + 0x1000
    e = _fx(battle, _holy_drop_think, cx, cy, tz, HOLY_DROP_SEQ, holy=True, battle=battle, coord=coord, target=t,
            state=0, age=0, first=first, spd=spd, v16c=abs(rx), v170=abs(ry), v178=0x30 << 16,
            a180=_ctrunc(abs(rx), 4), a174=_ctrunc(abs(ry), 4), a164=(0x30 << 16) // 4,
            **_motion(m=0x72, tx=cx, ty=cy, tz=tz, px=px, py=py, pz=pz, rx=rx, ry=ry, rz=0x30))
    if first:
        _sfx(battle, SFX_HOLY_DROP)
    _holy_drop_think(e, battle.engine)       # 池序在控制体之后 → 出生 tick 就 think; 首帧用未换算的 16.16 半径, int32 溢出飞到画面外 (实录 mina_0c 同)
    return e


def _holy_ctrl_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'holy_ctrl' not in ud:
        return
    battle = ud['battle']
    if ud['state'] == 0:
        if not e.is_playing():
            e.flags &= ~0x40
            ud['kind'] = 'mina_holy_ctrl'               # 隐身 (渲染器只画 kind=hit_effect)
            ud['end'] = ud['age'] + 0x10
            ud['state'] = 10
    else:
        d = _spawn_holy_drop(battle, ud['coord'], ud['target'], ud['first'])
        if ud['age'] == ud['end']:
            d.user_data['lead'] = True
            eng.destroy(e)
            return
    ud['age'] += 1


def _spawn_holy(battle, caster, coord, targets) -> None:
    for i, t in enumerate(targets):
        cx, cy = _pos(t)
        _fx(battle, _holy_ctrl_think, cx, cy + FP, _unit_z(t) + FP, HOLY_SPLASH_SEQ, holy_ctrl=True, battle=battle,
            coord=coord, target=t, state=0, age=0, end=-1, first=(i == 0))
        if i == 0:
            _sfx(battle, SFX_HOLY)
        coord.user_data['live'] += 1


# ---------------- 0x0d 移血 (FUN_004faf34 / 4fada8 / 4fab62) ----------------
def _drain_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'drain' not in ud:
        return
    battle = ud['battle']
    coord = ud['coord']
    if ud['state'] == 0:
        if ud['age'] == 0x14 and ud.get('lead'):
            _sfx(battle, SFX_DRAIN_20)
        for k in ('rx', 'ry', 'rz'):
            ud[k] += 1 if (_rand(battle) & 1) else -1
        ud['py'] = _wrap16(ud['py'] + 0x200)
        ud['px'] = ud['py']
        _c3211(e)
        if ud['age'] > 0x4f:
            caster = coord.user_data['caster']
            cx, cy = _pos(caster)
            ud.update(tx=cx, ty=cy, tz=_unit_z(caster) + 0x300000, m=0x71, ax=0, ay=0, az=0)
            ud['vx'] = _ctrunc(ud['tx'] - e.x, 6)
            ud['vy'] = _ctrunc(ud['ty'] - e.y, 6)
            ud['vz'] = _ctrunc(ud['tz'] - _getz(e), 6)
            ud['state'] = 10
            if ud.get('lead'):
                _sfx(battle, SFX_DRAIN_GO)
    elif _cdbc2(e):
        cd = coord.user_data
        cd['drain_left'] -= 1
        if cd['drain_left'] == 0:
            _drain_settle(battle, coord)
        _done(coord)
        eng.destroy(e)
        return
    ud['age'] += 1


def _drain_settle(battle, coord) -> None:
    """dispatcher -250 计数归零: 各目标红字, 施法者受击 6557f0[自身朝向] + 白字 (吸到的总量)."""
    from core.battle.combat import push_damage_event
    from core.battle.data import DamageEvent
    cd = coord.user_data
    caster = cd['caster']
    total = 0
    for t in cd['targets']:
        total += _damage(battle, caster, t)
    if caster.entity is not None:
        caster.entity.seq = b''
    caster.cast_hold = False
    _hit_pose(caster)
    before = caster.hp
    caster.hp = min(caster.max_hp, caster.hp + total)
    caster.shown_hp_override = None
    push_damage_event(battle, caster, DamageEvent(caster.hp - before, caster.hp, caster.x, caster.y, heal=True))


def _spawn_drain(battle, caster, coord, targets) -> None:
    from core.battle import combat
    from core.hit_effect_seq import HIT_EFFECT_Y_BASELINE_PX
    coord.user_data['drain_left'] = 0
    for t in targets:
        cx, cy = _pos(t)
        tz = _unit_z(t) + 0x300000
        last = None
        for _ in range(0x40):
            px = ((_rand(battle) % 1000) << 16) // 1000
            pz = ((_rand(battle) % 1000) << 16) // 1000
            rx = _ctrunc(_sin(pz) * 0x30, FP)
            ry = _ctrunc(_sin(pz) * 0x24, FP)
            e = _fx(battle, _drain_think, cx, cy, tz, FEATHER_SEQS[0], drain=True, battle=battle, coord=coord,
                    state=0, age=0, **_motion(m=0x72, tx=cx, ty=cy, tz=tz, px=px, py=px, pz=pz, rx=rx, ry=ry, rz=0x30))
            _c3211(e)
            battle.engine.attach_seq(e, tuple_to_bytecode(FEATHER_SEQS[_rand(battle) & 3]))
            coord.user_data['live'] += 1                  # 每片 -200 → +0x7c
            coord.user_data['drain_left'] += 1
            last = e
        last.user_data['lead'] = True
        _sfx(battle, SFX_DRAIN)
        _hit_pose(t, face=caster)
        r3, r2, r1 = _rand(battle) & 15, _rand(battle) & 15, _rand(battle) & 15
        combat._spawn_skill_extra_effect(battle, (cx >> 16) + r1 - 8,
                                         (cy >> 16) + r2 - 8 - HIT_EFFECT_Y_BASELINE_PX - (r3 - 8), DRAIN_STAR_SEQ)


# ---------------- 0x10 封魔 (FUN_004d4346 / 4d4323 / 4d4132 / 4d3f94 / 4d4075) ----------------
def _seal_icon(battle, coord, t, big: bool) -> None:
    from core.sprites.base import TILE_H
    cx, cy = _pos(t)
    row_y = ((t.y * TILE_H) + 24) * FP
    if big:
        x, y, z, frame = cx, row_y + 2 * FP, 0x340000, 8
    else:
        x = cx + ((_rand(battle) % 0x18 - 0xc) << 16)
        y = row_y + FP
        z = (((_rand(battle) & 15) - 8) << 16) + 0x340000
        frame = _rand(battle) & 3
    e = _fx(battle, _seal_icon_think, x, y, z, atlas=E_SILENC, frame=frame, seal_icon=True, coord=coord)
    coord.user_data.setdefault('icons', []).append(e)
    for _ in range(3 if big else 1):
        _sfx(battle, SFX_SEAL)


def _seal_icon_think(e: "Entity", eng: "Engine") -> None:
    if 'seal_icon' in e.user_data and e.user_data['coord'].user_data.get('icons_off'):
        eng.destroy(e)


def _seal_hit(battle, coord, t) -> None:
    from core.bosan_skills import _spark
    _hit_pose(t, fixed_idx=1)
    _spark(battle, 0, t)


def _seal_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'seal' not in ud:
        return
    battle, t, coord = ud['battle'], ud['target'], ud['coord']
    if ud['age'] == ud['next']:
        if ud['state'] == 0:
            _seal_hit(battle, coord, t)
            _seal_icon(battle, coord, t, big=False)
            ud['n'] += 1
            ud['next'] += max(0xc - ud['n'], 1)
            if ud['n'] > 0xf:
                ud['next'] = ud['age'] + 0x20
                ud['state'] = 10
        elif ud['state'] == 10:
            _seal_hit(battle, coord, t)
            _seal_icon(battle, coord, t, big=True)
            ud['next'] = ud['age'] + 0x20
            ud['state'] = 20
        else:
            coord.user_data['icons_off'] = True
            _done(coord)
            eng.destroy(e)
            return
    ud['age'] += 1


def _spawn_seal(battle, caster, coord, targets) -> None:
    for t in targets:
        e = battle.engine.spawn(think_fn=_seal_think)
        e.flags = 0x800 | 0x10000
        e.user_data.update(kind='mina_seal', projectile=True, seal=True, battle=battle, coord=coord, target=t,
                           state=0, age=0, n=0, next=8)
        coord.user_data['live'] += 1


# ---------------- 0x13 召喚精靈 ----------------
def _set_spirit_dir(e: "Entity", dir8: int) -> None:
    """FUN_004fbee9: 方向变了才换 seq (6722c8[dir&7], 每帧 3t 循环)."""
    ud = e.user_data
    dir8 &= 7
    if ud.get('dir8') == dir8:
        return
    ud['dir8'] = dir8
    ud['ps_frames'] = SPIRIT_FRAMES[dir8]
    ud['ps_i'] = 0
    ud['ps_t'] = 0
    e.frame_idx = SPIRIT_FRAMES[dir8][0]


def _spirit_anim(e: "Entity") -> None:
    ud = e.user_data
    ud['ps_t'] += 1
    if ud['ps_t'] >= 3:
        ud['ps_t'] = 0
        ud['ps_i'] = (ud['ps_i'] + 1) % 3
        e.frame_idx = ud['ps_frames'][ud['ps_i']]


def _dir8_from_phase(phi: int) -> int:
    return (((phi * 8) >> 16) + 3) & 7


def _spawn_spirit_entity(battle, caster, think, sheet: str, **ud) -> "Entity":
    from core.grid_atlas_table import GRID_ATLAS
    x, y = _pos(caster)
    e = battle.engine.spawn(think_fn=think)
    e.flags |= 0x40
    e.x, e.y = x, y - 10 * FP
    _set_z(e, _unit_z(caster))
    grid = next(v for v in GRID_ATLAS.values() if v[0] == sheet)
    e.user_data.update(kind='hit_effect', projectile=True, ps_sheet=sheet, ps_grid=(grid[1], 64, 48, grid[3], grid[4]),
                       battle=battle, caster=caster, state=0, age=0, **ud)
    _set_spirit_dir(e, 4)
    return e


def _sparkle_trail(battle, src: "Entity") -> None:
    """FUN_004fc1a3: 精灵处 z+48 e00 闪光, 增量环绕 (r 0/1 随机, 每 16t 换角), 64t 灭."""
    phi = ((_rand(battle) % 1000) << 16) // 3000
    _fx(battle, _trail_think, src.x, src.y, _getz(src) + 0x300000, FEATHER_SEQS[_rand(battle) & 3], trail=True,
        battle=battle, age=0, nxt=0x19, **_motion(m=0x34, px=phi, py=phi, rx=1, ry=1))


def _trail_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'trail' not in ud:
        return
    battle = ud['battle']
    if ud['age'] == ud['nxt']:
        ud['px'] = ud['py'] = ud['px'] + ((_rand(battle) % 1000) << 16) // 3000
        ud['rx'] = _rand(battle) & 1
        ud['ry'] = _rand(battle) & 1
        ud['nxt'] = ud['age'] + 0x10
    _c3211(e)
    ud['age'] += 1
    if ud['age'] > 0x3f:
        eng.destroy(e)


def _drop_feather(battle, src: "Entity") -> None:
    """FUN_004fbfb6: 精灵处 z+48 落羽 (vx/vy 0x4000/(rand&3+1), vz -2, 无加速)."""
    vx = 0x4000 // ((_rand(battle) & 3) + 1)
    vy = 0x4000 // ((_rand(battle) & 3) + 1)
    _fx(battle, _drop_think, src.x, src.y, _getz(src) + 0x300000, FEATHER_SEQS[_rand(battle) & 3], drop=True, age=0,
        **_motion(m=0x71, vx=vx, vy=vy, vz=-2 * FP, tx=0x7fffffff, ty=0x7fffffff))


def _drop_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'drop' not in ud:
        return
    _c3211(e)
    if ud['vz'] == 0:
        ud['az'] //= 4
    ud['age'] += 1
    if ud['age'] > 0x40 or _getz(e) < 1:
        eng.destroy(e)


def _face4(spirit: "Entity", target) -> int:
    tx, ty = _pos(target)
    dx, dy = tx - spirit.x, ty - spirit.y
    ax, ay = abs(dx), abs(dy)
    if dx >= 0 and dy >= 0:
        return 1 if ax <= ay else 3
    if dx >= 0:
        return 0 if ax <= ay else 3
    if dy >= 0:
        return 2 if ay < ax else 1
    return 0 if ax <= ay else 2


def _devil_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004fd010 攻击精灵."""
    ud = e.user_data
    if 'devil' not in ud:
        return
    battle, caster, t = ud['battle'], ud['caster'], ud['target']
    st = ud['state']
    if st == 0:
        cx, cy = _pos(caster)
        ud.update(tx=cx, ty=cy, accx=0x300000, accy=0x240000, px=0, py=0, spd=0x800, m=0x32, state=10)
    elif st == 10:
        ud['accx'] -= 0xc000
        ud['accy'] -= 0x9000
        ud['rx'], ud['ry'] = ud['accx'] >> 16, ud['accy'] >> 16
        ud['py'] = _wrap16(ud['py'] + ud['spd'])
        ud['px'] = ud['py']
        _set_z(e, _getz(e) + FP)
        _c3211(e)
        if ud['age'] % 4 == 0:
            _sparkle_trail(battle, e)
        _set_spirit_dir(e, _dir8_from_phase(ud['px']))
        if _getz(e) > 0x3fffff:
            ud['tx'] = e.x + 0x80000 + ((_rand(battle) & 3) << 16)
            ud['ty'] = e.y + 0x60000 + ((_rand(battle) % 3) << 16)
            ud['tz'] = _getz(e) + 0x80000 + ((_rand(battle) & 3) << 16)
            ud.update(ax=0x3333, ay=0x2666, az=0x3333, vx=0, vy=0, vz=0, m=0x71, n=0, nxt=ud['age'] + 0x20, state=20)
            d4 = _face4(e, t)
            _set_spirit_dir(e, DIR4_TO_8[d4])
            ud['dir4'] = d4
    elif st == 20:
        _c3211(e)
        if ud['age'] % 4 == 0:
            _sparkle_trail(battle, e)
        if ud['age'] == ud['nxt']:
            shard = _spawn_ice(battle, ud['coord'], t, e)
            ud['n'] += 1
            ud['nxt'] += max((8 - ud['n']) * 4, 1)
            if ud['n'] > 7:
                shard.user_data['lead'] = True
                ud['nxt'] += 0x20
                ud['state'] = 30
    elif st == 30:
        _c3211(e)
        if ud['age'] == ud['nxt']:
            _return_to_caster(e, caster)
            ud['state'] = 40
    elif _cdbc2(e):
        eng.destroy(e)
        return
    _spirit_anim(e)
    ud['age'] += 1


def _return_to_caster(e: "Entity", caster) -> None:
    ud = e.user_data
    cx, cy = _pos(caster)
    ud.update(tx=cx, ty=cy - 2 * FP, tz=_unit_z(caster), m=0x71)
    ud['vx'] = _ctrunc(ud['tx'] - e.x, 16)
    ud['vy'] = _ctrunc(ud['ty'] - e.y, 16)
    ud['vz'] = _ctrunc(ud['tz'] - _getz(e), 16)


def _spawn_ice(battle, coord, t, spirit: "Entity") -> "Entity":
    """FUN_004fcc33: 精灵处 (x-4..+3, y-2..+5, z+48) 按朝向前移 24/36px, 原地播 9 帧, 再 24/32 px/t 直飞目标 z48."""
    x = spirit.x - 0x40000 + ((_rand(battle) & 7) << 16)
    y = spirit.y - 0x20000 + ((_rand(battle) & 7) << 16)
    z = _getz(spirit) + 0x300000
    tx, ty = _pos(t)
    tz = 0x300000
    d4 = spirit.user_data.get('dir4', 1)
    if d4 in (0, 1):
        y += -0x180000 if d4 == 0 else 0x180000
        vy = -0x180000 if d4 == 0 else 0x180000
        n = max(_ctrunc(ty - y, vy), 1)
        vx, vz = _ctrunc(tx - x, n), _ctrunc(tz - z, n)
        seq = ICE_V_SEQ
    else:
        x += -0x240000 if d4 == 2 else 0x240000
        vx = -0x200000 if d4 == 2 else 0x200000
        n = max(_ctrunc(tx - x, vx), 1)
        vy, vz = _ctrunc(ty - y, n), _ctrunc(tz - z, n)
        seq = ICE_H_SEQ
    e = _fx(battle, _ice_think, x, y, z, seq, ice=True, battle=battle, coord=coord, target=t, state=0,
            **_motion(m=0x71, tx=tx, ty=ty, tz=tz, vx=vx, vy=vy, vz=vz))
    _sfx(battle, SFX_ICE)
    return e


def _ice_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'ice' not in ud:
        return
    if ud['state'] == 0:
        if not e.is_playing():
            ud['state'] = 10
        return
    if not _cdbc2(e):
        return
    battle, t, coord = ud['battle'], ud['target'], ud['coord']
    from core.bosan_skills import _starburst
    _hit_pose(t)
    _starburst(battle, t)
    _sfx(battle, SFX_ICE_HIT)
    if ud.get('lead'):
        _damage(battle, coord.user_data['caster'], t)
        _done(coord)
    eng.destroy(e)


def _angel_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004fc27b 回血精灵."""
    ud = e.user_data
    if 'angel' not in ud:
        return
    battle, caster, t = ud['battle'], ud['caster'], ud['target']
    st = ud['state']
    if st == 0:
        sx, sy, sz = e.x, e.y, _getz(e)
        cx, cy = _pos(t)
        ud.update(tx=cx, ty=cy, px=ud['phi0'], py=ud['phi0'], rx=0x50, ry=0x3c, m=0x32)
        _c3211(e)
        ud['tx'], ud['ty'] = e.x, e.y
        e.x, e.y = sx, sy
        _set_z(e, sz)
        ud['vx'] = _ctrunc(ud['tx'] - e.x, 32)
        ud['vy'] = _ctrunc(ud['ty'] - e.y, 32)
        ud['ax'] = ud['ay'] = 0
        ud['phi0'] = ud['phi0'] + 0x4000
        _set_spirit_dir(e, _dir8_from_phase(ud['px']))
        ud['m'] = 0x31
        ud['state'] = 10
        _sfx(battle, SFX_ANGEL_MOVE)
    elif st == 10:
        _cdbc2(e)
        if ud['age'] % 4 == 0:
            _sparkle_trail(battle, e)
        if (ud['m'] & 0x30) == 0:
            ud['n'] += 1
            if ud['n'] < 4:
                ud['state'] = 0
            else:
                cx, cy = _pos(t)
                ud.update(tx=cx, ty=cy, accx=0x50 << 16, accy=0x3c << 16, m=0x32, state=20)
                _sfx(battle, SFX_HEAL_A)
    elif st == 20:
        ud['accx'] -= 0x8000
        ud['accy'] -= 0x6000
        ud['rx'], ud['ry'] = ud['accx'] >> 16, ud['accy'] >> 16
        ud['w'] = min(ud['w'] + 0x40, 0x1000)
        ud['py'] = _wrap16(ud['py'] + ud['w'])
        ud['px'] = ud['py']
        _set_z(e, _getz(e) + 0xc000)
        _drop_feather(battle, e)
        _c3211(e)
        _drop_feather(battle, e)
        _set_spirit_dir(e, _dir8_from_phase(ud['px']))
        if _getz(e) > 0x5fffff:
            _release_pose(t)
            J._heal(battle, caster, t)
            _done(ud['coord'])
            _return_to_caster(e, caster)
            ud['ax'] = ud['ay'] = 0
            ud['az'] = ud['w']
            ud['state'] = 30
    elif _cdbc2(e):
        eng.destroy(e)
        return
    _spirit_anim(e)
    ud['age'] += 1


def _spawn_spirit(battle, caster, coord, targets) -> None:
    if not targets:
        return
    t = targets[0]
    if t.is_player == caster.is_player:
        _hold_pose(battle, t, HEAL_POSE_SEQS, coord)
        phi0 = ((_rand(battle) % 1000) << 16) // 1000
        _spawn_spirit_entity(battle, caster, _angel_think, PS_ANGEL, angel=True, coord=coord, target=t, phi0=phi0,
                             n=0, w=0, **_motion())
    else:
        _spawn_spirit_entity(battle, caster, _devil_think, PS_DEVIL, devil=True, coord=coord, target=t, n=0,
                             **_motion())
    coord.user_data['live'] += 1


SPAWN = {0x0a: J._spawn_heal_pillars, 0x0b: _spawn_cure, 0x0c: _spawn_holy, 0x0d: _spawn_drain,
         0x0e: _spawn_bigheal, 0x0f: J._spawn_revive, 0x10: _spawn_seal, 0x11: J._spawn_yuka, 0x12: J._spawn_slow,
         0x13: _spawn_spirit}
