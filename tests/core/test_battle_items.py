"""战斗道具结算与演出 (exe FUN_004a6efe act==3 + 各道具控制器, core.item_use)."""
import pytest

from core.battle import energy
from core.battle.data import BattleMap, BattleUnit
from core.battle.status import apply_status
from core.battle.tactics import TacticsBattle
from core.exe_rng import ExeRng


def _unit(name, x, y, is_player=True):
    u = BattleUnit(name=name, level=1, max_hp=600, hp=300, max_mp=300, mp=100, sg=0, attack=30, defence=5, agile=50,
                   move=0, is_player=is_player)
    u.x, u.y = x, y
    return u


def _battle(ally_dead=False):
    p = _unit('三藏法师', 5, 5)
    p.agile = 99                                     # 先手 (同 tools.skill_trace)
    a = _unit('ally', 5, 6)
    if ally_dead:
        a.hp = 0
        a.death_anim_time_ms = 0
    e = _unit('enemy', 9, 9, is_player=False)
    b = TacticsBattle(players=[p, a], enemies=[e], battle_map=BattleMap(16, 16), rng=ExeRng(1),
                      player_positions=[(5, 5), (5, 6)], enemy_positions=[(9, 9)])
    assert b.current is p
    p.facing = (0, 1)
    return b, p, a


def test_cure_items_clear_their_status_and_counters():
    b, p, a = _battle()
    for bit in (0x100, 0x200, 0x400, 0x800, 0x1000):
        apply_status(a, bit, 2)
    r = energy.battle_item(b, p, a, 0x136)
    assert r == {'cured': 0x100} and not a.status_bits & 0x100 and 0x100 not in a.status_turns
    assert energy.battle_item(b, p, a, 0x136) == {}                    # 没有中毒 → 无效果
    r = energy.battle_item(b, p, a, 0x13d)                             # 萬靈丹: 其余四种全清
    assert r['cured'] == 0x1e00 and a.status_bits & 0x1f00 == 0


def test_tianto_revives_then_fully_heals():
    b, p, a = _battle(ally_dead=True)
    r = energy.battle_item(b, p, a, 0x132)
    assert r['revived'] and a.hp == a.max_hp and a.mp == a.max_mp
    assert r['hp'] == a.max_hp - a.max_hp // 5                         # 白字 = 复活后再回的量


def test_needle_revives_only():
    b, p, a = _battle(ally_dead=True)
    r = energy.battle_item(b, p, a, 0x134)
    assert r['revived'] and a.hp == a.max_hp // 5


@pytest.mark.parametrize('item', [0x135, 0x13b])
def test_smoke_and_double_light_cannot_be_used(item):
    b, p, a = _battle()
    assert b.enter_item_aim(item)
    b.aim_cursor = (p.x, p.y)
    assert not b.confirm_attack_aim()                                   # exe 返回 0: 留在瞄准, 道具不扣
    assert b.last_item_used is None or b.last_item_used != item


@pytest.mark.parametrize('item,status,cursor_ally', [
    (0x12e, 0, False), (0x12f, 0, True), (0x130, 0, False), (0x131, 0, True), (0x132, 0, False), (0x133, 0, False),
    (0x136, 0x100, True), (0x137, 0x200, True), (0x138, 0x400, False), (0x139, 0x800, True), (0x13c, 0x1000, True),
    (0x13d, 0x1f00, True)])
def test_item_presentation_ends_turn(item, status, cursor_ally):
    b, p, a = _battle()
    target = a if cursor_ally else p
    for bit in (0x100, 0x200, 0x400, 0x800, 0x1000):
        if status & bit:
            apply_status(target, bit, 3)
    assert b.enter_item_aim(item)
    b.aim_cursor = (target.x, target.y)
    assert b.confirm_attack_aim()
    for _ in range(600):
        b.engine.tick()
        if b._pending_turn_end:
            break
    assert b._pending_turn_end
    assert not target.status_bits & status
