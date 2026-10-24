"""战斗状态图标 (2026-10-23 按 exe 逆向: reverse_engineering/status_icons_decomp.txt, fn_4cc625/4cbc9d/4a3c1f.txt).

exe: 行动结束 (FUN_004cbc9d case 1) 按结算结果给每个目标 FUN_004cc625(角色, 序号) 挂图标管理实体 (表 PTR_FUN_006551ec[序号-1],
每角色每序号至多一个); FUN_004a3c1f 在状态位清掉时 FUN_004cc746 摘图标 (敌人的痲痺图标还被 0x40000 留住);
角色倒下 FUN_004cc825 全摘; 战斗结束 FUN_004cc8f5 全清.
序号 ↔ 状态位: 1 中毒 0x100 / 2 睡眠 0x200 / 3 沉默 0x400 / 4 痲痺 0x800 / 5 咀咒 0x1000 / 6 幸運 0x2000;
7,8 的管理函数一生成就自毁 (無敵/返荷 无图标); 9,10 (森巴/防禦) 的函数存在但行动结束时从不挂 → 也无图标.

  1 中毒 FUN_004ccae2: age 24 起每 24t 一个泡泡 (FUN_004cc9ac): 角色 + (rand%48-24, rand&31-16), z 0 以 2px/t 升,
    目标高 48+rand&7; 先播 e_toxic 帧 8-15 (成形, 656a14) 再循环 0-7 (656a68); 到高后每 t 以 (高-目标)/高 概率破:
    6 滴 (FUN_004d2c99: e_toxic 帧 16+rand&7, vx ±1.5 匀速, vz -1..2 重力 0.25 落向 0, 8t 后闪烁, 24t 灭).
  2 睡眠 FUN_004ccdd6: age 10 起每 20t 一个 Z (FUN_004cccca): 角色 (x+16, y+1, z+64), e_sleep 帧 4, 角 0x1000+rand&0xfff
    (右上), 每 t 角 ±0x100, x += sin, z += cos, 活 80t.
  3 沉默 FUN_004cced8: 每 t 跟随角色 (x-16, y, z+64), e_silenc 帧 9 (seq 65522c).
  4 痲痺 FUN_004cd074: 4 片 e_para (seq 656a08[rand%3]) 生在角色 ±(24..31) / +8±(6..11), 弹簧朝角色 (a 0.5..1 / 0.375..0.5),
    正向速度钳 6 / 2.
  5 咀咒 FUN_004cd471: 3 个 e_curse 帧 10+rand&3, 绕角色 (rx 32 ry 24, 相位 k·0x5555, 每 t +0x20c), z 36 弹簧朝 48 (a 0.25..0.375).
  6 幸運 FUN_004cd6e7: 3 个 e_luck 帧 0, 绕角色 (rx 32 ry 12, 每 t +0x20c), z 32.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from core.anim_engine.bytecode import tuple_to_bytecode
from core.sprites.base import TILE_W, TILE_H

if TYPE_CHECKING:
    from core.anim_engine.engine import Engine
    from core.anim_engine.entity import Entity
    from core.battle.data import BattleUnit

FP = 1 << 16
E_TOXIC, E_SLEEP, E_SILENC, E_PARA, E_CURSE, E_LUCK = 218, 219, 220, 221, 222, 223
ICON_BITS = {1: 0x100, 2: 0x200, 3: 0x400, 4: 0x800, 5: 0x1000, 6: 0x2000}
ENEMY_STUN = 0x40000            # 敌人第 6 种状态: 也挂痲痺图标
DONE = 20                       # state_code: 不阻塞回合推进

TOXIC_FORM_SEQ = [('fm', E_TOXIC, f, 1) for f in range(8, 16)] + [('exit',)]     # 656a14
TOXIC_LOOP_SEQ = [('fm', E_TOXIC, f, 2) for f in range(8)] + [('loop',)]         # 656a68
SILENCE_SEQ = [('fm', E_SILENC, 9, 10), ('loop',)]                              # 65522c
PARA_SEQS = [[('fm', E_PARA, f, 3) for f in fr] + [('loop',)] for fr in        # 656a08
             ((10, 11, 12, 13, 14, 15, 16, 17), (12, 14, 16, 15, 17, 13, 11, 10), (14, 13, 15, 12, 16, 11, 17, 10))]
LUCK_SEQ = [('fm', E_LUCK, 0, 0), ('exit',)]                                     # 655238


def _rand(battle) -> int:
    return battle.rng.randrange(0x8000)


def _sin(a: int) -> int:
    return int(math.sin((a & 0xffff) / 65536 * 2 * math.pi) * FP)


def _cos(a: int) -> int:
    return int(math.cos((a & 0xffff) / 65536 * 2 * math.pi) * FP)


def _upos(u) -> tuple[int, int, int]:
    """角色当前世界坐标 (含 seq / 受击位移) + z (exe 正向)."""
    ent = u.entity
    x = (u.x * TILE_W + TILE_W // 2) * FP
    y = (u.y * TILE_H + TILE_H // 2) * FP
    z = 0
    if ent is not None:
        x += ent.x
        y += ent.y
        z = -ent.z
    ox, oy = getattr(u, 'reaction_offset', (0, 0))
    return x + int(ox * FP), y + int(oy * FP), z


def _icon(bt, think_fn, x, y, z, seq=None, /, atlas=None, frame=0, **ud) -> "Entity":
    battle = bt
    e = battle.engine.spawn(think_fn=think_fn)
    e.flags |= 0x40
    e.x, e.y, e.z = x, y, -z
    e.state_code = DONE
    e.user_data.update(kind='hit_effect', projectile=True, status_icon=True, ez=z, draw_order=15, **ud)
    if seq is not None:
        e.atlas_slot, e.frame_idx = seq[0][1], seq[0][2]
        battle.engine.attach_seq(e, tuple_to_bytecode(seq))
    else:
        e.atlas_slot, e.frame_idx = atlas, frame
    return e


def _set_z(e, z) -> None:
    e.user_data['ez'] = z
    e.z = -z


# ---------------- 1 中毒 ----------------
def _drop_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004d2c1c: x 匀速, z 重力 0.25 落向 0; 8t 后每 t 闪烁; 24t 灭."""
    if 'vz' not in e.user_data:
        return
    ud = e.user_data
    e.x += ud['vx']
    ud['vz'] += -ud['az'] if ud['ez'] > 0 else ud['az']
    _set_z(e, ud['ez'] + ud['vz'])
    if ud['age'] > 8:
        e.flags ^= 0x40
    if ud['age'] > 0x18:
        eng.destroy(e)
    ud['age'] += 1


def _bubble_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004cc9ac: 跟随角色; 成形 seq 完 → 循环 seq; 升到目标高后随机破 (6 滴)."""
    if 'battle' not in e.user_data:
        return
    ud = e.user_data
    battle, u = ud['battle'], ud['unit']
    x, y, _ = _upos(u)
    e.x, e.y = x + ud['ox'], y + ud['oy']
    if ud['state'] == 0:
        if not e.is_playing():
            eng.attach_seq(e, tuple_to_bytecode(TOXIC_LOOP_SEQ))
            ud['state'] = 10
        return
    _set_z(e, ud['ez'] + ud['vz'])
    tz, z = ud['tz'] >> 16, ud['ez'] >> 16
    if ud['ez'] >= ud['tz'] and z > 0 and tz < _rand(battle) % z:
        for _ in range(6):
            _icon(battle, _drop_think, e.x, e.y, ud['ez'], atlas=E_TOXIC, frame=0x10 + (_rand(battle) & 7),
                  vx=((_rand(battle) % 3000) << 16) // 1000 - 0x18000,
                  vz=((_rand(battle) % 3000) << 16) // 1000 - 0x10000, az=0x4000, age=0)
        eng.destroy(e)


def _poison_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004ccae2: age 24 起每 24t 一个泡泡."""
    if 'battle' not in e.user_data:
        return
    ud = e.user_data
    battle, u = ud['battle'], ud['unit']
    if ud['age'] == ud['next']:
        x, y, _ = _upos(u)
        ox = ((_rand(battle) % 0x30) - 0x18) * FP
        oy = ((_rand(battle) & 31) - 16) * FP
        tz = ((_rand(battle) & 7) + 0x30) * FP
        _icon(battle, _bubble_think, x + ox, y + oy, 0, TOXIC_FORM_SEQ, battle=battle, unit=u, ox=ox, oy=oy,
              tz=tz, vz=2 * FP, state=0)
        ud['next'] += 0x18
    ud['age'] += 1


# ---------------- 2 睡眠 ----------------
def _z_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004ccc52: 角 ±0x100, x += sin, z += cos, 80t."""
    if 'phi' not in e.user_data:
        return
    ud = e.user_data
    ud['phi'] += 0x100 if (_rand(ud['battle']) & 1) else -0x100
    e.x += _sin(ud['phi'])
    _set_z(e, ud['ez'] + _cos(ud['phi']))
    ud['age'] += 1
    if ud['age'] > 0x50:
        eng.destroy(e)


def _sleep_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004ccdd6: age 10 起每 20t 一个 Z (FUN_004cccca)."""
    if 'battle' not in e.user_data:
        return
    ud = e.user_data
    battle, u = ud['battle'], ud['unit']
    if ud['age'] == ud['next']:
        ud['next'] = ud['age'] + 0x14
        x, y, z = _upos(u)
        phi = (_rand(battle) & 0xfff) + 0x1000
        zz = _icon(battle, _z_think, x + 16 * FP, y + FP, z + 64 * FP, atlas=E_SLEEP, frame=4, battle=battle,
                   phi=phi, age=0)
        zz.x += _sin(phi)
        _set_z(zz, zz.user_data['ez'] + _cos(phi))
    ud['age'] += 1


# ---------------- 3 沉默 ----------------
def _silence_think(e: "Entity", eng: "Engine") -> None:
    if 'unit' not in e.user_data:
        return
    x, y, z = _upos(e.user_data['unit'])
    e.x, e.y = x - 16 * FP, y
    _set_z(e, z + 64 * FP)


# ---------------- 4 痲痺 ----------------
def _para_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004cd074 state 10: 目标 = 角色, x,y 弹簧, 正向速度钳 6 / 2."""
    if 'unit' not in e.user_data:
        return
    ud = e.user_data
    x, y, _ = _upos(ud['unit'])
    for axis, v, t, a, cap in (('x', 'vx', x, 'ax', 0x60000), ('y', 'vy', y, 'ay', 0x20000)):
        ud[v] += ud[a] if getattr(e, axis) < t else -ud[a]
        setattr(e, axis, getattr(e, axis) + ud[v])
        ud[v] = min(ud[v], cap)


def _para_spawn(battle, u) -> list:
    out = []
    x, y, _ = _upos(u)
    for _ in range(4):
        ox = (_rand(battle) & 7) * FP + 0x180000
        if not (_rand(battle) & 1):
            ox = -ox
        oy = (_rand(battle) % 6) * FP + 0x60000
        if not (_rand(battle) & 1):
            oy = -oy
        out.append(_icon(battle, _para_think, x + ox, y + 8 * FP + oy, 0, PARA_SEQS[_rand(battle) % 3], unit=u,
                         vx=0, vy=0, ax=(((_rand(battle) & 0x3ff) * FP) >> 13) + 0x8000,
                         ay=(((_rand(battle) & 0x1ff) * FP) >> 13) + 0x6000))
    return out


# ---------------- 5 咀咒 / 6 幸運 (FUN_004cd387) ----------------
def _orbit_think(e: "Entity", eng: "Engine") -> None:
    """z 弹簧 (mode 0x41) + 绕角色 (mode 0x32, 角 +0x20c/t)."""
    if 'unit' not in e.user_data:
        return
    ud = e.user_data
    if ud['az']:
        ud['vz'] += ud['az'] if ud['ez'] < ud['tz'] else -ud['az']
        _set_z(e, ud['ez'] + ud['vz'])
    x, y, _ = _upos(ud['unit'])
    ud['phi'] = (ud['phi'] + 0x20c) & 0xffff
    e.x = x + _sin(ud['phi']) * ud['rx']
    e.y = y - _cos(ud['phi']) * ud['ry']


def _curse_spawn(battle, u) -> list:
    return [_icon(battle, _orbit_think, 0, 0, 0x240000, atlas=E_CURSE, frame=10 + (_rand(battle) & 3), unit=u,
                  phi=k * 0x5555, rx=0x20, ry=0x18, tz=0x300000, vz=0,
                  az=((_rand(battle) % 1000) << 16) // 8000 + 0x4000) for k in range(3)]


def _luck_spawn(battle, u) -> list:
    return [_icon(battle, _orbit_think, 0, 0, 0x200000, LUCK_SEQ, unit=u, phi=k * 0x5555, rx=0x20, ry=0xc,
                  tz=0, vz=0, az=0) for k in range(3)]


def _manager(battle, think_fn, u, **ud) -> list:
    e = battle.engine.spawn(think_fn=think_fn)
    e.flags = 0x800 | 0x10000
    e.state_code = DONE
    e.user_data.update(kind='status_icon_mgr', battle=battle, unit=u, age=0, **ud)
    return [e]


def _create(battle, u, idx: int) -> list:
    if idx == 1:
        return _manager(battle, _poison_think, u, next=0x18)
    if idx == 2:
        return _manager(battle, _sleep_think, u, next=10)
    if idx == 3:
        x, y, z = _upos(u)
        return [_icon(battle, _silence_think, x - 16 * FP, y, z + 64 * FP, SILENCE_SEQ, unit=u)]
    if idx == 4:
        return _para_spawn(battle, u)
    if idx == 5:
        return _curse_spawn(battle, u)
    if idx == 6:
        return _luck_spawn(battle, u)
    return []


def _wanted(u, idx: int) -> bool:
    if not u.alive:
        return False
    bit = ICON_BITS[idx]
    if u.status_bits & bit:
        return True
    return idx == 4 and not u.is_player and bool(u.status_bits & ENEMY_STUN)


def remove_all(battle, u) -> None:
    """FUN_004cc825: 角色倒下 → 全摘."""
    reg = getattr(battle, 'status_icons', {})
    for ents in reg.pop(id(u), {}).values():
        for e in ents:
            battle.engine.destroy(e)


def sync(battle, units=None, create: bool = True) -> None:
    """按状态位挂/摘图标. create=True = 行动结束 (FUN_004cbc9d case 1 挂 + FUN_004a3c1f 摘); False = 只摘."""
    if not hasattr(battle, 'status_icons'):
        battle.status_icons = {}
    reg = battle.status_icons
    for u in (units if units is not None else battle.all_units):
        cur = reg.setdefault(id(u), {})
        for idx in ICON_BITS:
            want = _wanted(u, idx)
            if want and idx not in cur and create:
                cur[idx] = _create(battle, u, idx)
            elif not want and idx in cur:
                for e in cur.pop(idx):
                    battle.engine.destroy(e)
        # 管理实体生成的泡泡/Z 不登记; 摘图标时它们自然播完消失 (exe 同: -2 只删直属子实体)
