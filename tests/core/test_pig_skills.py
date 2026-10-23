"""猪八戒 5 技能 (core.pig_skills): 发弹数 / 火爆数 / 结算 / 收尾 / 音效 (exe dispatcher 501f38..50399a)."""
import random
from types import SimpleNamespace

import pytest

from core.battle.data import BattleMap, BattleUnit
from core.battle.tactics import TacticsBattle


def _unit(name, x, y, *, is_player, agile, hp=600):
    u = BattleUnit(name=name, level=1, max_hp=600, hp=hp, max_mp=300, mp=300, sg=99,
                   attack=60, defence=5, agile=agile, move=0, is_player=is_player)
    u.x, u.y = x, y
    return u


def _run(sid, *, enemies=((15, 55),), ally=None, cursor=None):
    from scenes.battle.update import _tick_reactions
    from core.attack_seq import ATTACK_TICK_MS
    p = _unit('猪八戒', 15, 53, is_player=True, agile=99)
    players = [p]
    if ally is not None:
        a = _unit('ally', *ally, is_player=True, agile=50, hp=100)
        players.append(a)
    es = [_unit(f'e{i}', x, y, is_player=False, agile=1) for i, (x, y) in enumerate(enemies)]
    b = TacticsBattle(players=players, enemies=es, battle_map=BattleMap(32, 64), rng=random.Random(3),
                      player_positions=[(u.x, u.y) for u in players], enemy_positions=[(e.x, e.y) for e in es])
    p.facing = (0, 1)
    played, stopped = [], []
    b.engine.on('sound_play', lambda e, s: played.append(s))
    b.engine.on('sound_play_solo', lambda e, s: played.append(s))
    b.engine.on('sound_stop', lambda e, s: stopped.append(s))
    assert b.enter_attack_aim(skill_id=sid)
    b.aim_cursor = cursor or (es[0].x, es[0].y)
    assert b.confirm_attack_aim()
    stub = SimpleNamespace(battle=b)
    seen = {'proj': set(), 'burst': set(), 'orbit': set()}
    for t in range(1500):
        b.engine.tick()
        _tick_reactions(stub, ATTACK_TICK_MS)
        for e in b.engine.entities:
            if not e.flags & 0x800:
                continue
            ud = e.user_data
            for k, key in (('proj', 'pig_proj'), ('burst', 'burst'), ('orbit', 'pig_orbit')):
                if ud.get(key):
                    seen[k].add((id(e), e._born_tick))
        if b._pending_turn_end and not any(e.flags & 0x800 and e.user_data.get('projectile') for e in b.engine.entities):
            break
    return b, p, players, es, seen, played, stopped, t


def test_pig_heal_heals_ally_only():
    from core.pig_skills import SFX_SHOT, SFX_PIG_ARRIVE
    b, p, players, es, seen, played, _, _ = _run(0x19, ally=(15, 55), enemies=((20, 58),), cursor=(15, 55))
    assert b._pending_turn_end
    assert players[1].hp > 100, "回復豬彈应给队友回血"
    assert es[0].hp == 600, "回復豬彈不伤敌"
    assert len(seen['proj']) == 1 and len(seen['burst']) == 1
    assert played.count(SFX_SHOT) == 1 and played.count(SFX_PIG_ARRIVE) == 1


@pytest.mark.parametrize('sid, shots', [(0x1a, 2), (0x1c, 4)])
def test_fire_cannon_shots_and_damage(sid, shots):
    from core.pig_skills import SFX_SHOT, SFX_FIRE_HIT
    b, p, _, es, seen, played, _, _ = _run(sid)
    assert b._pending_turn_end
    assert es[0].hp < 600
    assert len(seen['proj']) == shots and len(seen['burst']) == shots
    assert played.count(SFX_SHOT) == shots
    # 火炎砲 -250 播 0x13b ×2 / 發; 連續火炎砲 -200 播 0x13b ×1 / 發
    assert played.count(SFX_FIRE_HIT) == (2 * shots if sid == 0x1a else shots)


def test_spread_hits_offset_tiles_only():
    from core.pig_skills import SFX_SPREAD_SHOT
    # 下 3 格 / 右 2 格 在偏移表里; 斜角 (16,54) 不在
    b, p, _, es, seen, played, _, _ = _run(0x1b, enemies=((15, 56), (17, 53), (16, 54)), cursor=(15, 53))
    assert b._pending_turn_end
    assert es[0].hp < 600 and es[1].hp < 600
    assert es[2].hp == 600
    assert len(seen['proj']) == 12 and len(seen['burst']) == 12
    assert played.count(SFX_SPREAD_SHOT) == 12


def test_typhoon_36_orbits_then_damage():
    from core.pig_skills import SFX_TYPHOON
    b, p, _, es, seen, played, stopped, _ = _run(0x1d, enemies=((15, 55), (13, 53)), cursor=(15, 53))
    assert b._pending_turn_end
    assert all(e.hp < 600 for e in es)
    assert len(seen['orbit']) == 36 and len(seen['burst']) == 36
    assert SFX_TYPHOON in played and SFX_TYPHOON in stopped


def test_typhoon_orbit_geometry():
    """第 0 发 φ = 0x9555 (210°): 首步 rx 96 → 落在施法者 左下 (sin<0, -cos>0), 半径 1 格首 tick 即爆."""
    import math
    from core.pig_skills import TYPHOON_RX0, TYPHOON_DRX
    phi = (0x19555 - 0) & 0xffff
    a = phi / 65536 * 2 * math.pi
    assert math.sin(a) < 0 and -math.cos(a) > 0
    assert TYPHOON_RX0 + TYPHOON_DRX >= 1 * 64 + 32


def test_no_fade_for_pig_skills():
    b, *_ = _run(0x1a)
    assert b.dim_level == 0.0
