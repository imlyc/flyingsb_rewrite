"""TacticsBattle: 回合切换 / 胜负检测 / 玩家行动."""

import random

from core.battle.data import BattleMap, BattleUnit, Phase
from core.battle.tactics import TacticsBattle


def _player(name, x, y, *, hp=20, atk=10, agile=10, move=3):
    return _unit(name, x, y, hp=hp, atk=atk, agile=agile, move=move, is_player=True)


def _enemy(name, x, y, *, hp=20, atk=10, agile=5, move=3):
    return _unit(name, x, y, hp=hp, atk=atk, agile=agile, move=move, is_player=False)


def _unit(name, x, y, *, hp, atk, agile, move, is_player):
    u = BattleUnit(
        name=name, level=1, max_hp=hp, hp=hp,
        max_mp=0, mp=0, sg=0,
        attack=atk, defence=0, agile=agile,
        move=move, is_player=is_player,
    )
    u.x, u.y = x, y
    return u


def _battle(*, players, enemies, w=10, h=10):
    return TacticsBattle(
        players=players, enemies=enemies,
        battle_map=BattleMap(w, h),
        rng=random.Random(0),
        player_positions=[(p.x, p.y) for p in players],
        enemy_positions=[(e.x, e.y) for e in enemies],
    )


def test_turn_order_by_agile():
    """回合顺序按 agile 降序排."""
    fast = _player("fast", 1, 1, agile=20)
    slow = _enemy("slow", 8, 8, agile=5)
    medium = _player("med", 2, 1, agile=10)
    b = _battle(players=[fast, medium], enemies=[slow])
    assert [u.name for u in b.turn_order] == ["fast", "med", "slow"]


def test_initial_phase_player_move_for_player_first():
    p = _player("p", 1, 1, agile=20)
    e = _enemy("e", 8, 8, agile=5)
    b = _battle(players=[p], enemies=[e])
    assert b.phase == Phase.PLAYER_MOVE
    assert b.current is p
    assert b._pre_move_pos == (1, 1)


def test_initial_phase_enemy_turn_for_enemy_first():
    """敌人 agile 更高 → 第一回合是 ENEMY_TURN. AI 延后执行 (pending), 等 scene 触发."""
    p = _player("p", 1, 1, agile=5)
    e = _enemy("e", 2, 1, agile=20)  # 邻接, AI 应直接 face + plan attack
    b = _battle(players=[p], enemies=[e])
    assert b.phase == Phase.ENEMY_TURN
    assert b.current is e
    # 移动范围预先算好 (= scene 显示用)
    assert (e.x, e.y) in b.turn_move_range
    # AI 尚未执行: pending=True, 没 pending_enemy_attack
    assert b._enemy_ai_pending is True
    assert b._pending_enemy_attack is None
    # scene 触发后 AI 执行 → 邻接 player → 设 pending_enemy_attack
    b.run_pending_enemy_ai()
    assert b._enemy_ai_pending is False
    assert b._pending_enemy_attack is p


def test_player_step_in_move_range():
    """move 范围内 + 通行 + 空闲 → 走一步."""
    p = _player("p", 5, 5, move=3)
    e = _enemy("e", 9, 9)
    b = _battle(players=[p], enemies=[e])
    ok = b.player_step(1, 0)
    assert ok and (p.x, p.y) == (6, 5)
    assert p.facing == (1, 0)


def test_player_step_blocked_by_unit():
    p = _player("p", 5, 5, move=3, agile=20)
    blocker = _enemy("b", 6, 5, agile=5)
    b = _battle(players=[p], enemies=[blocker])
    ok = b.player_step(1, 0)
    assert not ok and (p.x, p.y) == (5, 5)
    # 朝向仍然更新 (语义: 撞墙也转身)
    assert p.facing == (1, 0)


def test_player_step_out_of_range():
    p = _player("p", 5, 5, move=1, agile=20)
    e = _enemy("e", 9, 9, agile=5)
    b = _battle(players=[p], enemies=[e])
    assert b.player_step(1, 0)              # 1 步内可达
    assert not b.player_step(1, 0)          # 第 2 步超 move=1


def test_enter_aim_then_confirm_no_target():
    """PLAYER_MOVE 进 AIM, 朝向无敌人时 Enter 不发动攻击."""
    p = _player("p", 5, 5, agile=20)
    e = _enemy("e", 9, 9, agile=5)
    b = _battle(players=[p], enemies=[e])
    assert b.enter_attack_aim()
    assert b.phase == Phase.PLAYER_AIM
    p.facing = (0, 1)                       # 朝下, 没人
    assert not b.confirm_attack_aim()
    assert b.phase == Phase.PLAYER_AIM      # 仍在 aim, 继续选目标


def test_cancel_attack_aim_returns_to_move():
    """AIM 阶段 ESC 取消 → 回到 PLAYER_MOVE."""
    p = _player("p", 5, 5, agile=20)
    e = _enemy("e", 9, 9, agile=5)
    b = _battle(players=[p], enemies=[e])
    b.enter_attack_aim()
    assert b.cancel_attack_aim()
    assert b.phase == Phase.PLAYER_MOVE


def test_aim_turn_facing_recomputes_pattern():
    """AIM shift+方向键: 转 facing + 重算 pattern + cursor 跟到新 facing 格."""
    p = _player("p", 5, 5, agile=20)
    e = _enemy("e", 9, 9, agile=5)
    b = _battle(players=[p], enemies=[e])
    p.facing = (0, 1)                      # 朝下
    b.enter_attack_aim()
    assert b.aim_cursor == (5, 6)           # facing 前一格
    assert b.aim_attack_range == {(5, 6)}   # 默认攻击范围单格
    assert b.aim_turn_facing(1, 0)          # 转向右
    assert p.facing == (1, 0)
    assert b.aim_cursor == (6, 5)
    assert b.aim_attack_range == {(6, 5)}
    assert (p.x, p.y) == (5, 5)             # unit 位置没动


def test_aim_move_cursor_constrained_by_pattern():
    """普攻 pattern 只有 1 格, 方向键移 cursor 应该不动 (无邻接合法位置)."""
    p = _player("p", 5, 5, agile=20)
    e = _enemy("e", 9, 9, agile=5)
    b = _battle(players=[p], enemies=[e])
    p.facing = (1, 0)
    b.enter_attack_aim()
    assert b.aim_cursor == (6, 5)
    assert not b.aim_move_cursor(0, 1)      # 单格 pattern, 不能动
    assert b.aim_cursor == (6, 5)


def test_aim_confirm_attacks_cursor_target():
    """confirm 攻击 cursor 上的敌人, 而非 facing 格 (= 远程时这两个可能不同)."""
    p = _player("p", 5, 5, agile=20)
    e = _enemy("e", 6, 5, agile=5)          # 邻接, 在普攻 pattern 内
    b = _battle(players=[p], enemies=[e])
    p.facing = (1, 0)
    b.enter_attack_aim()
    assert b.aim_cursor == (6, 5)
    assert b.confirm_attack_aim()           # cursor 上有敌, 攻击成功


def test_check_end_victory_when_all_enemies_dead():
    """所有敌人 hp=0 → 进 VICTORY phase + 累计奖励."""
    p = _player("p", 1, 1, agile=20)
    e = _enemy("e", 2, 1, agile=5)
    e.exp_reward, e.money_reward = 100, 50
    b = _battle(players=[p], enemies=[e])
    e.hp = 0
    # 直接调内部 _check_end (= end_unit_turn 流程后会走到)
    assert b._check_end()
    assert b.phase == Phase.VICTORY
    assert b.exp_gained == 100
    assert b.money_gained == 50


def test_check_end_defeat_when_all_players_dead():
    p = _player("p", 1, 1, agile=20)
    e = _enemy("e", 2, 1, agile=5)
    b = _battle(players=[p], enemies=[e])
    p.hp = 0
    assert b._check_end()
    assert b.phase == Phase.DEFEAT


def test_cancel_to_move_restores_position():
    """X 键: 把当前单位拉回回合起点."""
    p = _player("p", 5, 5, move=3)
    e = _enemy("e", 9, 9)
    b = _battle(players=[p], enemies=[e])
    b.player_step(1, 0)
    b.player_step(1, 0)
    assert (p.x, p.y) == (7, 5)
    assert b.cancel_to_move()
    assert (p.x, p.y) == (5, 5)


def test_next_actor_skips_current():
    p1 = _player("p1", 1, 1, agile=20)
    p2 = _player("p2", 2, 1, agile=15)
    e = _enemy("e", 9, 9, agile=5)
    b = _battle(players=[p1, p2], enemies=[e])
    # current=p1, 下一行动 = p2
    assert b.next_actor() is p2


def test_player_use_skill_consumes_sg():
    """必杀消耗 10 SG; 范围内只一敌, ×2 伤害."""
    p = _player("p", 5, 5, agile=20)
    p.sg = 30
    e = _enemy("e", 6, 5, agile=5, hp=999)   # 邻接, 够 attack range
    b = _battle(players=[p], enemies=[e])
    p.facing = (1, 0)
    ok = b.player_use_skill()
    assert ok
    assert p.sg == 20                        # 扣了 10
    assert e.hp < 999                        # 受伤


def test_player_use_skill_no_target():
    """攻击范围内无敌人 → 不消耗 SG, 返回 False."""
    p = _player("p", 5, 5, agile=20)
    p.sg = 30
    e = _enemy("e", 9, 9, agile=5)           # 太远
    b = _battle(players=[p], enemies=[e])
    assert not b.player_use_skill()
    assert p.sg == 30                        # 未扣


def test_player_use_skill_insufficient_sg():
    p = _player("p", 5, 5, agile=20)
    p.sg = 5
    e = _enemy("e", 6, 5, agile=5)
    b = _battle(players=[p], enemies=[e])
    assert not b.player_use_skill()
    assert p.sg == 5
