"""美娜 10 技能 (core.mina_skills): 施法 seq 6720bc → MINA_SIG → 各招特效 → 协调实体收尾."""
import random
from types import SimpleNamespace

import pytest

from core.battle.data import BattleMap, BattleUnit
from core.battle.tactics import TacticsBattle
from core.battle.status import has_status, apply_status


def _unit(name, x, y, *, is_player, agile, hp=600):
    u = BattleUnit(name=name, level=1, max_hp=600, hp=hp, max_mp=3000, mp=3000, sg=0,
                   attack=60, defence=5, agile=agile, move=0, is_player=is_player)
    u.x, u.y = x, y
    return u


def _run(sid, *, ally_hp=300, cursor=(16, 53), seed=3, n=4000):
    from scenes.battle.update import _tick_reactions
    from core.attack_seq import ATTACK_TICK_MS
    p = _unit('美娜', 15, 53, is_player=True, agile=99)
    a = _unit('ally', 16, 53, is_player=True, agile=50, hp=ally_hp)
    e = _unit('e', 15, 54, is_player=False, agile=1)
    b = TacticsBattle(players=[p, a], enemies=[e], battle_map=BattleMap(32, 64), rng=random.Random(seed),
                      player_positions=[(15, 53), (16, 53)], enemy_positions=[(15, 54)])
    if ally_hp == 0:
        a.hp = 0
        a.death_anim_time_ms = 0
    p.facing = (0, 1)
    played = []
    b.engine.on('sound_play', lambda en, s: played.append(s))
    assert b.enter_attack_aim(skill_id=sid)
    b.aim_cursor = cursor
    if not b.confirm_attack_aim():
        b.aim_cursor = (15, 53)
        assert b.confirm_attack_aim()
    stub = SimpleNamespace(battle=b)
    kinds = set()
    for _ in range(n):
        b.engine.tick()
        _tick_reactions(stub, ATTACK_TICK_MS)
        for en in b.engine.entities:
            for k in ('bigheal', 'cure', 'holy', 'drain', 'seal', 'devil', 'angel', 'ice', 'trail', 'drop', 'seal_icon'):
                if en.user_data.get(k):
                    kinds.add(k)
        if b._pending_turn_end and not any(x.flags & 0x800 and x.user_data.get('projectile')
                                           and not x.user_data.get('trail') and not x.user_data.get('drop')
                                           for x in b.engine.entities):
            break
    return b, p, a, e, played, kinds


ENEMY = {0x0c, 0x0d, 0x10}


@pytest.mark.parametrize('sid', list(range(0x0a, 0x14)))
def test_all_finish(sid):
    b, p, a, e, played, kinds = _run(sid, ally_hp=0 if sid in (0x0f, 0x12) else 300,
                                     cursor=(15, 54) if sid in ENEMY else (16, 53))
    assert b._pending_turn_end, f"{sid:#x} 没收尾"


def test_heals():
    for sid in (0x0a, 0x0e, 0x11):
        b, p, a, *_ = _run(sid)
        assert a.hp > 300, f"{sid:#x}"


def test_revives():
    for sid in (0x0f, 0x12):
        b, p, a, *_ = _run(sid, ally_hp=0)
        assert a.alive, f"{sid:#x}"


def test_cure_clears_poison():
    from core.mina_skills import ST_POISON, _apply_statuses
    b, p, a, *_ = _run(0x0b)
    apply_status(a, ST_POISON, 3)
    _apply_statuses(b, p, 0x0b, [a])
    assert not has_status(a, ST_POISON)


def test_holy_damages():
    b, p, a, e, played, kinds = _run(0x0c, cursor=(15, 54))
    assert e.hp < 600 and 'holy' in kinds
    assert 0xec in played and 0xc4 in played


def test_drain_heals_caster():
    b, p, a, e, played, kinds = _run(0x0d, cursor=(15, 54))
    p.hp = 100
    b, p, a, e, played, kinds = _run(0x0d, cursor=(15, 54))
    assert e.hp < 600 and 'drain' in kinds and 0x12d in played


def test_seal_silences():
    from core.mina_skills import ST_SILENCE
    b, p, a, e, played, kinds = _run(0x10, cursor=(15, 54))
    assert has_status(e, ST_SILENCE) and 'seal_icon' in kinds
    assert played.count(0xea) == 16 + 3


def test_spirit_kinds():
    seen = set()
    for seed in range(12):
        b, p, a, e, played, kinds = _run(0x13, seed=seed, cursor=(15, 53))
        seen |= kinds & {'devil', 'angel'}
    assert seen == {'devil', 'angel'}
