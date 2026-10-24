"""破无 5 技能 (core.pao_skills): 每目标一支箭 / 命中附加效果 / 收尾 (exe dispatcher 508253 / 508a21)."""
import random
from types import SimpleNamespace

import pytest

from core.battle.data import BattleMap, BattleUnit
from core.battle.tactics import TacticsBattle


def _unit(name, x, y, *, is_player, agile):
    u = BattleUnit(name=name, level=1, max_hp=600, hp=600, max_mp=300, mp=300, sg=99,
                   attack=60, defence=5, agile=agile, move=0, is_player=is_player)
    u.x, u.y = x, y
    return u


def _run(sid, enemies, cursor):
    from scenes.battle.update import _tick_reactions
    from core.attack_seq import ATTACK_TICK_MS
    p = _unit('破无', 15, 53, is_player=True, agile=99)
    es = [_unit(f'e{i}', x, y, is_player=False, agile=1) for i, (x, y) in enumerate(enemies)]
    b = TacticsBattle(players=[p], enemies=es, battle_map=BattleMap(32, 64), rng=random.Random(5),
                      player_positions=[(p.x, p.y)], enemy_positions=[(e.x, e.y) for e in es])
    p.facing = (0, 1)
    played = []
    b.engine.on('sound_play', lambda e, s: played.append(s))
    assert b.enter_attack_aim(skill_id=sid)
    b.aim_cursor = cursor
    assert b.confirm_attack_aim()
    stub = SimpleNamespace(battle=b)
    seen = {}
    for _ in range(1500):
        b.engine.tick()
        _tick_reactions(stub, ATTACK_TICK_MS)
        for e in b.engine.entities:
            if e.flags & 0x800:
                for k in ('pao_arrow', 'chiri', 'thunder', 'ring', 'fx_end'):
                    if e.user_data.get(k):
                        seen.setdefault(k, set()).add((id(e), e._born_tick))
        if b._pending_turn_end and not any(e.flags & 0x800 and e.user_data.get('projectile') for e in b.engine.entities):
            break
    return b, es, {k: len(v) for k, v in seen.items()}, played


@pytest.mark.parametrize('sid', [0x2f, 0x30, 0x31, 0x32])
def test_one_arrow_per_target(sid):
    from core.pao_skills import SFX_SHOOT, SFX_ARROW_HIT
    enemies = [(14, 56), (15, 56), (16, 56)] if sid in (0x2f, 0x31) else [(15, 56)]
    b, es, seen, played = _run(sid, enemies, (15, 56))
    assert b._pending_turn_end
    assert all(e.hp < 600 for e in es)
    assert seen['pao_arrow'] == len(es)
    assert seen['chiri'] == 8 * len(es)
    assert played.count(SFX_SHOOT) == 1 and played.count(SFX_ARROW_HIT) == len(es)
    if sid in (0x30, 0x31):
        assert seen['fx_end'] == len(es)
    if sid == 0x32:
        assert seen['thunder'] == 1 and seen['ring'] == 4


def test_rain_hits_all_in_pattern():
    b, es, seen, played = _run(0x33, [(15, 55), (13, 53), (16, 54)], (15, 53))
    assert b._pending_turn_end
    assert all(e.hp < 600 for e in es)
    assert seen['pao_arrow'] == 3


def test_no_fade():
    b, *_ = _run(0x30, [(15, 56)], (15, 56))
    assert b.dim_level == 0.0
