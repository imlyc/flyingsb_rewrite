"""combat.py: miss/damage 数学 + reaction 触发 + 死亡分支."""

import random

from core.battle import combat
from core.battle.data import (
    AGILE_MISS_FACTOR,
    BASE_MISS_RATE,
    BattleMap,
    BattleUnit,
    DamageEvent,
    MAX_MISS_RATE,
)
from core.battle.queries import BattleQueries


def _unit(name, x, y, *, hp=20, atk=10, defense=2, agile=10, is_player=True):
    u = BattleUnit(
        name=name, level=1, max_hp=hp, hp=hp,
        max_mp=0, mp=0, sg=0,
        attack=atk, defence=defense, agile=agile,
        move=3, is_player=is_player,
    )
    u.x, u.y = x, y
    return u


class _FakeBattle:
    """combat.* 只用 rng / damage_events / _log / engine (hit-effect spawn), 拼一个最小 stub."""
    def __init__(self, seed=0):
        from core.anim_engine.engine import Engine
        self.rng = random.Random(seed)
        self.damage_events: list[DamageEvent] = []
        self.messages: list[str] = []
        self.players: list[BattleUnit] = []
        self.enemies: list[BattleUnit] = []
        self.map = BattleMap(10, 10)
        self.q = BattleQueries(self.map, self.players, self.enemies)
        self.engine = Engine()

    def _log(self, m): self.messages.append(m)


# ---- miss_chance ----

def test_miss_chance_equal_agile():
    """同 agile → 基础 miss 率."""
    a = _unit("a", 0, 0, agile=10)
    d = _unit("d", 1, 0, agile=10)
    assert combat.miss_chance(a, d) == BASE_MISS_RATE


def test_miss_chance_defender_faster():
    """defender 比攻击者快, miss 率上升."""
    a = _unit("a", 0, 0, agile=10)
    d = _unit("d", 1, 0, agile=30)
    expected = BASE_MISS_RATE + 20 * AGILE_MISS_FACTOR
    assert combat.miss_chance(a, d) == expected


def test_miss_chance_capped():
    """非常慢的 attacker 也不会超过 MAX_MISS_RATE."""
    a = _unit("a", 0, 0, agile=1)
    d = _unit("d", 1, 0, agile=999)
    assert combat.miss_chance(a, d) == MAX_MISS_RATE


def test_miss_chance_floor_at_zero():
    """attacker 远快于 defender, miss 率不能为负."""
    a = _unit("a", 0, 0, agile=999)
    d = _unit("d", 1, 0, agile=1)
    assert combat.miss_chance(a, d) == 0.0


# ---- apply_damage ----

def test_apply_damage_basic():
    b = _FakeBattle()
    a, d = _unit("a", 0, 0), _unit("d", 1, 0, hp=20)
    combat.apply_damage(b, a, d, 7, "")
    assert d.hp == 13
    assert len(b.damage_events) == 1
    ev = b.damage_events[0]
    assert ev.damage == 7 and ev.remaining_hp == 13 and not ev.miss
    assert d.reaction_seq is not None       # 触发受击反应


def test_apply_damage_lethal_clamps_hp():
    b = _FakeBattle()
    a, d = _unit("a", 0, 0), _unit("d", 1, 0, hp=5)
    combat.apply_damage(b, a, d, 99, "")
    assert d.hp == 0
    assert not d.alive


def test_apply_damage_defers_displayed_hp_to_settlement():
    """逻辑 hp 立即扣 (AI/胜负用真值), 但显示 hp + 虚弱/死亡视觉延迟到结算."""
    b = _FakeBattle()
    a, d = _unit("a", 0, 0), _unit("d", 1, 0, hp=20)
    combat.apply_damage(b, a, d, 15, "")        # 20→5 (虚弱阈值 40% of 20 = 8, 5<8)
    # 逻辑 hp 立即变
    assert d.hp == 5
    # 显示 hp 仍是旧值, 受击/虚弱视觉被抑制 (settle_pending)
    assert d.settle_pending is True
    assert d.display_hp == 20
    assert d.display_weakened is False          # 显示层还没虚弱
    # 受击反应结束 → commit HP (存活, 早于闪烁)
    d.commit_hp()
    assert d.display_hp == 5
    assert d.display_weakened is True
    # 闪烁信号 → 虚弱/死亡视觉放行
    d.release_death_visual()
    assert d.settle_pending is False


def test_dying_enemy_keeps_old_hp_display():
    """致死攻击: 死亡敌人保持受击前 HP 显示 (原版死亡闪烁不显 0, 保持原值直到消失)."""
    b = _FakeBattle()
    a, d = _unit("a", 0, 0), _unit("d", 1, 0, hp=12)
    combat.apply_damage(b, a, d, 99, "")        # 12→0 致死
    assert d.hp == 0 and not d.alive
    assert d.display_hp == 12                    # 受击前旧值
    d.commit_hp()                                # 死亡 → 不提交, 保留旧值
    assert d.display_hp == 12
    d.release_death_visual()
    assert d.display_hp == 12                    # 直到消失都显旧值


def test_multi_impact_damages_only_on_last():
    """多段攻击 (无限刀 5 IMPACT): 只 *最后* 一段结算伤害, 之前的仅触发视觉反馈."""
    b = _FakeBattle(seed=0)
    a = _unit("a", 0, 0, atk=20, agile=100)
    d = _unit("d", 1, 0, hp=100, defense=0, agile=0)
    a.pending_attack_target = d
    a.pending_impact_count = 0
    a.pending_impact_total = 5             # 5 段

    initial_hp = 100
    # 前 4 次 IMPACT — 不出伤害
    for i in range(4):
        combat.apply_pending_attack(b, a)
        assert len(b.damage_events) == 0, f"impact #{i+1} 不该出伤害事件"
        assert d.hp == initial_hp, f"impact #{i+1} 不该掉血"
    # 第 5 次 (最后) — 出伤害
    combat.apply_pending_attack(b, a)
    assert len(b.damage_events) == 1
    assert d.hp < initial_hp
    # 反应动画在每次 IMPACT 都触发
    assert d.reaction_seq is not None


def test_single_impact_skill_damages_on_first_call():
    """单段攻击 (total=1) 第 1 次 = 最后一次, 直接结算."""
    b = _FakeBattle(seed=0)
    a = _unit("a", 0, 0)
    d = _unit("d", 1, 0, hp=20)
    a.pending_attack_target = d
    a.pending_impact_count = 0
    a.pending_impact_total = 1
    combat.apply_pending_attack(b, a)
    assert len(b.damage_events) == 1
    assert d.hp < 20


def test_set_reaction_turns_defender_toward_attacker():
    """defender 在 (5,5), attacker 在 (8,5) (右侧) → defender 朝右."""
    a = _unit("a", 8, 5)
    d = _unit("d", 5, 5)
    d.facing = (0, 1)   # 初始朝下
    combat.set_reaction(d, "hit", attacker=a)
    assert d.facing == (1, 0)   # 转面向攻击者 (右)
    assert d.reaction_saved_facing == (0, 1)   # 保存原朝向供动画结束还原


def test_set_reaction_dodge_kind():
    a = _unit("a", 0, 0)
    d = _unit("d", 1, 0)
    combat.set_reaction(d, "dodge", attacker=a)
    assert d.reaction_seq is not None
    # hit / dodge 拿不同的 seq table; 不深入细节, 这里只确认有挂上


# ---- strike_skill (必杀, 不能 miss, 伤害 x2) ----

def test_strike_skill_double_damage():
    """必杀公式 max(1, (attack - defense + rng) * 2)."""
    b = _FakeBattle(seed=42)
    a = _unit("a", 0, 0, atk=20)
    d = _unit("d", 1, 0, hp=50, defense=5)
    combat.strike_skill(b, a, d)
    # rng.randint(-5, 5) 的特定 seed 值不重要, 但伤害必然 = max(1, (20-5+x)*2) >= 20
    assert d.hp < 50
    ev = b.damage_events[0]
    assert ev.damage >= 20      # (15 + (-5..5)) * 2 ≥ 20
    assert ev.damage <= 40


def test_strike_skill_min_damage_1():
    """攻击力远低于防御也至少打 1 (max(1, ...))."""
    b = _FakeBattle(seed=0)
    a = _unit("a", 0, 0, atk=1)
    d = _unit("d", 1, 0, hp=20, defense=999)
    combat.strike_skill(b, a, d)
    assert b.damage_events[0].damage >= 1


# ---- begin_attack / clear_pending_attack ----

def test_begin_attack_sets_pending_and_spawns_entity():
    """begin_attack 应该挂上 entity + 设 pending target."""
    b = _FakeBattle()
    # 把 engine 注入 (begin_attack 用 battle.engine.spawn/attach_seq)
    from core.anim_engine.engine import Engine
    b.engine = Engine()
    a = _unit("a", 5, 5)
    a.facing = (1, 0)
    d = _unit("d", 6, 5, is_player=False)
    combat.begin_attack(b, a, d)
    assert a.pending_attack_target is d
    assert a.entity is not None
    assert a.entity.user_data.get('unit') is a


def test_clear_pending_attack_resets_entity():
    b = _FakeBattle()
    from core.anim_engine.engine import Engine
    b.engine = Engine()
    a = _unit("a", 0, 0)
    a.facing = (1, 0)
    d = _unit("d", 1, 0, is_player=False)
    combat.begin_attack(b, a, d)
    combat.clear_pending_attack(a)
    assert a.pending_attack_target is None
    assert a.entity.flags & 0x20000 == 0    # playing flag cleared
    assert a.entity.seq == b''
