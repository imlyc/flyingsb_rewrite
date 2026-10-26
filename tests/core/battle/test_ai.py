"""敌方 AI: 技能优先 (真实敌人技能表驱动) / 无技能回退普攻."""

import random

from core.battle import ai
from core.battle.data import BattleMap, BattleUnit
from core.battle.tactics import TacticsBattle


def _unit(name, x, y, *, is_player):
    u = BattleUnit(name=name, level=1, max_hp=50, hp=50, max_mp=0, mp=0, sg=0,
                   attack=10, defence=0, agile=10, move=3, is_player=is_player)
    u.x, u.y = x, y
    return u


def _battle(players, enemies):
    return TacticsBattle(
        players=players, enemies=enemies, battle_map=BattleMap(10, 10),
        rng=random.Random(0),
        player_positions=[(p.x, p.y) for p in players],
        enemy_positions=[(e.x, e.y) for e in enemies],
    )


def test_enemy_ai_uses_skill_when_in_range():
    """敌人在射程内 → 选技能 (不是普攻); _pending_enemy_skill 被设置."""
    p = _unit("美娜", 5, 5, is_player=True)
    e = _unit("羊頭怪", 5, 6, is_player=False)
    e.known_skills = [48]
    e.move_weights = [0, 100]           # 总放招
    b = _battle([p], [e])
    # skill 48 的可达范围 + 伤害范围 (测试里直接给定: 命中玩家所在格)
    b.attack_range = lambda u=None, sid=None: {(p.x, p.y)}
    b.damage_range = lambda cursor, u=None, sid=None: {(p.x, p.y)}
    ai.take_turn(b, e)
    assert b._pending_enemy_skill == 48
    assert b._pending_enemy_attack is p


def test_enemy_ai_skips_heal_skills():
    """回血技能不参与选技能 → 无攻击技时退化为普攻."""
    p = _unit("美娜", 5, 5, is_player=True)
    e = _unit("牧师", 5, 6, is_player=False)
    e.known_skills = [0x15]      # 生命之火 (is_heal_skill)
    e.move_weights = [0, 100]
    b = _battle([p], [e])
    b.damage_range = lambda cursor, u=None, sid=None: {(p.x, p.y)}
    ai.take_turn(b, e)
    assert b._pending_enemy_skill is None
    assert b._pending_enemy_attack is p


def test_skill_chance_from_move_weights():
    """放招倾向 = 第 1..3 招权重 / 总权重 (原版敌人表 +0x50..)."""
    u = _unit("羊頭怪", 1, 1, is_player=False)
    u.move_weights = [70, 30]
    assert ai.skill_chance(u) == 0.3
    u.move_weights = [40, 30, 20, 10]
    assert ai.skill_chance(u) == 0.6
    assert ai.skill_chance(_unit("x", 1, 1, is_player=False)) == 0.3     # 无权重数据


def test_enemy_ai_moves_then_attacks_without_skills():
    """无技能 → 走向最近玩家; 到位后普攻."""
    p = _unit("美娜", 1, 1, is_player=True)
    e = _unit("骷髅", 8, 1, is_player=False)
    b = _battle([p], [e])
    ai.take_turn(b, e)
    assert b._pending_enemy_skill is None
    assert e.x < 8                                  # 朝玩家移动了
