"""乐神杰特 10 技能 (skill 0x25..0x2e), 2026-10-23 按 exe 逆向 (reverse_engineering/jet_decomp.txt, jet_thinks_decomp.txt,
jet_leaves_decomp.txt; 状态位见 fn_4a6efe.txt 的 skill switch). 资源: 施法 csona_m1 (fm 25, 弹吉他循环); 音符 esona00 (289);
重金屬 e221 (221); 幸運 e_luck (223); 森巴 e_power (225); 防禦 e_def (226); 光圈 ds_mag03 (229); 羽毛/闪光 e00 (247);
英雄 ejaha05 (286).

共同 (各 dispatcher case 0/10): 渐暗 → 挂施法 seq 6778d4[dir] (11 帧各 3t 循环) + 音符发射器 FUN_00505ccc(脚本) + 起手音.
  音符发射器 FUN_00505bb2: 出生后 age 2 起按脚本 (帧, 间隔) 对冒音符 (FUN_00505aa7: 施法者 x-16 y+1 z+64, 角 0xd000+rand&0xfff,
  每 t 角 ±0x100, x += sin·2 z += cos·2, 活 80t); 脚本读到 -1 → 下一拍 -100 (重金屬等 13 个音符) 并自毁.
  -100: 施法者回待机 (|= 0x10000), 各招特效登场; 收尾 0x1e 等计数 → 0x28 渐亮.

  0x25 重金屬 (FUN_00505cef): 每目标 FUN_004d2746: age 0,4,8,12 各 FUN_004d2632 光爆 (e221 seq 6568f8[rand%5] 2 帧, 0xc1),
       光爆播完 → 目标 -250 (受击 + 刺爆 655c10[6418dc[目标朝向]]) 并化为碎片 (目标 ±24..31 / +8±6..11, 弹簧回目标
       a 0.5/0.375, seq 656a08[rand%3], 1/4 概率隐身闪烁, 活 60t); 第 4 个碎片完 → -200.  状态: 敌 痲痺 0x800 2 回合 (掷骰).
  0x26 恢復樂章 (模板 FUN_004d4ee0): 每目标 3 道螺旋光柱 (FUN_004d4d93, ds_mag03) 上升→收缩→下压 (-200), 下压到 600 → -250;
       -200: 回血白字 + 32 片羽毛 (FUN_004d498c). 0x131.
  0x27 幸運進行曲 (模板 FUN_004d222e): 首目标 FUN_004d20a6 大星 + 3 小星 (e_luck) 从 z+888 以 8px/t 落到 z+432, 停, 翻, 升回;
       大星升到顶 → -200 → 渐亮. 0x132 / 0x11e,0x11f / 0x120 / 0x161.  状态: 有咀咒 0x1000 → 清; 否则 幸運 0x2000 3 回合.
  0x28 強力森巴 (FUN_005065e5): 每目标 8 个 e_power 光环 (FUN_005064f3: 半径 400 每 t -8 收到 48, 转 0x200/t, 停 60t (299),
       再 +48/t 扩到 400 → -200). 0x13d / 0x13e, -200 停 0xf9.  状态: 0x10000 3 回合.
  0x29 樂章轉音 (FUN_00506bb9): 每目标一颗光点 (FUN_00506ac7: 绕目标 半径 32→每 t -0.5, 转 0x1000/t, z 144 每 t -1, 每 t 撒
       一粒 e00 闪光 (20t)), z≤80 再等 20t → -200. 0x134 / 0x112.  状态: 战后经验全给该目标 (battle.exp_receiver).
  0x2a 強力防禦 (FUN_005071d4): 同森巴, e_def 帧 0, 0x130 / 0x13e.  状态: 0x20000 3 回合.
  0x2b 回生舞步 (模板 FUN_004fb91a): 每 (倒地) 目标 FUN_004fb8ed: 40t 内每 2t 一粒闪光从四周落下聚拢 (FUN_004fb6a7),
       86t 后 0xc5 + 爬起 seq 670904 (ps+4 13,12,5,4,3 各 8t) → 6709b8[dir] → 复活待机 → -200. 0x135 / 0x112.
  0x2c 回復優卡 (模板 FUN_004d62bc): 每目标被托起 z+48, 5t 光圈 (FUN_004d5cd5 ×8/t), 120t 后落下 → -200 白字. 0x133.
  0x2d 英雄樂章 (模板 FUN_0050eb21 = 紫河化精為氣): 每目标 ejaha05 seq 6799c8 + 0x12e, 播完 -200. 0x136.  状态: 無敵 0x4000 2 回合.
  0x2e 強力慢曲 (FUN_00507634): 每目标挂 seq 670818 (ps+2 帧 6,7 各 6t) + FUN_004f07e9 24 个 ds_mag03 光点螺旋升到 80 再落下 (0xc9/0xca);
       落地 → -200: 复活待机 + 白字 (满 HP). 0x13c.
实现: 施法 seq 在 begin_attack 挂上的同一刻由 skill_seq.SKILL_ATTACH_HOOKS 启动音符发射器; 音符完 → 协调实体跑各招.
状态的实际效果 (攻防倍率/無敵/痲痺不能动 等) 另做, 这里只置位 (core.battle.status).
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
JET_SKILLS = tuple(range(0x25, 0x2f))
CSONA_M1, ESONA00 = 25, 289
E221, E_LUCK, E_POWER, E_DEF, DS_MAG03, E00, EJAHA05 = 221, 223, 225, 226, 229, 247, 286

ST_PARALYSIS, ST_CURSE, ST_LUCK, ST_INVINCIBLE = 0x800, 0x1000, 0x2000, 0x4000
ST_SAMBA, ST_GUARD = 0x10000, 0x20000

START_SOUND = {0x25: 0x10c, 0x26: 0x131, 0x27: 0x132, 0x28: 0x13d, 0x29: 0x134, 0x2a: 0x130,
               0x2b: 0x135, 0x2c: 0x133, 0x2d: 0x136, 0x2e: 0x13c}
NOTE_SCRIPT = [0, 4, 4, 10, 5, 5, 5, 5, 4, 10, 5, 5, 5, 5, 4, 10, 5, 5, 5, 5, 4, 10, 5, 5, 5, 5, -1]
NOTE_SCRIPT_SAMBA = [0, 2, 4, 5, 5, 3, 5, 3, 4, 5, 5, 3, 5, 3, 4, 5, 5, 3, 5, 3, 4, 5, 5, 3, 5, 3, -1]
NOTE_LIFE = 0x50


# ---------------- 施法 seq ----------------
JET_DIR_BASE = (0, 16, 34, 48)
SKILL_JET_CAST = [[('fm', CSONA_M1, b + i, 3) for i in range(11)] + [('loop',)] for b in JET_DIR_BASE]   # @0x6778d4
JET_SEQS = {sid: SKILL_JET_CAST for sid in JET_SKILLS}

HEAVY_SEQS = [[('fm', E221, a, 1), ('fm', E221, b, 1), ('exit',)] for a, b in ((5, 0), (6, 1), (7, 2), (8, 3), (9, 4))]  # 6568f8
SHARD_SEQS = [[('fm', E221, f, 3) for f in fr] + [('loop',)] for fr in                                                  # 656a08
              ((10, 11, 12, 13, 14, 15, 16, 17), (12, 14, 16, 15, 17, 13, 11, 10), (14, 13, 15, 12, 16, 11, 17, 10))]
FEATHER_SEQS = [[('fm', E00, f, 1) for f in (b, b + 1, b + 2)] + [('loop',)] for b in (30, 33, 36, 39)]                 # 656abc
POWER_SEQ = [('fm', E_POWER, f, 1) for f in range(8)] + [('loop',)]                                                     # 677938
GUARD_SEQ = [('fm', E_DEF, 0, 1), ('exit',)]                                                                           # 6779c4
MAG_SEQ = [('fm', DS_MAG03, 3, 1), ('fm', DS_MAG03, 1, 2), ('fm', DS_MAG03, 4, 1), ('fm', DS_MAG03, 2, 2),
           ('fm', DS_MAG03, 0, 1), ('loop',)]                                                                          # 6561a4
SPARKLE_FALL_SEQ = [('fm', E00, f, 2) for f in (5, 6, 7, 8, 9)] + [('loop',)]                                           # 6720cc
LUCK_MAIN_FALL = [('fm', E_LUCK, 5, 0), ('exit',)]           # 65685c
LUCK_MAIN_SPIN = [('fm', E_LUCK, 6, 12), ('fm', E_LUCK, 7, 12), ('loop',)]   # 656868
LUCK_SMALL_FALL = [('fm', E_LUCK, f, 1) for f in (1, 2, 3)] + [('loop',)]    # 656830
LUCK_SMALL_LAND = [('fm', E_LUCK, 0, 0), ('exit',)]           # 656850
HERO_SEQ = [('fm', EJAHA05, f, 1) for f in (7, 6, 0, 1, 2, 3, 4, 5, 7)] + [('exit',)]   # 6799c8
SLOW_RISE_SEQ = [('idle', 2, 6, 6), ('idle', 2, 7, 6), ('jump', -500), ('exit',)]     # 670818 (目标自身 ps+2)
REVIVE_UP_SEQ = [('idle', 4, f, 8) for f in (13, 12, 5, 4, 3)] + [('exit',)]          # 670904 (目标 ps+4)
REVIVE_TURN_SEQS = [[('idle', 0, f, 3) for f in (6, 11, 12, 17, 0)] + [('exit',)],     # 6709b8[dir] (目标 ps+0)
                    [('idle', 0, 6, 3), ('exit',)],
                    [('idle', 0, f, 0) for f in (6, 17, 12)] + [('exit',)],
                    [('idle', 0, f, 0) for f in (6, 23, 18)] + [('exit',)]]


# ---------------- 工具 ----------------
def _sfx(battle, sid: int) -> None:
    battle.engine._emit('sound_play', None, sid)


def _sfx_stop(battle, sid: int) -> None:
    battle.engine._emit('sound_stop', None, sid)


def _rand(battle) -> int:
    return battle.rng.randrange(0x8000)


def _sin(a: int) -> int:
    return int(math.sin((a & 0xffff) / 65536 * 2 * math.pi) * FP)


def _cos(a: int) -> int:
    return int(math.cos((a & 0xffff) / 65536 * 2 * math.pi) * FP)


def _pos(unit) -> tuple[int, int]:
    ent = unit.entity
    x = (unit.x * TILE_W + TILE_W // 2) * FP
    y = (unit.y * TILE_H + TILE_H // 2) * FP
    if ent is not None and unit.reaction_seq is None:
        x += ent.x
        y += ent.y
    return x, y


def _dir(unit) -> int:
    from core.attack_seq import facing_to_atk_index
    return facing_to_atk_index(unit.facing)


def _fx(bt, think_fn, x: int, y: int, z: int, seq=None, /, atlas: int | None = None, frame: int = 0, **ud) -> "Entity":
    """z 用 16.16 正向 (exe 约定, 上为正)."""
    e = bt.engine.spawn(think_fn=think_fn)
    e.flags |= 0x40
    e.x, e.y = x, y
    e.user_data.update(kind='hit_effect', projectile=True, ez=z, **ud)
    e.z = -z
    if seq is not None:
        e.atlas_slot, e.frame_idx = seq[0][1], seq[0][2]
        bt.engine.attach_seq(e, tuple_to_bytecode(seq))
    else:
        e.atlas_slot, e.frame_idx = atlas, frame
    return e


def _set_z(e: "Entity", z: int) -> None:
    e.user_data['ez'] = z
    e.z = -z


# ---------------- 音符 ----------------
def _note_think(e: "Entity", eng: "Engine") -> None:
    """FUN_00505a2f: 角 ±0x100 随机游走, x += sin·2, z += cos·2, age > 80 自毁."""
    ud = e.user_data
    if 'note' not in ud:
        return
    _note_step(e, ud['battle'], random_walk=True)
    ud['age'] += 1
    if ud['age'] > NOTE_LIFE:
        eng.destroy(e)


def _note_step(e: "Entity", battle, random_walk: bool) -> None:
    ud = e.user_data
    if random_walk:
        ud['phi'] += 0x100 if (_rand(battle) & 1) else -0x100
    e.x += _sin(ud['phi']) * 2
    _set_z(e, ud['ez'] + _cos(ud['phi']) * 2)


def _spawn_note(battle, caster, frame: int) -> None:
    """FUN_00505aa7."""
    x, y = _pos(caster)
    phi = (_rand(battle) & 0xfff) + 0xd000
    e = _fx(battle, _note_think, x - 16 * FP, y + FP, 64 * FP, atlas=ESONA00, frame=frame, note=True, battle=battle,
            phi=phi, age=0)
    _note_step(e, battle, random_walk=False)        # 出生调一次 FUN_004c3211
    _note_step(e, battle, random_walk=True)         # 下标在发射器之后, 出生 tick 再 think 一次 (实录首帧 x-20 z65)


def _emitter_think(e: "Entity", eng: "Engine") -> None:
    """FUN_00505bb2: age == next 时冒音符; 脚本 -1 → 下一拍发 -100 (协调实体登场) 并自毁."""
    ud = e.user_data
    if 'emitter' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    if ud['done']:
        _on_impact(battle, caster)
        eng.destroy(e)
        return
    if ud['age'] == ud['next']:
        s = ud['script']
        _spawn_note(battle, caster, s[ud['i']])
        ud['next'] = ud['age'] + s[ud['i'] + 1]
        ud['i'] += 2
        if s[ud['i']] == -1:
            ud['done'] = True
    ud['age'] += 1


def on_attach(battle, caster) -> None:
    """case 10: 挂施法 seq 的同一刻启动音符发射器 + 起手音."""
    sid = caster.pending_skill_id
    e = battle.engine.spawn(think_fn=_emitter_think)
    e.flags = 0x800 | 0x10000
    e.user_data.update(kind='jet_emitter', projectile=True, emitter=True, battle=battle, caster=caster, age=0, next=2,
                       i=0, done=False, script=NOTE_SCRIPT_SAMBA if sid == 0x28 else NOTE_SCRIPT)
    _sfx(battle, START_SOUND[sid])
    _emitter_think(e, battle.engine)                 # 出生当 tick 就 think (实录 jet_26: 首音符 attach+2)


# ---------------- 目标 / 状态 ----------------
def _targets(battle, caster, sid: int) -> list:
    """dispatcher 目标表: 范围内我方 (复活类含倒地者); 重金屬 = 敌方."""
    enemy = sid == 0x25
    revive = sid in (0x2b, 0x2e)
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
            if enemy:
                if not u.is_player and u.alive and u.is_player != caster.is_player:
                    out.append(u)
            elif u.is_player == caster.is_player and (u.alive or revive):
                if sid == 0x2b and u.alive:
                    continue                                  # 回生舞步只救倒地者
                out.append(u)
    return out


def _apply_statuses(battle, caster, sid: int, targets: list) -> None:
    """FUN_004a6efe 的 skill switch (只置位, 效果另做)."""
    from core.battle.status import apply_status, has_status, clear_status
    for t in targets:
        if sid == 0x27:
            if has_status(t, ST_CURSE):
                clear_status(t, ST_CURSE)
            else:
                apply_status(t, ST_LUCK, 3)
        elif sid == 0x28:
            apply_status(t, ST_SAMBA, 3)
        elif sid == 0x2a:
            apply_status(t, ST_GUARD, 3)
        elif sid == 0x2d:
            apply_status(t, ST_INVINCIBLE, 2)
        elif sid == 0x29:
            battle.exp_receiver = t                           # DAT_007d9900: 战后经验全给此人
        elif sid == 0x25:
            # 命中率 clamp 10..90 (原版用双方智慧/魔防, 这里占位 50%); 敌人类型标志 0x20 免疫
            if not (t.type_flags & 0x20) and battle.rng.randrange(101) < 50:
                apply_status(t, ST_PARALYSIS, 2)
                battle._log(f"{t.name} 痲痺 (2 回合)")


def _heal(battle, caster, t, full: bool = False) -> None:
    from core.battle.combat import push_damage_event
    from core.battle.data import DamageEvent
    from core.skill_seq import heal_amount
    before = t.hp
    t.hp = t.max_hp if full else min(t.max_hp, t.hp + heal_amount(caster, caster.pending_skill_id))
    t.shown_hp_override = None
    push_damage_event(battle, t, DamageEvent(t.hp - before, t.hp, t.x, t.y, heal=True))


def _revive(battle, caster, t, full: bool) -> None:
    from core.skill_seq import heal_amount
    if t.alive:
        if full:
            _heal(battle, caster, t, full=True)
        return
    t.hp = t.max_hp if full else min(t.max_hp, heal_amount(caster, caster.pending_skill_id))
    t.shown_hp_override = None
    t.settle_pending = False
    t.death_anim_time_ms = -1
    t.reaction_seq = None
    if full:
        from core.battle.combat import push_damage_event
        from core.battle.data import DamageEvent
        push_damage_event(battle, t, DamageEvent(t.hp, t.hp, t.x, t.y, heal=True))


# ---------------- 协调实体 ----------------
def _coord_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'jet' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    if ud['live'] > 0 or getattr(battle, 'float_pending', 0) > 0:
        return
    if any(v.reaction_seq is not None for v in ud['targets']):
        return
    ud['unit'] = caster
    eng._signal(e, SIG_END)
    eng.destroy(e)


def _on_impact(battle, caster) -> None:
    """-100: 施法者回待机, 状态置位, 各招特效."""
    sid = caster.pending_skill_id
    targets = _targets(battle, caster, sid)
    if caster.entity is not None:
        caster.entity.seq = b''
        caster.entity.flags &= ~0x20000
    caster.cast_hold = False
    _apply_statuses(battle, caster, sid, targets)
    coord = battle.engine.spawn(think_fn=_coord_think)
    coord.flags = 0x800 | 0x10000
    coord.user_data.update(kind='jet_coord', projectile=True, jet=True, battle=battle, caster=caster, sid=sid,
                           targets=targets, live=0)
    SPAWN[sid](battle, caster, coord, targets)


def _done(coord) -> None:
    coord.user_data['live'] -= 1


# ---------- 0x25 重金屬 ----------
def _shard_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004d2418: 先播光爆 seq; 完 → 目标 -250 + 变碎片 (弹簧回目标, 闪烁, 60t)."""
    ud = e.user_data
    if 'shard' not in ud:
        return
    battle, victim = ud['battle'], ud['victim']
    if ud['state'] == 0:
        ud['age'] += 1                                  # +0x144 自出生计
        if e.is_playing():
            return
        from core.battle import combat
        if victim.alive:
            combat.set_reaction(victim, "hit", None)
            _spark_dir(battle, victim, (1, 0, 3, 2)[_dir(victim)])
        vx, vy = _pos(victim)
        ox = (_rand(battle) & 7) * FP + 24 * FP
        if not (_rand(battle) & 1):
            ox = -ox
        oy = (_rand(battle) % 6) * FP + 6 * FP
        if not (_rand(battle) & 1):
            oy = -oy
        e.x, e.y = vx + ox, vy + 8 * FP + oy
        _set_z(e, 0)
        ud.update(state=10, tx=vx, ty=vy + 8 * FP, vx=0, vy=0, ax=0x8000, ay=0x6000)
        eng.attach_seq(e, tuple_to_bytecode(SHARD_SEQS[_rand(battle) % 3]))
        return
    for axis, v, t, a in (('x', 'vx', 'tx', 'ax'), ('y', 'vy', 'ty', 'ay')):
        ud[v] += ud[a] if getattr(e, axis) < ud[t] else -ud[a]
        setattr(e, axis, getattr(e, axis) + ud[v])
    if _rand(battle) & 3 == 0:
        e.flags &= ~0x40
    else:
        e.flags |= 0x40
    ud['age'] += 1
    if ud['age'] > 0x3b:
        if ud.get('last'):
            _done(ud['coord'])
        eng.destroy(e)


def _spark_dir(battle, victim, d: int) -> None:
    from core.bosan_skills import _spark
    _spark(battle, d, victim)


def _heavy_spawner_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004d26b0: age 0,4,8,12 各一个光爆 (FUN_004d2632), 第 4 个标记为最后."""
    ud = e.user_data
    if 'heavy' not in ud:
        return
    battle, victim = ud['battle'], ud['victim']
    if ud['age'] == ud['next']:
        vx, vy = _pos(victim)
        s = _fx(battle, _shard_think, vx, vy, 0, HEAVY_SEQS[_rand(battle) % 5], shard=True, battle=battle,
                victim=victim, coord=ud['coord'], state=0, age=0)
        _sfx(battle, 0xc1)
        ud['n'] += 1
        if ud['n'] == 4:
            s.user_data['last'] = True
            eng.destroy(e)
            return
        ud['next'] += 4
    ud['age'] += 1


def _spawn_heavy(battle, caster, coord, targets) -> None:
    for v in targets:
        e = battle.engine.spawn(think_fn=_heavy_spawner_think)
        e.flags = 0x800 | 0x10000
        e.user_data.update(kind='jet_heavy', projectile=True, heavy=True, battle=battle, victim=v, coord=coord,
                           age=0, next=0, n=0)
        coord.user_data['live'] += 1


# ---------- 光圈上升粒子 (FUN_004d4819 / 4d47d4) ----------
def _rise_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'rise' not in ud:
        return
    for axis, v in (('x', 'vx'), ('y', 'vy')):
        setattr(e, axis, getattr(e, axis) + ud[v])
    ud['vz'] += ud['az'] if ud['ez'] < 0 else -ud['az']
    _set_z(e, ud['ez'] + ud['vz'])
    ud['age'] += 1
    if ud['age'] > 0x30 or ud['ez'] < FP:
        eng.destroy(e)


def _spawn_rise(battle, src: "Entity") -> None:
    """FUN_004d4819: 源位置, vx/vy = 0x4000/(rand&3+1), vz -2 (向下), seq 656abc[rand&3]."""
    vx = 0x4000 // ((_rand(battle) & 3) + 1)
    vy = 0x4000 // ((_rand(battle) & 3) + 1)
    _fx(battle, _rise_think, src.x, src.y, src.user_data['ez'], FEATHER_SEQS[_rand(battle) & 3], rise=True,
        vx=vx, vy=vy, vz=-2 * FP, az=0, age=0)


# ---------- 0x26 恢復樂章 (模板 FUN_004d4ee0) ----------
def _pillar_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004d4acf: 螺旋上升 (z +1, 角速 +0x20 至 0x1000), 偶数 tick 撒粒子; z>96 → 半径每 t -1 收缩; 收到 0 → -200 (首道);
    再半径 +10,+20.. 外扩, >599 → -250 (首道) 自毁."""
    ud = e.user_data
    if 'pillar' not in ud:
        return
    battle = ud['battle']
    st = ud['state']
    if st == 0:
        _set_z(e, ud['ez'] + FP)
        ud['spd'] = min(ud['spd'] + 0x20, 0x1000)
        ud['phi'] = (ud['phi'] + ud['spd']) & 0xffff
        _orbit(e)
        if ud['age'] % 2 == 0:
            _spawn_rise(battle, e)
        if ud['ez'] > 0x600000:
            ud['state'] = 10
    elif st == 10:
        ud['phi'] = (ud['phi'] + ud['spd']) & 0xffff
        ud['rx'] = ud['ry']
        ud['ry'] -= 1
        _orbit(e)
        if ud['rx'] < 1:
            if ud.get('lead'):
                _heal_settle(battle, ud['coord'], ud['target'])
                _sfx(battle, 0xca)
            ud['grow'] = 0
            ud['state'] = 20
    elif st == 20:
        ud['grow'] += 10
        ud['ry'] += ud['grow']
        ud['rx'] = ud['ry']
        _orbit(e)
        if ud['rx'] > 599:
            if ud.get('lead'):
                _done(ud['coord'])
            eng.destroy(e)
            return
    ud['age'] += 1


def _orbit(e: "Entity") -> None:
    """FUN_004c3211 mode 2 (x,y): x = cx + sin φ·rx, y = cy - cos φ·ry."""
    ud = e.user_data
    e.x = ud['cx'] + _sin(ud['phi']) * ud['rx']
    e.y = ud['cy'] - _cos(ud['phi']) * ud['ry']


def _heal_settle(battle, coord, t) -> None:
    """-200: 目标回待机 + 回血白字 + 32 片羽毛 (FUN_004d498c)."""
    _release_pose(t)
    _heal(battle, coord.user_data['caster'], t)
    x, y = _pos(t)
    for _ in range(32):
        vx = ((_rand(battle) & 31) - 16) * FP >> 4
        vy = ((_rand(battle) & 31) - 16) * FP >> 4
        vz = ((_rand(battle) & 63) * FP) >> 4
        _fx(battle, _feather_think, x, y, 128 * FP, FEATHER_SEQS[_rand(battle) & 3], feather=True, vx=vx, vy=vy,
            vz=vz, az=0x8000, age=0)


def _feather_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004d4920 (同 M凤凰羽毛, a 0.5): 弹簧朝 z0, vz 恰 0 时 a/4; age>48 或 z<1 自毁."""
    ud = e.user_data
    if 'feather' not in ud:
        return
    e.x += ud['vx']
    e.y += ud['vy']
    ud['vz'] += -ud['az'] if ud['ez'] > 0 else ud['az']
    _set_z(e, ud['ez'] + ud['vz'])
    if ud['vz'] == 0:
        ud['az'] >>= 2
    if ud['age'] > 0x30 or ud['ez'] < FP:
        eng.destroy(e)
    ud['age'] += 1


HEAL_POSE_SEQS = [[('idle', 2, f, 5), ('idle', 2, f + 1, 5), ('exit',)] for f in (2, 6, 10, 14)]   # 655aa8[dir] (目标 ps+2)


def _hold_pose(battle, t, seqs) -> None:
    """模板 -100: 目标挂姿势 seq 并保持末帧 (清 0x10000), 到 -200 才回待机."""
    _attach_unit_seq(battle, t, seqs[_dir(t)])
    t.cast_hold = True


def _release_pose(t) -> None:
    t.cast_hold = False


def _spawn_heal_pillars(battle, caster, coord, targets) -> None:
    for t in targets:
        _hold_pose(battle, t, HEAL_POSE_SEQS)
        cx, cy = _pos(t)
        phi = ((_rand(battle) & 0x3ff) << 16) >> 10
        for k in range(3):
            e = _fx(battle, _pillar_think, cx, cy, 0, MAG_SEQ, pillar=True, battle=battle, coord=coord, target=t,
                    cx=cx, cy=cy, rx=0x20, ry=0x18, phi=phi & 0xffff, spd=0x400, state=0, age=0, lead=(k == 2))
            _orbit(e)
            _pillar_think(e, battle.engine)          # 出生 tick 就 think (实录首帧 z=1)
            phi += 0x5555
        coord.user_data['live'] += 1
    _sfx(battle, 0xc9)


# ---------- 0x28 強力森巴 / 0x2a 強力防禦 (FUN_005064f3 / 5070d8) ----------
def _ring_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'ring' not in ud:
        return
    battle = ud['battle']
    ud['phi'] = (ud['phi'] + 0x200) & 0xffff
    st = ud['state']
    if st == 0:
        ud['ry'] -= 8
        ud['rx'] = ud['ry']
        _orbit(e)
        if ud['rx'] < 0x31:
            ud.update(rx=0x30, ry=0x30, until=ud['age'] + 0x3c, state=10)
    elif st == 10:
        _orbit(e)
        if ud['age'] == ud['until']:
            if ud.get('lead'):
                _sfx(battle, 299)
            ud['state'] = 20
    else:
        ud['ry'] += 0x30
        ud['rx'] = ud['ry']
        _orbit(e)
        if ud['rx'] > 399:
            if ud.get('lead'):
                if ud['sid'] == 0x28:
                    _sfx_stop(battle, 0xf9)
                _done(ud['coord'])
            eng.destroy(e)
            return
    ud['age'] += 1


def _spawn_rings(battle, caster, coord, targets) -> None:
    sid = coord.user_data['sid']
    seq = POWER_SEQ if sid == 0x28 else GUARD_SEQ
    for t in targets:
        x, y = _pos(t)
        cy = y + 1000 * FP
        for k in range(8):
            e = _fx(battle, _ring_think, x, cy, 0, seq, ring=True, battle=battle, coord=coord, sid=sid,
                    cx=x, cy=cy, rx=400, ry=400, phi=(k << 13), state=0, age=0, lead=(k == 7))
            _set_z(e, 0x4080000)                         # 目标 (x, y+1000, z+1032) = 画在目标上方 32px
            _orbit(e)
        coord.user_data['live'] += 1
        if sid == 0x2a:
            _sfx(battle, 0x13e)
    if sid == 0x28:
        _sfx(battle, 0x13e)


# ---------- 0x29 樂章轉音 (FUN_00506ac7) ----------
def _spiral_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'spiral' not in ud:
        return
    battle = ud['battle']
    if ud['state'] == 0:
        ud['r16'] -= 0x8000
        ud['rx'] = ud['r16'] >> 16
        ud['ry'] = ud['rx'] // 2
        ud['phi'] = (ud['phi'] + 0x1000) & 0xffff
        _set_z(e, ud['ez'] - FP)
        _orbit(e)
        _fx(battle, _sparkle_think, e.x, e.y, ud['ez'], FEATHER_SEQS[_rand(battle) & 3], sparkle=True, age=0)
        if ud['ez'] < 0x500001:
            ud.update(until=ud['age'] + 0x14, state=10)
    elif ud['age'] == ud['until']:
        _done(ud['coord'])
        eng.destroy(e)
        return
    ud['age'] += 1


def _sparkle_think(e: "Entity", eng: "Engine") -> None:
    """FUN_005068f7: 原地, age > 19 自毁."""
    ud = e.user_data
    if 'sparkle' not in ud:
        return
    if ud['age'] > 0x13:
        eng.destroy(e)
    ud['age'] += 1


def _spawn_spirals(battle, caster, coord, targets) -> None:
    for t in targets:
        cx, cy = _pos(t)
        phi = ((_rand(battle) & 0x3ff) << 16) >> 10
        e = _fx(battle, _spiral_think, cx, cy, 0x900000, None, atlas=E00, frame=0, spiral=True, battle=battle,
                coord=coord, cx=cx, cy=cy, r16=0x200000, rx=32, ry=16, phi=phi & 0xffff, state=0, age=0)
        e.flags &= ~0x40                                       # 本体不画 (只撒闪光)
        _orbit(e)
        coord.user_data['live'] += 1
        _sfx(battle, 0x112)


# ---------- 0x27 幸運進行曲 (模板 FUN_004d222e / 4d20a6) ----------
def _luck_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004d1f34 (大星) / 4d1dc0 (小星): 以 8px/t 落到 z 目标 → 等 → 换 seq → 等 → 速度反向升回 → 大星发 -200."""
    ud = e.user_data
    if 'luck' not in ud:
        return
    battle = ud['battle']
    st = ud['state']
    age = ud['age']
    if st == 0:
        _set_z(e, ud['ez'] + ud['vz'])
        if ud['ez'] <= ud['tz']:
            if ud['small'] and ud.get('flag'):
                _sfx(battle, 0x161)
            ud['state'] = 10
    elif st == 10:
        if ud['wait1'] <= age:
            if ud['small']:
                eng.attach_seq(e, tuple_to_bytecode(LUCK_SMALL_LAND))
                _sfx(battle, 0x120)
            else:
                _sfx_stop(battle, 0x11f)
                eng.attach_seq(e, tuple_to_bytecode(LUCK_MAIN_SPIN))
            ud['state'] = 20
    elif st == 20:
        if ud['wait2'] <= age:
            if not ud['small']:
                _sfx_stop(battle, 0x161)
            ud['vz'] = -ud['vz']
            ud['state'] = 30
    else:
        _set_z(e, ud['ez'] + ud['vz'])
        if ud['ez'] > 0x377ffff:
            if not ud['small']:
                _done(ud['coord'])
            eng.destroy(e)
            return
    ud['age'] += 1


def _spawn_luck(battle, caster, coord, targets) -> None:
    if not targets:
        return
    t = targets[0]
    x, y = _pos(t)
    y += 0x1980000
    common = dict(luck=True, battle=battle, coord=coord, vz=-8 * FP, tz=432 * FP, state=0, age=0)
    _fx(battle, _luck_think, x, y, 0x3780000, LUCK_MAIN_FALL, small=False, wait1=0xd4, wait2=300, **common)
    for k in range(3):
        _fx(battle, _luck_think, x - 0x100000 + k * 0x100000, y, 0x3780000, LUCK_SMALL_FALL, small=True,
            wait1=k * 0x1e + 0x78, wait2=300, flag=(k == 2), **common)
    coord.user_data['live'] += 1
    _sfx(battle, 0x11e)
    _sfx(battle, 0x11f)


# ---------- 0x2b 回生舞步 (模板 FUN_004fb91a / 4fb8ed) ----------
def _gather_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004fb4da: 先从 z64 每 t 落 2; 落地后匀速 (横 8 / 竖 6) 聚向目标, 到达自毁."""
    from core.pao_skills import _cdbc2
    ud = e.user_data
    if 'gather' not in ud:
        return
    if ud['state'] == 0:
        _set_z(e, ud['ez'] - 2 * FP)
        for axis, v, t, a in (('x', 'vx0', 'tx', 0x20000), ('y', 'vy0', 'ty', 0x18000)):   # mode 0x31 弹簧 a 2 / 1.5
            ud[v] += a if getattr(e, axis) < ud[t] else -a
            setattr(e, axis, getattr(e, axis) + ud[v])
        if ud['ez'] < 1:
            _set_z(e, 0x5c0000)                         # exe 把 z 设成 0x5c0000 (92px) 后横飞聚拢
            dx, dy = ud['tx'] - e.x, ud['ty'] - e.y
            if abs(dy) < abs(dx):
                vx = 8 * FP if dx >= 1 else -8 * FP
                vy = int(dy / max(1, abs(dx) >> 19))
            else:
                vy = 6 * FP if dy >= 1 else -6 * FP
                vx = int(dx / max(1, abs(dy) // (6 * FP)))
            ud.update(vx=vx, vy=vy, axes=0x30, state=10)
    elif _cdbc2(e):
        eng.destroy(e)


def _revive_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004fb7c3: age<40 奇数 tick 撒闪光; >86 → 0xc5 + 爬起 seq → 转身 seq → 复活待机 → -200."""
    ud = e.user_data
    if 'revive' not in ud:
        return
    battle, t = ud['battle'], ud['target']
    age = ud['age']
    if ud['state'] == 0:
        if age < 0x28 and age & 1:
            _spawn_gather(battle, t)
        if age > 0x56:
            _sfx(battle, 0xc5)
            _revive(battle, ud['coord'].user_data['caster'], t, full=False)
            _attach_unit_seq(battle, t, REVIVE_UP_SEQ)
            ud['state'] = 10
    elif ud['state'] == 10:
        if not t.entity.is_playing():
            _attach_unit_seq(battle, t, REVIVE_TURN_SEQS[_dir(t)])
            ud['state'] = 20
    elif not t.entity.is_playing():
        _done(ud['coord'])
        eng.destroy(e)
        return
    ud['age'] += 1


def _attach_unit_seq(battle, unit, seq) -> None:
    if unit.entity is None:
        unit.entity = battle.engine.spawn()
        unit.entity.user_data = {'unit': unit}
    battle.engine.attach_seq(unit.entity, tuple_to_bytecode(seq))


def _spawn_gather(battle, t) -> None:
    """FUN_004fb6a7: 目标 ±(32..63, 24..47) z64, 落地后聚向目标, seq 656abc[rand&3]."""
    x, y = _pos(t)
    u = _rand(battle) & 31
    ox = (u + 32) * FP
    oyv = _rand(battle) % 24 + 24
    oy = oyv * FP
    if not (_rand(battle) & 1):
        ox = -ox
    if not (_rand(battle) & 1):
        oy = -oy
    _fx(battle, _gather_think, x + ox, y + oy, 64 * FP, FEATHER_SEQS[_rand(battle) & 3], gather=True, tx=x, ty=y,
        vx0=0, vy0=0, state=0)


def _spawn_revive(battle, caster, coord, targets) -> None:
    for t in targets:
        e = battle.engine.spawn(think_fn=_revive_think)
        e.flags = 0x800 | 0x10000
        e.user_data.update(kind='jet_revive', projectile=True, revive=True, battle=battle, coord=coord, target=t,
                           state=0, age=0)
        coord.user_data['live'] += 1
        _sfx(battle, 0x112)


# ---------- 0x2c 回復優卡 (模板 FUN_004d62bc / 4d6299 / 4d5f4b) ----------
def _yuka_think(e: "Entity", eng: "Engine") -> None:
    """目标 z 弹簧升到 48 → 5t 每 t 8 个光圈 → 120t → 落回 → -200 白字."""
    ud = e.user_data
    if 'yuka' not in ud:
        return
    battle, t = ud['battle'], ud['target']
    ent = t.entity
    st = ud['state']
    age = ud['age']
    if st == 0:
        ud.update(tz=48 * FP, vz=FP, az=0, uz=0, state=10)
    elif st == 10:
        ud['vz'] += ud['az'] if ud['uz'] < ud['tz'] else -ud['az']
        ud['uz'] += ud['vz']
        if ud['uz'] > 0x2fffff:
            ud.update(az=0x1999, n=0, until=age + 5, state=20)
            if ud.get('first'):
                _sfx(battle, 0xc9)
    elif st == 20:
        _yuka_rings(battle, t, ud['n'], 5, ud)
        ud['n'] += 1
        ud['vz'] += ud['az'] if ud['uz'] < ud['tz'] else -ud['az']
        ud['uz'] += ud['vz']
        if age == ud['until']:
            ud.update(until=age + 0x78, state=30)      # (第一次 0x86a768 脉冲: 光圈此时都在 state 0, 不看)
    elif st == 30:
        ud['vz'] += ud['az'] if ud['uz'] < ud['tz'] else -ud['az']
        ud['uz'] += ud['vz']
        if age == ud['until']:
            ud.update(tz=0, vz=-FP, az=0, state=40)
            ud['release'] = True                        # 0x86a768 = 1: 光圈散 (n==2 那批外扩)
            _heal(battle, ud['coord'].user_data['caster'], t)       # -200 白字
            _done(ud['coord'])                                      # -250
            if ud.get('first'):
                _sfx(battle, 0xca)
    else:
        ud['uz'] += ud['vz']
        if ud['uz'] < 0:
            ud['uz'] = 0
            if ent is not None:
                ent.z = 0
            eng.destroy(e)
            return
    if ent is not None:
        ent.z = -ud['uz']
    ud['age'] += 1


def _yuka_rings(battle, t, n: int, total: int, owner_ud) -> None:
    """FUN_004d5cd5: 8 个 ds_mag03 绕目标, φ = k<<13, 高度角 a = int(0.5/(total+1)·65536)·(n+1)."""
    x, y = _pos(t)
    a = int(0.5 / (total + 1) * 65536) * (n + 1)
    rx0 = _sin(a) * 0x30
    ry0 = _sin(a) * 0x24
    for k in range(8):
        e = _fx(battle, _yuka_ring_think, x, y, 0, MAG_SEQ, yring=True, owner=owner_ud, target=t,
                phi=(k << 13), a=a, spd=((_rand(battle) & 63) * FP >> 12) + 0x400,
                r16x=abs(rx0) << 2, r16y=abs(ry0) << 2, cx=x, cy=y, rx=0, ry=0, age=0, burst=(n == 2))
        e.user_data['dx'] = e.user_data['r16x'] >> 7
        e.user_data['dy'] = e.user_data['r16y'] >> 7
        _yuka_ring_place(e)


def _yuka_ring_place(e) -> None:
    ud = e.user_data
    t = ud['target']
    ud['cx'], ud['cy'] = _pos(t)
    tz = (-t.entity.z if t.entity is not None else 0) + 0x300000
    ud['phi'] = (ud['phi'] - ud['spd'] + 0x10000) & 0xffff
    _orbit(e)
    _set_z(e, tz + _cos(ud['a']) * 0x30)


def _yuka_ring_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004d5a59: 跟随目标转圈, 半径衰减 (每 t -1/128); age 86 等释放; 释放后外扩 (+64/+48), >500 自毁."""
    ud = e.user_data
    if 'yring' not in ud:
        return
    st = ud.get('state', 0)
    if st in (0, 10):
        _yuka_ring_place(e)
        if st == 0:
            ud['rx'] = ud['r16x'] >> 16
            ud['ry'] = ud['r16y'] >> 16
            ud['r16x'] -= ud['dx']
            ud['r16y'] -= ud['dy']
            if ud['age'] == 0x56:
                ud['state'] = 10
        elif ud['owner'].get('release'):
            if not ud['burst']:
                eng.destroy(e)
                return
            ud['state'] = 20
    else:
        ud['rx'] += 0x40
        ud['ry'] += 0x30
        _orbit(e)
        if ud['burst']:
            _spawn_rise(ud['owner']['battle'], e)
        if ud['ry'] > 500:
            eng.destroy(e)
            return
    ud['age'] += 1


def _spawn_yuka(battle, caster, coord, targets) -> None:
    for i, t in enumerate(targets):
        e = battle.engine.spawn(think_fn=_yuka_think)
        e.flags = 0x800 | 0x10000
        e.user_data.update(kind='jet_yuka', projectile=True, yuka=True, battle=battle, coord=coord, target=t,
                           state=0, age=0, first=(i == 0))
        coord.user_data['live'] += 1


# ---------- 0x2d 英雄樂章 (模板 FUN_0050eb21 = 紫河化精為氣) ----------
def _hero_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'hero' not in ud or e.is_playing():
        return
    _done(ud['coord'])
    eng.destroy(e)


def _spawn_hero(battle, caster, coord, targets) -> None:
    for t in targets:
        x, y = _pos(t)
        _fx(battle, _hero_think, x, y + FP, 0, HERO_SEQ, hero=True, coord=coord)
        coord.user_data['live'] += 1
        _sfx(battle, 0x12e)


# ---------- 0x2e 強力慢曲 (FUN_00507634 / 4f07e9 / 4f04b4) ----------
def _slow_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004f04b4: 上升 (z+1, 角速 +0x20 至 0x1000), 每 4 个之一撒粒子; z>80 → 换 seq 6720cc, 下落 (z-1.5, 角速随机减,
    半径 +1/+0.75); 落地 → 首者 -200 (复活 + 白字)."""
    ud = e.user_data
    if 'slow' not in ud:
        return
    battle = ud['battle']
    if ud['state'] == 0:
        _set_z(e, ud['ez'] + FP)
        ud['spd'] = min(ud['spd'] + 0x20, 0x1000)
        ud['phi'] = (ud['phi'] + ud['spd']) & 0xffff
        _orbit(e)
        if ud['emit']:
            _spawn_rise(battle, e)
        if ud['ez'] > 0x500000:
            ud['r16x'], ud['r16y'] = ud['rx'] << 16, ud['ry'] << 16
            eng.attach_seq(e, tuple_to_bytecode(SPARKLE_FALL_SEQ))
            if ud.get('lead'):
                _sfx(battle, 0xca)
            ud['state'] = 10
    else:
        _set_z(e, ud['ez'] - 0x18000)
        if _rand(battle) & 1:
            ud['spd'] = max(ud['spd'] - 0x80, 0x100)
        ud['phi'] = (ud['phi'] + ud['spd']) & 0xffff
        ud['r16x'] += FP
        ud['r16y'] += 0xc000
        ud['rx'], ud['ry'] = ud['r16x'] >> 16, ud['r16y'] >> 16
        _orbit(e)
        if ud['ez'] < 1:
            if ud.get('lead'):
                t = ud['target']
                _revive(battle, ud['coord'].user_data['caster'], t, full=True)
                _done(ud['coord'])
            eng.destroy(e)


def _spawn_slow(battle, caster, coord, targets) -> None:
    for t in targets:
        _attach_unit_seq(battle, t, SLOW_RISE_SEQ)
        cx, cy = _pos(t)
        phi = ((_rand(battle) & 0x3ff) << 16) >> 10
        n = 0
        for count, rx, ry, step in ((16, 0x20, 0x18, 0x1000), (8, 0x18, 0x12, 0x2000)):
            for k in range(count):
                e = _fx(battle, _slow_think, cx, cy, 0, MAG_SEQ, slow=True, battle=battle, coord=coord, target=t,
                        cx=cx, cy=cy, rx=rx, ry=ry, phi=phi & 0xffff, spd=0x400, state=0, emit=(k % 4 == 0),
                        lead=(n == 23))
                _orbit(e)
                phi = (phi + step) & 0xffff
                n += 1
        coord.user_data['live'] += 1
    _sfx(battle, 0xc9)


SPAWN = {0x25: _spawn_heavy, 0x26: _spawn_heal_pillars, 0x27: _spawn_luck, 0x28: _spawn_rings, 0x29: _spawn_spirals,
         0x2a: _spawn_rings, 0x2b: _spawn_revive, 0x2c: _spawn_yuka, 0x2d: _spawn_hero, 0x2e: _spawn_slow}
