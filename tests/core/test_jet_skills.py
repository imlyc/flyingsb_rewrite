"""乐神杰特 10 技能 (core.jet_skills): 音符脚本 → -100 → 各招特效 → 收尾; 状态位只置位 (效果另做)."""
import random
from types import SimpleNamespace

import pytest

from core.battle.data import BattleMap, BattleUnit
from core.battle.tactics import TacticsBattle
from core.battle.status import has_status, apply_status


def _unit(name, x, y, *, is_player, agile, hp=600):
    u = BattleUnit(name=name, level=1, max_hp=600, hp=hp, max_mp=300, mp=300, sg=0,
                   attack=60, defence=5, agile=agile, move=0, is_player=is_player)
    u.x, u.y = x, y
    return u


def _run(sid, *, ally_hp=300, cursor=None, seed=3):
    from scenes.battle.update import _tick_reactions
    from core.attack_seq import ATTACK_TICK_MS
    p = _unit('乐神杰特', 15, 53, is_player=True, agile=99)
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
    b.aim_cursor = cursor or (16, 53)
    if not b.confirm_attack_aim():
        b.aim_cursor = (15, 53)
        assert b.confirm_attack_aim()
    stub = SimpleNamespace(battle=b)
    notes = set()
    for _ in range(3000):
        b.engine.tick()
        _tick_reactions(stub, ATTACK_TICK_MS)
        for en in b.engine.entities:
            if en.flags & 0x800 and en.user_data.get('note'):
                notes.add((id(en), en._born_tick))
        if b._pending_turn_end and not any(x.flags & 0x800 and x.user_data.get('projectile') for x in b.engine.entities):
            break
    return b, p, a, e, played, len(notes)


@pytest.mark.parametrize('sid', list(range(0x25, 0x2f)))
def test_all_finish_with_13_notes(sid):
    b, p, a, e, played, notes = _run(sid, ally_hp=0 if sid in (0x2b, 0x2e) else 300,
                                     cursor=(15, 54) if sid == 0x25 else None)
    assert b._pending_turn_end, f"{sid:#x} 没收尾"
    assert notes == 13
    from core.jet_skills import START_SOUND
    assert START_SOUND[sid] in played


def test_status_flags():
    from core.jet_skills import ST_SAMBA, ST_GUARD, ST_INVINCIBLE, ST_LUCK
    for sid, bit in ((0x28, ST_SAMBA), (0x2a, ST_GUARD), (0x2d, ST_INVINCIBLE), (0x27, ST_LUCK)):
        b, p, a, e, *_ = _run(sid)
        assert has_status(a, bit), f"{sid:#x} 应给队友 {bit:#x}"


def test_luck_clears_curse_instead():
    from core.jet_skills import ST_CURSE, ST_LUCK, _apply_statuses
    b, p, a, e, *_ = _run(0x26)
    apply_status(a, ST_CURSE, 3)
    _apply_statuses(b, p, 0x27, [a])
    assert not has_status(a, ST_CURSE) and not has_status(a, ST_LUCK)


def test_exp_receiver_flag():
    b, p, a, *_ = _run(0x29)
    assert b.exp_receiver is a


def test_heal_and_revive():
    b, p, a, *_ = _run(0x26)
    assert a.hp > 300
    b, p, a, *_ = _run(0x2b, ally_hp=0)
    assert a.alive
    b, p, a, *_ = _run(0x2e, ally_hp=0)
    assert a.alive and a.hp == a.max_hp


def test_heavy_metal_paralysis_roll():
    from core.jet_skills import ST_PARALYSIS
    hits = sum(has_status(_run(0x25, cursor=(15, 54), seed=s)[3], ST_PARALYSIS) for s in range(12))
    assert hits >= 6                                     # 双方智力/幸运 0 → 成功率顶到 90%
    # exe act==2 case 2: 威力 + (智力差)/2 + (威力 + 幸运差) + 相性, clamp 10..90
    from types import SimpleNamespace
    from core.battle.formulas import seal_chance
    c = SimpleNamespace(wisdom=50, luck=10, is_player=True, status_bits=0)
    e = SimpleNamespace(wisdom=400, luck=300, is_player=False, status_bits=0, type_flags=0)
    assert seal_chance(c, e, 0x25) == 10
    e.wisdom, e.luck = 100, 170
    assert seal_chance(c, e, 0x25) == 100 + (50 - 100) // 2 + (100 + 10 - 170)    # = 15
