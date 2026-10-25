"""主角能量 MP / SG (core.battle.energy) + 战斗外用道具 (core.items.field_use), 规则见 energy 模块 docstring."""
import random
from types import SimpleNamespace

from core.battle import energy
from core.battle.data import BattleMap, BattleUnit
from core.battle.tactics import TacticsBattle
from core.items import field_use


def _u(name, x=10, y=10, *, is_player=True, mp=0, max_mp=0, sg=0, agile=50, equipment=(), skills=None):
    u = BattleUnit(name=name, level=10, max_hp=600, hp=600, max_mp=max_mp, mp=mp, sg=sg,
                   attack=100, defence=10, agile=agile, move=3, is_player=is_player)
    u.x, u.y = x, y
    u.equipment = tuple(equipment)
    if skills is not None:
        u.known_skills = list(skills)
    return u


def _battle(players, enemies, seed=1):
    return TacticsBattle(players=players, enemies=enemies, battle_map=BattleMap(32, 32), rng=random.Random(seed),
                         player_positions=[(u.x, u.y) for u in players],
                         enemy_positions=[(u.x, u.y) for u in enemies])


def test_mp_cost_and_shields():
    p = _u('美娜', mp=20, max_mp=20)
    assert energy.mp_cost(p, 0x0e) == 20                        # 大恢復
    assert energy.can_cast(p, 0x0e)
    energy.pay(p, 0x0e)
    assert p.mp == 0 and not energy.can_cast(p, 0x0e)
    p.equipment = (0xfa,)                                       # 脱皮盾 0xfa: 2 倍
    assert energy.mp_cost(p, 0x0a) == 10
    p.equipment = (0xfb,)                                       # 0xfb: 一半 (整除)
    assert energy.mp_cost(p, 0x0b) == 3                         # 療毒 7 // 2


def test_sg_thresholds_by_menu_position():
    p = _u('三藏法师', sg=7, skills=[0x14, 0x15, 0x16, 0x17, 0x18])
    assert [energy.can_cast(p, s) for s in p.known_skills] == [True, True, False, False, False]   # 2/5/8/12/16
    energy.pay(p, 0x15)                                         # 生命之火 5
    assert p.sg == 2
    s = _u('沙悟净', sg=6, skills=[0x1e, 0x1f])
    assert energy.can_cast(s, 0x1e) and not energy.can_cast(s, 0x1f)   # 6 / 16
    assert not energy.can_cast(_u('三藏法师', sg=0, mp=999, max_mp=999, skills=[0x14]), 0x14)  # SG 型不看 MP


def test_mp_type_has_no_sg_and_beast_cannot_cast():
    p = _u('孙悟空', mp=99, max_mp=99, sg=0xFFFFFFFF)
    assert not energy.uses_sg(p)
    energy.sg_gain(p)
    assert p.sg == 0xFFFFFFFF
    z = _u('紫河', mp=0, max_mp=0)
    z.zihe = {'transformed': True}
    assert energy.energy_type(z) == energy.ENERGY_NONE and not energy.can_cast(z, 0x3d)


def test_round_start_sg_gain():
    a = _u('三藏法师', 10, 10, sg=0)
    b = _u('破无', 11, 10, sg=0, equipment=(0x145, 0xf4))       # 火大的丝巾 + 血盾: 每回合 +3
    c = _u('捕山', 12, 10, sg=16)
    d = _u('蒙面人', 13, 10, sg=0)
    bt = _battle([a, b, c, d], [_u('e', 20, 20, is_player=False, agile=1)])   # 开战即第 1 回合
    assert (a.sg, b.sg, c.sg) == (1, 3, 16)                     # 封顶 16
    from core.battle.status import apply_status
    apply_status(d, 0x200, 3)                                   # 睡眠: 不涨
    d.sg = 0
    bt._start_round()
    assert (a.sg, b.sg, d.sg) == (2, 6, 0)


def test_hit_by_enemy_gains_sg_attacking_does_not():
    p = _u('猪八戒', 10, 10, sg=0)
    e = _u('e', 10, 11, is_player=False, agile=1)
    bt = _battle([p], [e])
    p.sg = 0
    from core.battle import combat
    combat.apply_damage(bt, e, p, 5, "")
    assert p.sg == 1
    combat.apply_damage(bt, p, e, 5, "")                        # 自己打人: 不涨
    assert p.sg == 1


def test_battle_item_formula():
    user = _u('美娜', mp=0, max_mp=500)
    user.wisdom = 40
    user.hp = 100
    bt = SimpleNamespace(rng=random.Random(3))
    r = random.Random(3).randrange(20)
    res = energy.battle_item(bt, user, user, 0x12b)             # 恢复药 威力 50
    assert res['hp'] == 50 * (r + 90) // 100 + 40 * 50 // 100
    res = energy.battle_item(bt, user, user, 0x130)             # MP 优药 10000 → 封顶
    assert res['mp'] == 500 and user.mp == 500
    s = _u('三藏法师', sg=3)
    assert energy.battle_item(bt, s, s, 0x13a) == {'sg': 13} and s.sg == 16   # 兴奋剂
    dead = _u('三藏法师')
    dead.hp = 0
    assert energy.battle_item(bt, s, dead, 0x12b) == {}         # 倒地: 普通药无效
    assert energy.battle_item(bt, s, dead, 0x134)['revived'] and dead.hp == 600 // 5   # 强力针灸


def _ch(hp, mhp, mp, mmp):
    return SimpleNamespace(CurrentHP=hp, MaxHP=mhp, CurrentMP=mp, MaxMP=mmp)


def test_field_use_rules():
    assert field_use(_ch(100, 100, 0, 50), 0x12b) is None      # HP 满: 没效果
    assert field_use(_ch(10, 100, 0, 0), 0x12e) is None        # SG 型 (MaxMP 0) 用不了 MP 药
    c = _ch(10, 100, 0, 999)
    assert field_use(c, 0x12f) == (0, 300)                      # MP 良药: 场外固定 +300
    assert field_use(c, 0x131) == (90, 699)                     # 仙桃
    party = [_ch(1, 50, 0, 10), _ch(2, 60, 0, 0)]
    field_use(party[0], 0x133, party)                           # 魔法的白粉: 全队
    assert [(p.CurrentHP, p.CurrentMP) for p in party] == [(50, 10), (60, 0)]


def test_write_back():
    ch = _ch(0, 0, 5, 30)
    ch.SG = 0
    p = _u('三藏法师', sg=9)
    p.save_ref = ch
    m = _u('美娜', mp=12, max_mp=30)
    ch2 = _ch(0, 0, 30, 30)
    m.save_ref = ch2
    energy.write_back(SimpleNamespace(players=[p, m]))
    assert ch.SG == 9 and ch2.CurrentMP == 12
