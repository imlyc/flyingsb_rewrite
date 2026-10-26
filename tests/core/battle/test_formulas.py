"""core.battle.formulas = exe FUN_004a6efe 各分支, 用固定随机数逐项核对."""
from types import SimpleNamespace

from core.battle import formulas as F
from core.battle.data import BattleUnit


class FixedRng:
    """randrange(n) 依次返回给定值 (rand()%n)."""
    def __init__(self, *vals):
        self.vals = list(vals)

    def randrange(self, n):
        v = self.vals.pop(0)
        assert 0 <= v < n, (v, n)
        return v


def _b(*vals):
    return SimpleNamespace(rng=FixedRng(*vals))


def _p(**kw):
    u = BattleUnit(name='孙悟空', level=kw.pop('level', 30), max_hp=500, hp=500, max_mp=50, mp=50, sg=0,
                   attack=kw.pop('attack', 300), defence=kw.pop('defence', 200), agile=50, move=5, is_player=True)
    u.luck, u.wisdom = kw.pop('luck', 40), kw.pop('wisdom', 60)
    for k, v in kw.items():
        setattr(u, k, v)
    return u


def _e(**kw):
    u = BattleUnit(name='e', level=kw.pop('level', 30), max_hp=2000, hp=kw.pop('hp', 2000), max_mp=200, mp=200, sg=0,
                   attack=kw.pop('attack', 400), defence=kw.pop('defence', 100), agile=10, move=4, is_player=False)
    u.luck, u.wisdom, u.evade, u.magic_atk = kw.pop('luck', 10), kw.pop('wisdom', 30), kw.pop('evade', 0), kw.pop('magic_atk', 150)
    for k, v in kw.items():
        setattr(u, k, v)
    return u


def test_dir_index_front_side_back_and_sleep():
    t = _e()
    t.x, t.y, t.facing = 5, 5, (0, -1)               # 面朝上
    a = _p()
    a.x, a.y = 5, 4                                    # 正面
    assert F.dir_index(a, t) == 0
    a.x, a.y = 6, 5                                    # 侧面
    assert F.dir_index(a, t) == 2
    a.x, a.y = 5, 6                                    # 正背后
    assert F.dir_index(a, t) == 4
    a.x, a.y = 5, 4
    t.status_bits = F.SLEEP
    assert F.dir_index(a, t) == 4


def test_element_and_affinity():
    assert F.element_mult(0, 0x2000000) == 100
    assert F.element_mult(0x1000000, 0x2000000) == 170
    assert F.element_mult(0x1000000, 0x8000000) == 50
    a, d = _p(status_bits=0x2000), _e(type_flags=0x1000)    # 幸運進行曲 vs 咀咒
    assert F.affinity(a, d) == 20


def test_player_normal_hit_crit_damage():
    p, e = _p(level=30, luck=40), _e(level=30, luck=10, defence=100, evade=5)
    p.x, p.y, e.x, e.y, e.facing = 5, 4, 5, 5, (0, -1)    # 正面, 方位 0
    # 命中率 = 0 + 80 - 5 + 40 - 10 + 0 + 30/3 = 115 → 90; 骰 50 命中
    # 暴击 = 40 + 5 - 10 + 30 + 0 - 30 = 35; 骰 34 → 暴击; 伤害骰 rand%40 = 20 → 100%
    out = F.player_normal(_b(50, 34, 20), p, e, 0x4001)
    assert out.hit and out.crit
    assert out.dmg == (300 - 100) * 100 // 100 * 2
    out = F.player_normal(_b(95), p, e, 0x4001)       # 骰 95 ≥ 90 → 落空
    assert not out.hit


def test_player_normal_small_base_and_falloff():
    p, e = _p(attack=50), _e(defence=100)
    p.x, p.y, e.x, e.y, e.facing = 5, 4, 5, 5, (0, -1)
    # 攻 - 防 < 5 → rand%5+1 = 3; 不暴击 (骰 100); 伤害骰 0 → 80%; 衰减 4/8
    out = F.player_normal(_b(0, 100, 2, 0), p, e, 0x4001, falloff=4)
    assert out.dmg == (3 * 80 // 100) * 4 // 8


def test_player_physical_skill_half_defence():
    p, e = _p(attack=300), _e(defence=100)
    p.x, p.y, e.x, e.y, e.facing = 5, 4, 5, 5, (0, -1)
    sid = 0x16                                         # 不敗三擊 (0x00804021: 物理, 威力 330)
    out = F.player_skill(_b(0, 100, 20), p, e, sid)
    assert out.hit and not out.magic
    assert out.dmg == (300 - 50) * 100 // 100 * 330 // 100


def test_player_magic_skill_formula_and_hp_cap():
    p, e = _p(level=20, wisdom=80), _e(wisdom=30, hp=50)
    sid = 0x0c                                         # 聖水 (法术, 威力 35)
    out = F.player_skill(_b(10), p, e, sid)
    expect = (35 + 40) * 100 // 100 + (80 - 30) * 35 // 200
    assert out.magic and out.hit and out.dmg == min(expect, 50)


def test_enemy_physical_and_guard():
    e, p = _e(attack=400, luck=10, level=30), _p(defence=200, luck=40, level=30)
    e.x, e.y, p.x, p.y, p.facing = 5, 4, 5, 5, (0, -1)
    # 命中 = 80 - 40 + 10 = 50, 骰 10 命中; 暴击 = 5 - 40 + 10 - 30 + 30 = -25 不暴击; 伤害骰 20
    out = F.enemy_attack(_b(10, 0, 20), e, p, None)
    assert out.hit and not out.crit and out.dmg == (400 - 100) * 100 // 100
    p.status_bits = F.ST_GUARD
    out = F.enemy_attack(_b(10, 0, 20), e, p, None)
    assert out.dmg == (400 - 100) * 100 // 100 * 65 // 100


def test_enemy_magic_always_hits():
    e, p = _e(magic_atk=150, wisdom=30), _p(wisdom=60)
    e.x, e.y, p.x, p.y = 5, 4, 5, 5
    out = F.enemy_attack(_b(100, 100, 10), e, p, 7)    # 7 = 施放魔法風暴 (法术, 威力 120)
    assert out.hit and out.magic
    assert out.dmg == (150 + 30 - 60) * 120 * 100 // 10000


def test_heal_amount_magic_and_physical():
    c = _p(wisdom=60, attack=300)
    assert F.heal_amount(_b(10), c, 0x0a) == 60 * 100 // 100 + 60 * 60 // 100      # 小回復 威力 60
    assert F.heal_amount(_b(10), c, 0x15) == 300 * 100 // 100                     # 生命之火: 物理型 = 攻击


def test_mp_drain():
    c, e = _p(wisdom=60), _e(wisdom=30)
    c.max_mp = 400
    e.max_mp, e.mp = 200, 80
    from core.skill_table import SKILL_TABLE
    k = SKILL_TABLE[0x3d][1] + (60 - 30) // 2              # 威力 (技能表 +0xc) + 智力差/2
    assert F.mp_drain(None, c, e, 0x3d) == min(200 * k // 100, 400 // 4, 80)
    e.type_flags = 0x20
    assert F.mp_drain(None, c, e, 0x3b) == 25 and F.mp_drain(None, c, e, 0x3d) == 5


def test_counter_check_and_damage():
    p, e = _p(attack=300, defence=200), _e(attack=400, defence=100)
    p.x, p.y, p.facing = 5, 4, (0, 1)                  # 面朝下, 敌人在正前方
    e.x, e.y, e.facing = 5, 5, (0, -1)
    e.unit_class = 0                                   # 反击率 [30, 28, 25, 22, 20]
    out = F.Outcome(hit=True, roll=75, dir=0)          # 100 - 75 = 25 < 30 → 反击
    assert F.counter_check(p, e, out, 0x4011)
    out.roll = 70                                      # 30 不 < 30
    assert not F.counter_check(p, e, out, 0x4011)
    out.roll = 90
    assert not F.counter_check(p, e, out, 0x4001)      # 无 0x10 不可反击
    out.crit = True
    assert not F.counter_check(p, e, out, 0x4011)      # 暴击不反击
    # 敌反击我方: 会心骰 rand%10=3 (非会心 → 40..79%), 伤害骰 20 → 60%; 攻 - 我防 (全额)
    dmg, crit = F.counter_damage(_b(3, 20), e, p)
    assert not crit and dmg == (400 - 200) * 60 // 100
    p.status_bits = F.ST_GUARD                         # 強力防禦 ×70%
    dmg, crit = F.counter_damage(_b(0, 20), e, p)      # rand%10=0 → 会心 70..109%
    assert crit and dmg == (400 - 200) * 90 // 100 * 70 // 100
