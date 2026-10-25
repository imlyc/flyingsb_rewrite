#!/usr/bin/env python3
"""无头跑一个技能, 输出与原版 entdump (wine/cnc-ddraw entdump.c) 同格式的逐 tick 实体表, 供 wine/skill_timeline.py
/ wine/skill_diff.py 与原版实录对比.

用法: python -m tools.skill_trace <skill_id_hex> [--caster 紫河] [--enemy-dx -1 --enemy-dy 2] [--facing down] [--out x.log]
坐标系: 与 exe 一致 — 格 64×48 px, 16.16 定点; z 为负=上空 (exe z 正=上空, 输出时取反对齐).
E 行: idx flags x y z dir slot frame tick state fn link. flags 合成: 0x40 可见 0x80 当前行动者 0x400 敌方 0x800 alive
0x10000 待机 0x20000 seq 播放中. fn = 我们的 think_fn 名 (原版是地址, 不比对).
"""
from __future__ import annotations

import argparse, random, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.battle.data import BattleMap, BattleUnit
from core.battle.tactics import TacticsBattle
from core.sprites.base import TILE_W, TILE_H

FACING = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}


def _unit(name, x, y, *, is_player, agile):
    u = BattleUnit(name=name, level=1, max_hp=600, hp=600, max_mp=300, mp=300, sg=0,
                   attack=30, defence=5, agile=agile, move=0, is_player=is_player)
    u.x, u.y = x, y
    return u


_CUR_TICK = [0]


def unit_line(idx, u, active):
    e = u.entity
    flags = 0x40 | 0x800 | (0x400 if not u.is_player else 0) | (0x80 if active else 0)
    if e is not None and e.is_playing():
        flags |= 0x20000
    elif not u.cast_hold:
        flags |= 0x10000
    if e is not None and (e.is_playing() or u.cast_hold or _CUR_TICK[0] < e.user_data.get('hold_until_tick', -1)) \
            and _CUR_TICK[0] >= e.user_data.get('idle_until_tick', 0):
        slot, frame = e.atlas_slot, e.frame_idx
        x = u.x * TILE_W * 65536 + TILE_W * 32768 + e.x
        y = u.y * TILE_H * 65536 + TILE_H * 32768 + e.y
        z = -e.z
    else:
        slot, frame = 0x20006, 0
        x = (u.x * TILE_W + TILE_W // 2) << 16
        y = (u.y * TILE_H + TILE_H // 2) << 16
        z = 0
    from core.attack_seq import facing_to_atk_index
    return f"E {idx} {flags:x} {x} {y} {z} {facing_to_atk_index(u.facing)} {slot:x} {frame} 0 0 unit 0"


def effect_line(idx, e, tick0):
    flags = 0x800 | (0x40 if e.flags & 0x40 else 0) | (0x20000 if e.is_playing() else 0) | (0x10000 if e.think_fn else 0)
    fn = getattr(e.think_fn, '__name__', 'seq') if e.think_fn else 'seq'
    return f"E {idx} {flags:x} {e.x} {e.y} {-e.z} 0 {e.atlas_slot:x} {e.frame_idx} {tick0} {e.state_code} {fn} 0"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('skill', type=lambda s: int(s, 16))
    ap.add_argument('--caster', default='紫河'); ap.add_argument('--caster-idx', type=int, default=4, help='原版实录里施法者的实体下标 (队伍位置)')
    ap.add_argument('--enemy-dx', type=int, default=-1); ap.add_argument('--enemy-dy', type=int, default=2)
    ap.add_argument('--facing', default='down'); ap.add_argument('--enemy-facing', default=None, help='敌人朝向 (受击推开方向取决于它)'); ap.add_argument('--more-enemies', default='', help='更多敌人 dx,dy;dx,dy (相对施法者)'); ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--ally-facing', default=None); ap.add_argument('--ally-dx', type=int); ap.add_argument('--ally-dy', type=int, help='加一个队友 (我方目标技能用)')
    ap.add_argument('--cursor-dx', type=int); ap.add_argument('--cursor-dy', type=int, help='光标相对施法者格 (默认敌人格, 失败回施法者)')
    ap.add_argument('--attack', type=int, default=None, help='普攻表 idx (普攻实录; skill 参数忽略)')
    ap.add_argument('--max-ticks', type=int, default=900); ap.add_argument('--out', default='-')
    a = ap.parse_args()
    p = _unit(a.caster, 15, 53, is_player=True, agile=99)
    e = _unit('enemy', 15 + a.enemy_dx, 53 + a.enemy_dy, is_player=False, agile=1)
    players = [p]
    if a.ally_dx is not None and (a.ally_dx, a.ally_dy) != (0, 0):      # (0,0) = 目标就是施法者自己
        ally = _unit('ally', 15 + a.ally_dx, 53 + a.ally_dy, is_player=True, agile=50); players.append(ally)
        if a.skill in (0x09, 0x2b, 0x0f):       # M凤凰 复活术 / 回生舞步 / 甦生: 队友得是倒下的才是目标
            ally.hp = 0; ally.death_anim_time_ms = 0
    es = [e] + [_unit(f'enemy{i}', 15 + int(t.split(',')[0]), 53 + int(t.split(',')[1]), is_player=False, agile=1)
                for i, t in enumerate(x for x in a.more_enemies.split(';') if x)]
    b = TacticsBattle(players=players, enemies=es, battle_map=BattleMap(32, 64), rng=random.Random(a.seed),
                      player_positions=[(u.x, u.y) for u in players], enemy_positions=[(u.x, u.y) for u in es])
    p.facing = FACING[a.facing]
    if a.ally_facing and len(players) > 1:
        players[1].facing = FACING[a.ally_facing]
    if a.skill == 0x13:                         # 召喚精靈: 实录目标是自己/队友 → 回血精灵, 否则攻击精灵
        b.spirit_pick = 'ally' if a.ally_dx is not None else 'enemy'
    if a.enemy_facing:
        for u in es:
            u.facing = FACING[a.enemy_facing]
    out = []
    sounds = []
    b.engine.on('sound_play', lambda ent, sid: sounds.append(sid))
    b.engine.on('sound_play_solo', lambda ent, sid: sounds.append(sid))
    if a.attack is not None:
        from core import normal_attack as NA
        p.attack_normal = p.attack_melee = a.attack
        if p.name == '紫河' and a.attack in (88, 89, 90):           # 紫河形态卡 (形态 = idx-88), 开战已变身
            NA.zihe_setup(p, {0: (), 1: (0x129,), 2: (0x12a,)}[a.attack - 88] + (0x144,))
            NA.zihe_switch(p, to_beast=True)
            p.flicker = None
            p.attack_normal = p.attack_melee = a.attack
    assert b.enter_attack_aim(skill_id=None if a.attack is not None else a.skill), 'aim failed'
    b.aim_cursor = (15 + a.cursor_dx, 53 + a.cursor_dy) if a.cursor_dx is not None else (e.x, e.y)
    if not b.confirm_attack_aim():                 # 我方/自身目标技能 (生命之火/斗轉/返荷/化精為氣): 光标放施法者
        b.aim_cursor = (p.x, p.y)
        assert b.confirm_attack_aim(), 'confirm failed (敌人不在范围?)'
    born = {}
    from types import SimpleNamespace
    from scenes.battle.update import _tick_reactions
    from core.attack_seq import ATTACK_TICK_MS
    scene_stub = SimpleNamespace(battle=b)
    for t in range(a.max_ticks):
        b.engine.tick()
        _CUR_TICK[0] = b.engine._tick_id
        _tick_reactions(scene_stub, ATTACK_TICK_MS)    # 受击 seq 也推进 (dispatcher 收尾要等它播完, 如猪八戒 0x14)
        out.append(f"F {t} {t * 24}")
        out.append(f"G cam={a.enemy_dx},{a.enemy_dy} skill={a.attack if a.attack is not None else a.skill} move=0 nvict=1")
        out.append(f"B caster={0x86b618 + a.caster_idx * 0x1ac:x} n=1 {0x86b618 + 60 * 0x1ac:x}")
        out.append(unit_line(a.caster_idx, p, True)); out.append(unit_line(60, e, False))
        idx = 90
        for ent in b.engine.entities:
            if not (ent.flags & 0x800) or any(ent is u.entity for u in b.all_units):
                continue
            out.append(effect_line(90 + ent.id, ent, b.engine._tick_id - ent._born_tick))   # 槽位复用时 age 归零 (= exe +0x144)
        if sounds:
            out.append("S " + " ".join(str(s) for s in sounds)); sounds.clear()
        if b._pending_turn_end and not any((ent.flags & 0x800) and ent.user_data.get('projectile') and ent.state_code != 20
                                           for ent in b.engine.entities):
            break        # 收尾渐亮等 projectile 实体也结束 (施法者回待机的时刻才能对上)
    text = "\n".join(out) + "\n"
    if a.out == '-': sys.stdout.write(text)
    else: pathlib.Path(a.out).write_text(text); print('wrote', a.out, 'ticks', t + 1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
