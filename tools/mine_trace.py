#!/usr/bin/env python3
"""捕山地雷引爆的逐 tick 跟踪 (格式同 tools.skill_trace): 捕山在 (15, 53) 朝 --facing 埋雷 (技能 0x35, 光标正前一格),
回合收尾后敌人 (原站在雷前方两格) 走到雷上, 敌方回合 post_enemy_turn → 踩雷 (招式 247) 直到回合可交接.
供 Unity 版 TacticsTrace.Mine 逐行对照 (Unity 导出器 mine_trace_cases)."""
from __future__ import annotations

import argparse, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.battle.data import BattleMap, Phase
from core.battle.tactics import TacticsBattle
from core.exe_rng import ExeRng
from tools.skill_trace import FACING, _unit, unit_line, effect_line, _CUR_TICK


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--facing', default='down'); ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--max-ticks', type=int, default=900); ap.add_argument('--out', default='-')
    a = ap.parse_args()
    fx, fy = FACING[a.facing]
    p = _unit('捕山', 15, 53, is_player=True, agile=99)
    p.sg = 16
    e = _unit('enemy', 15 + fx * 3, 53 + fy * 3, is_player=False, agile=1)
    b = TacticsBattle(players=[p], enemies=[e], battle_map=BattleMap(32, 64), rng=ExeRng(a.seed),
                      player_positions=[(p.x, p.y)], enemy_positions=[(e.x, e.y)])
    p.facing = (fx, fy)
    assert b.enter_attack_aim(skill_id=0x35), 'aim failed'
    b.aim_cursor = (15 + fx, 53 + fy)
    assert b.confirm_attack_aim(), 'confirm failed'
    from types import SimpleNamespace
    from scenes.battle.update import _tick_reactions
    from core.attack_seq import ATTACK_TICK_MS
    scene_stub = SimpleNamespace(battle=b)
    sounds = []
    b.engine.on('sound_play', lambda ent, sid: sounds.append(sid))
    b.engine.on('sound_play_solo', lambda ent, sid: sounds.append(sid))
    out = []

    def busy() -> bool:
        return any((ent.flags & 0x800) and ent.user_data.get('projectile') and ent.state_code != 20 for ent in b.engine.entities)

    stage = 0
    for t in range(a.max_ticks):
        b.engine.tick()
        _CUR_TICK[0] = b.engine._tick_id
        _tick_reactions(scene_stub, ATTACK_TICK_MS)
        out.append(f"F {t} {t * 24}")
        out.append(f"B stage={stage} enemy_hp={e.hp} mines={len(getattr(b, 'mines', {}))}")
        out.append(unit_line(4, p, stage == 0)); out.append(unit_line(60, e, stage == 1))
        for ent in b.engine.entities:
            if not (ent.flags & 0x800) or any(ent is u.entity for u in b.all_units):
                continue
            out.append(effect_line(90 + ent.id, ent, b.engine._tick_id - ent._born_tick))
        if sounds:
            out.append("S " + " ".join(str(s) for s in sounds)); sounds.clear()
        if b._pending_turn_end and not busy():
            if stage == 1:
                break
            # 埋雷收尾 → 敌人走到雷上, 敌方回合交给 post_enemy_turn (= 走动画结束后的那一步)
            b._pending_turn_end = False
            e.x, e.y = 15 + fx, 53 + fy
            e.facing = (-fx, -fy)
            b._turn_order, b._turn_idx = [e], 0          # 轮到这个敌人
            b.phase = Phase.ENEMY_TURN
            b.post_enemy_turn()
            stage = 1
    text = "\n".join(out) + "\n"
    if a.out == '-': sys.stdout.write(text)
    else: pathlib.Path(a.out).write_text(text); print('wrote', a.out, 'ticks', t + 1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
