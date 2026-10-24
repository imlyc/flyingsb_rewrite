"""捕山 5 技能 + 地雷触发 (core.bosan_skills, exe dispatcher 50a848/50bdff/50afe5/50b93c/50c63b + 地雷 50bff2)."""
import random
from types import SimpleNamespace

import pytest

from core.battle.data import BattleMap, BattleUnit
from core.battle.tactics import TacticsBattle, Phase


def _unit(name, x, y, *, is_player, agile, hp=600):
    u = BattleUnit(name=name, level=1, max_hp=600, hp=hp, max_mp=300, mp=300, sg=99,
                   attack=60, defence=5, agile=agile, move=0, is_player=is_player)
    u.x, u.y = x, y
    return u


def _battle(enemies):
    p = _unit('捕山', 15, 53, is_player=True, agile=99)
    es = [_unit(f'e{i}', x, y, is_player=False, agile=1) for i, (x, y) in enumerate(enemies)]
    b = TacticsBattle(players=[p], enemies=es, battle_map=BattleMap(32, 64), rng=random.Random(7),
                      player_positions=[(p.x, p.y)], enemy_positions=[(e.x, e.y) for e in es])
    p.facing = (0, 1)
    return b, p, es


def _run(b, n=2000):
    from scenes.battle.update import _tick_reactions
    from core.attack_seq import ATTACK_TICK_MS
    stub = SimpleNamespace(battle=b)
    seen = {}
    played, stopped = [], []
    b.engine.on('sound_play', lambda e, s: played.append(s))
    b.engine.on('sound_stop', lambda e, s: stopped.append(s))
    for _ in range(n):
        b.engine.tick()
        _tick_reactions(stub, ATTACK_TICK_MS)
        for e in b.engine.entities:
            if e.flags & 0x800:
                for k in ('throw', 'segment', 'flame', 'fx_end', 'chiri', 'mine'):
                    if e.user_data.get(k):
                        seen.setdefault(k, set()).add((id(e), e._born_tick))
        if b._pending_turn_end and not any(e.flags & 0x800 and e.user_data.get('projectile') and e.state_code != 20
                                           for e in b.engine.entities):
            break
    return {k: len(v) for k, v in seen.items()}, played, stopped


def _cast(b, sid, cursor):
    assert b.enter_attack_aim(skill_id=sid)
    b.aim_cursor = cursor
    return b.confirm_attack_aim()


@pytest.mark.parametrize('sid', [0x34, 0x36])
def test_throw(sid):
    b, p, es = _battle([(15, 56)])
    assert _cast(b, sid, (15, 56))
    seen, played, _ = _run(b)
    assert b._pending_turn_end and es[0].hp < 600
    assert seen['throw'] == 1 and seen['fx_end'] == 1
    assert (0xf2 if sid == 0x34 else 0x102) in played
    assert b.dim_level == 0.0


def test_laser_hits_every_20_ticks():
    from core.bosan_skills import SFX_LASER
    b, p, es = _battle([(15, 55), (15, 57)])
    assert _cast(b, 0x37, (15, 54))
    seen, played, stopped = _run(b)
    assert b._pending_turn_end and all(e.hp < 600 for e in es)
    assert seen['segment'] > 80                         # 每 tick 一段, 88 tick
    assert seen['chiri'] == 8 * 5 * 2                   # age 0,20,40,60,80 各一次 ×2 目标
    assert SFX_LASER in played and SFX_LASER in stopped


def test_flamethrower():
    from core.bosan_skills import SFX_FLAME, SFX_FLAME_HIT
    b, p, es = _battle([(15, 55)])
    assert _cast(b, 0x38, (15, 54))
    seen, played, stopped = _run(b)
    assert b._pending_turn_end and es[0].hp < 600
    assert played.count(SFX_FLAME_HIT) == 4             # age 32/64/96/128
    assert SFX_FLAME in stopped
    assert seen['flame'] == 6 + 41                      # age 0..5 每 t + 之后 age%3==0 (6..128 → 41 个)


def test_mine_place_and_trigger():
    from core.bosan_skills import MINE_DAMAGE, can_place_mine
    b, p, es = _battle([(20, 58)])
    assert not _cast(b, 0x35, (20, 58)), "有人的格不能埋雷"
    b.cancel_attack_aim() if hasattr(b, 'cancel_attack_aim') else None
    b.phase = Phase.PLAYER_AIM
    b.aim_skill_id = 0x35
    b.aim_cursor = (15, 54)
    assert b.confirm_attack_aim()
    seen, played, _ = _run(b)
    assert (15, 54) in b.mines and 0x10e in played
    assert not can_place_mine(b, (15, 54)), "同格不能再埋"
    # 敌人走到雷上 → 敌方回合 post_enemy_turn 改为引爆
    e = es[0]
    e.x, e.y = 15, 54
    b._pending_turn_end = False
    b.phase = Phase.ENEMY_TURN
    b._turn_order.insert(b._turn_idx, e) if b.current is not e else None
    b._turn_idx = b._turn_order.index(e)
    b._pending_enemy_attack = p
    b.post_enemy_turn()
    _run(b)
    assert e.hp == 600 - MINE_DAMAGE
    assert (15, 54) not in b.mines
    assert b._pending_turn_end
    assert p.hp == 600, "踩雷的敌人这回合不再攻击"
