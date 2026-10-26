"""敌方 AI exe 移植 (core.battle.ai_exe = FUN_004b1286 / 4aece7 / 4b0532 / 4b1084) 的固定局面."""

import random

from core.battle import ai_exe
from core.battle.data import BattleMap, BattleUnit
from core.battle.tactics import TacticsBattle

MELEE, FIREBALL, DASH, HEAL_SELF, SUMMON = 0, 3, 0x46, 31, 2


def _unit(name, x, y, *, is_player, move=3, moves=(), weights=(), etype=-1, hp=50):
    u = BattleUnit(name=name, level=1, max_hp=hp, hp=hp, max_mp=99, mp=99, sg=0,
                   attack=10, defence=0, agile=10, move=move, is_player=is_player)
    u.x, u.y = x, y
    u.enemy_moves = list(moves)
    u.move_weights = list(weights) or [10] * len(moves)
    u.enemy_type = etype
    return u


def _battle(players, enemies, w=12, h=12, seed=0, obstacles=()):
    m = BattleMap(w, h)
    m.obstacles |= set(obstacles)
    return TacticsBattle(players=players, enemies=enemies, battle_map=m, rng=random.Random(seed),
                         player_positions=[(p.x, p.y) for p in players],
                         enemy_positions=[(e.x, e.y) for e in enemies])


def test_aim_runs_keep_only_run_start():
    """FUN_004ade85 bug: run 右端写进下一槽 → 菱形瞄准 (模板 13) 每行只剩最左一格."""
    runs = ai_exe.aim_runs(13, 0)
    assert all(c0 == c1 for _, c0, c1 in runs)
    assert [r[0] for r in runs] == [-3, -2, -1, 0, 1, 2, 3]
    assert dict((r, c) for r, c, _ in runs)[0] == -3            # 中间行 7 格只剩 x-3


def test_rotation_matches_exe_dirs():
    """exe 方向 0 上 1 下 2 左 3 右: 近战模板 0 的瞄准格 = 前方一格."""
    assert ai_exe.aim_runs(0, 0) == ((-1, 0, 0),)
    assert ai_exe.aim_runs(0, 1) == ((1, 0, 0),)
    assert ai_exe.aim_runs(0, 2) == ((0, -1, -1),)
    assert ai_exe.aim_runs(0, 3) == ((0, 1, 1),)


def test_melee_only_one_reachable_side():
    """移动力 1, 只有正上方一格能打到玩家 → 站 (5,6) 朝上, 光标 = 玩家格."""
    p = _unit("美娜", 5, 5, is_player=True)
    e = _unit("怪", 5, 7, is_player=False, move=1, moves=[MELEE])
    b = _battle([p], [e])
    ai_exe.take_turn(b, e)
    assert (e.x, e.y) == (5, 6)
    assert e.post_move_facing == (0, -1)
    assert b._pending_enemy_cursor == (5, 5)
    assert b._pending_enemy_attack is p and b._pending_enemy_move == MELEE


def test_melee_stays_when_adjacent_from_left():
    """敌人在玩家左边相邻: 唯一可站格 (含原地) 里能罩玩家的就是原地, 朝右."""
    p = _unit("美娜", 5, 5, is_player=True)
    e = _unit("怪", 4, 5, is_player=False, move=1, moves=[MELEE], )
    b = _battle([p], [e], obstacles={(4, 4), (4, 6), (3, 5)})
    ai_exe.take_turn(b, e)
    assert (e.x, e.y) == (4, 5) and not e.move_path
    assert e.facing == (1, 0)
    assert b._pending_enemy_cursor == (5, 5)


def test_ranged_move_avoids_player_adjacent_tiles():
    """flags&3 == 2 的招 (召來巨大火炎彈) 走 FUN_004adff5 模式 1: 不站活玩家相邻格."""
    p = _unit("美娜", 5, 5, is_player=True)
    e = _unit("法师", 5, 6, is_player=False, move=3, moves=[FIREBALL])
    b = _battle([p], [e], seed=3)
    ai_exe.take_turn(b, e)
    assert b._pending_enemy_move == FIREBALL
    assert abs(e.x - p.x) + abs(e.y - p.y) != 1
    assert all(abs(x - p.x) + abs(y - p.y) != 1 for x, y in b._ai_stand)


def test_dash_abandoned_when_landing_off_map():
    """猛撞: 落点 = 站位 + 2×朝向; 玩家贴上边界, 敌人只能从下往上撞 → 落点 y=-1 越界 → 放弃 (只移动)."""
    p = _unit("美娜", 5, 0, is_player=True)
    e = _unit("火球", 5, 2, is_player=False, move=1, moves=[DASH])
    b = _battle([p], [e], obstacles={(4, 0), (6, 0)})
    ai_exe.take_turn(b, e)
    assert b._pending_enemy_move is None


def test_dash_ok_with_room_behind():
    """落点 (5,4) 空且洪水可达 (绕路, 不限步数) → 出招."""
    p = _unit("美娜", 5, 5, is_player=True)
    e = _unit("火球", 5, 7, is_player=False, move=1, moves=[DASH])
    b = _battle([p], [e], obstacles={(4, 7), (6, 7), (5, 8)})
    ai_exe.take_turn(b, e)
    assert b._pending_enemy_move == DASH
    assert (e.x, e.y) == (5, 6) and b._pending_enemy_cursor == (5, 5)


def test_dash_abandoned_when_landing_unreachable():
    """落点被墙围住 (洪水 7de67c < 0) → 放弃."""
    p = _unit("美娜", 5, 5, is_player=True)
    e = _unit("火球", 5, 7, is_player=False, move=1, moves=[DASH])
    b = _battle([p], [e], obstacles={(4, 7), (6, 7), (5, 8), (4, 4), (6, 4), (5, 3)})
    ai_exe.take_turn(b, e)
    assert b._pending_enemy_move is None


def test_heal_uses_global_stand_table():
    """优先招 (回复) 用全局可站格表 (上一次 FUN_004aece7 留下的); 表空 → 不回复, 走移动 fallback."""
    p = _unit("美娜", 1, 1, is_player=True)
    e = _unit("牧师", 8, 8, is_player=False, move=2, moves=[HEAL_SELF], etype=11, hp=100)
    e.hp = 10
    b = _battle([p], [e], seed=1)
    b._ai_stand = []
    ai_exe.take_turn(b, e)
    assert b._pending_enemy_move is None
    b._ai_stand = [(8, 8), (8, 9), (9, 8)]
    for seed in range(20):                     # ai_mode 10: 触发条件随机 (hp% < 50 - rand%20)
        b.rng = random.Random(seed)
        ai_exe.take_turn(b, e)
        if b._pending_enemy_move == HEAL_SELF:
            break
    assert b._pending_enemy_move == HEAL_SELF
    assert b._pending_enemy_attack is e
    assert (e.x, e.y) in {(8, 8), (8, 9), (9, 8)}
    assert b._pending_enemy_cursor == (e.x, e.y)


def test_fallback_moves_toward_target_mode_nearest():
    """没招能用 → FUN_004b1084: ai_mode 2 选最近玩家, 可站格里离它最近的 (曼哈顿)."""
    near = _unit("近", 8, 2, is_player=True)
    far = _unit("远", 0, 11, is_player=False)
    far.is_player = True
    e = _unit("怪", 8, 8, is_player=False, move=2, moves=[MELEE], etype=0)
    b = _battle([near, far], [e])
    ai = ai_exe.ExeAI(b, e)
    ai.ai_mode = 2
    ai._flood((e.x, e.y), ai_exe.FLOOD_TURN)
    ai.adf85(ai.rng_move)
    ai.adff5_ae20d(0)
    ai.b1084()
    assert (e.x, e.y) == (8, 6)


def test_summon_requires_space_and_low_calf_count():
    boss = _unit("牛魔王", 5, 5, is_player=False, moves=[SUMMON], etype=1)
    p = _unit("美娜", 0, 0, is_player=True)
    b = _battle([p], [boss], seed=0)
    hit = 0
    for seed in range(30):
        b.rng = random.Random(seed)
        b._pending_enemy_move = None
        ai_exe.take_turn(b, boss)
        hit += b._pending_enemy_move == SUMMON
    assert 0 < hit < 30                          # 0 只牛寶寶 < rand%7 → 6/7 概率
    calves = [_unit("牛寶寶", 5 + dx, 5 + dy, is_player=False, etype=0x17)
              for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1))]
    b2 = _battle([p], [boss] + calves)
    for seed in range(30):                       # 6 只 ≥ rand%7 恒成立 → 不召
        b2.rng = random.Random(seed)
        b2._pending_enemy_move = None
        ai_exe.take_turn(b2, boss)
        assert b2._pending_enemy_move != SUMMON
    b3 = _battle([p], [boss] + calves[:1])       # 场上还有 1 只就不召 (竞技场偏离 exe, 用户要求)
    for seed in range(30):
        b3.rng = random.Random(seed)
        b3._pending_enemy_move = None
        ai_exe.take_turn(b3, boss)
        assert b3._pending_enemy_move != SUMMON


def test_summon_spawns_calves_near_caster():
    from core.enemy_spells.m2 import SummonCalf, summon_cells
    boss = _unit("牛魔王", 5, 5, is_player=False, moves=[SUMMON], etype=1)
    p = _unit("美娜", 0, 0, is_player=True)
    b = _battle([p], [boss])
    cells = summon_cells(b, boss)
    assert all(abs(x - 5) + abs(y - 5) < 4 for x, y in cells) and (5, 5) not in cells
    sp = SummonCalf(b, boss, SUMMON)
    new = sp._spawn()
    assert len(new) == 3 and all(u.enemy_type == 0x17 and u in b.enemies for u in new)
    assert len({(u.x, u.y) for u in new}) == 3
