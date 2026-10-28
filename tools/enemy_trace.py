#!/usr/bin/env python3
"""无头跑一个敌招 (core.enemy_moves / core.enemy_spells), 输出与原版 entdump 同格式的逐 tick 实体表 (同 tools.skill_trace),
供 wine/skill_diff.py 与原版实录 (wine/arena.sh + emove 强制出招) 对比. 施法敌人 = 实体 60, 我方目标 = 实体 0..

用法: python -m tools.enemy_trace <招式id> --type <敌人表下标> [--facing down] [--targets dx,dy;dx,dy] [--target-facing up]
      [--cursor-dx 0 --cursor-dy 2] [--out x.log]
"""
from __future__ import annotations

import argparse, random, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.battle.data import BattleMap
from core.battle.tactics import TacticsBattle
from tools.skill_trace import FACING, _unit, unit_line, effect_line, _CUR_TICK
from core.exe_rng import ExeRng


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('move', type=int)
    ap.add_argument('--type', type=int, required=True, help='敌人表下标 (原版 arena.sh 同号)')
    ap.add_argument('--facing', default='down')
    ap.add_argument('--targets', default='0,2', help='我方单位相对施法者格 "dx,dy;dx,dy" (第一个 = 主目标)')
    ap.add_argument('--target-facing', default='up')
    ap.add_argument('--target-idx', default='', help='各我方单位在实录里的实体下标 (逗号), 默认 0,1,2..')
    ap.add_argument('--cursor-dx', type=int); ap.add_argument('--cursor-dy', type=int)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--max-ticks', type=int, default=1500); ap.add_argument('--out', default='-')
    a = ap.parse_args()
    from core.battle.setup import make_enemy_by_type
    from core.enemy_moves import move
    from core.skill_patterns import compute_template_strike, strike_falloff
    from core.battle import combat
    cx, cy = 15, 53
    e = make_enemy_by_type(a.type)
    e.x, e.y = cx, cy
    e.mp = e.max_mp = 9999
    offs = [tuple(int(v) for v in t.split(',')) for t in a.targets.split(';') if t]
    ps = []
    for i, (dx, dy) in enumerate(offs):
        p = _unit(f'p{i}', cx + dx, cy + dy, is_player=True, agile=1)
        p.max_hp = p.hp = 30000
        p.defence, p.luck = 100, 0
        ps.append(p)
    idxs = [int(v) for v in a.target_idx.split(',')] if a.target_idx else list(range(len(ps)))
    b = TacticsBattle(players=ps, enemies=[e], battle_map=BattleMap(32, 64), rng=ExeRng(a.seed),
                      player_positions=[(u.x, u.y) for u in ps], enemy_positions=[(e.x, e.y)])
    e.facing = FACING[a.facing]
    for p in ps:
        p.facing = FACING[a.target_facing]
    m = move(a.move)
    tgt = ps[0]
    cursor = (cx + a.cursor_dx, cy + a.cursor_dy) if a.cursor_dx is not None else (tgt.x, tgt.y)
    tiles = {t for t in compute_template_strike(e, cursor, m.template, b.map) if b.map.in_bounds(*t)}
    b._pending_damage_range = tiles if len(tiles) > 1 else None
    b._pending_damage_falloff = strike_falloff(e, cursor, m.template) if len(tiles) > 1 else None
    e.pending_enemy_move = a.move
    b.phase = __import__('core.battle.data', fromlist=['Phase']).Phase.ENEMY_TURN
    combat.begin_attack(b, e, tgt, cursor=cursor)
    out, sounds = [], []
    b.engine.on('sound_play', lambda ent, sid: sounds.append(sid))
    b.engine.on('sound_play_solo', lambda ent, sid: sounds.append(sid))
    from types import SimpleNamespace
    from scenes.battle.update import _tick_reactions
    from core.attack_seq import ATTACK_TICK_MS
    stub = SimpleNamespace(battle=b)
    t = 0
    for t in range(a.max_ticks):
        b.engine.tick()
        _CUR_TICK[0] = b.engine._tick_id
        _tick_reactions(stub, ATTACK_TICK_MS)
        out.append(f"F {t} {t * 24}")
        out.append(f"G cam={cursor[0] - cx},{cursor[1] - cy} skill=-1 move={a.move} nvict={len(ps)}")
        out.append(f"B caster={0x86b618 + 60 * 0x1ac:x} n={len(ps)} " + " ".join(f"{0x86b618 + i * 0x1ac:x}" for i in idxs))
        out.append(unit_line(60, e, True))
        for i, p in zip(idxs, ps):
            out.append(unit_line(i, p, False))
        for ent in b.engine.entities:
            if not (ent.flags & 0x800) or any(ent is u.entity for u in b.all_units):
                continue
            out.append(effect_line(90 + ent.id, ent, b.engine._tick_id - ent._born_tick))
        if sounds:
            out.append("S " + " ".join(str(s) for s in sounds)); sounds.clear()
        if b._pending_turn_end and not any((ent.flags & 0x800) and ent.user_data.get('projectile') and ent.state_code != 20
                                           for ent in b.engine.entities):
            break
    text = "\n".join(out) + "\n"
    if a.out == '-':
        sys.stdout.write(text)
    else:
        pathlib.Path(a.out).write_text(text); print('wrote', a.out, 'ticks', t + 1, b.messages[-3:])
    return 0


if __name__ == '__main__':
    sys.exit(main())
