"""状态图标 (core.battle.status_icons): 有状态位就挂, 位清掉就摘; 無敵/森巴/防禦 无图标."""
import random

from core.battle.data import BattleMap, BattleUnit
from core.battle.tactics import TacticsBattle
from core.battle.status import apply_status, clear_status
from core.battle import status_icons as si


def _battle():
    p = BattleUnit(name='p', level=1, max_hp=100, hp=100, max_mp=0, mp=0, sg=0, attack=10, defence=0, agile=10,
                   move=3, is_player=True)
    e = BattleUnit(name='e', level=1, max_hp=100, hp=100, max_mp=0, mp=0, sg=0, attack=10, defence=0, agile=1,
                   move=3, is_player=False)
    b = TacticsBattle(players=[p], enemies=[e], battle_map=BattleMap(20, 20), rng=random.Random(1),
                      player_positions=[(5, 5)], enemy_positions=[(9, 9)])
    return b, p, e


def _icons(b):
    return [x for x in b.engine.entities if x.flags & 0x800 and x.user_data.get('status_icon')]


def test_icons_follow_status_bits():
    b, p, e = _battle()
    for bit in (0x100, 0x200, 0x400, 0x800, 0x1000, 0x2000):
        apply_status(p, bit, 3)
    apply_status(p, 0x4000, 2)
    apply_status(p, 0x10000, 3)
    si.sync(b)
    reg = b.status_icons[id(p)]
    assert set(reg) == {1, 2, 3, 4, 5, 6}, "無敵/森巴 不挂图标"
    assert len(reg[5]) == 3 and len(reg[6]) == 3 and len(reg[4]) == 4
    for _ in range(80):
        b.engine.tick()
    assert any(x.atlas_slot == si.E_TOXIC for x in _icons(b)), "中毒应冒泡泡"
    assert any(x.atlas_slot == si.E_SLEEP for x in _icons(b)), "睡眠应冒 Z"
    clear_status(p, 0x2000)
    si.sync(b, create=False)
    assert 6 not in b.status_icons[id(p)]


def test_icons_never_block_turn_end():
    b, p, e = _battle()
    apply_status(p, 0x1000, 3)
    si.sync(b)
    assert all(x.state_code == si.DONE for x in _icons(b))


def test_enemy_stun_uses_paralysis_icon():
    b, p, e = _battle()
    e.status_bits |= si.ENEMY_STUN
    si.sync(b)
    assert 4 in b.status_icons[id(e)]
