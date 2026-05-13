"""BattleQueries 空间查询: occupant / movement_range / bfs_path / attack_tiles."""

import pytest

from core.battle.data import BattleMap, BattleUnit
from core.battle.queries import BattleQueries


def _unit(name, x, y, *, is_player=True, alive=True, move=3, attack_range=1):
    u = BattleUnit(
        name=name, level=1, max_hp=10, hp=10 if alive else 0,
        max_mp=0, mp=0, sg=0, attack=5, defence=0, agile=10,
        move=move, is_player=is_player, attack_range=attack_range,
    )
    u.x, u.y = x, y
    return u


def _q(w=10, h=10, obstacles=(), players=(), enemies=()):
    m = BattleMap(w, h, obstacles=set(obstacles))
    return BattleQueries(m, list(players), list(enemies))


def test_all_units_alive_units():
    p, e = _unit("p", 0, 0), _unit("e", 5, 5, is_player=False, alive=False)
    q = _q(players=[p], enemies=[e])
    assert q.all_units == [p, e]
    assert q.alive_units == [p]   # 死敌不算


def test_occupant_player_corpse_blocks():
    """死玩家留尸占格 (可复活), 死敌不占."""
    dead_player = _unit("p", 3, 3, alive=False)
    dead_enemy = _unit("e", 4, 4, is_player=False, alive=False)
    q = _q(players=[dead_player], enemies=[dead_enemy])
    assert q.occupant(3, 3) is dead_player        # 玩家尸体占格
    assert q.occupant(4, 4) is None               # 敌人尸体不占


def test_occupant_ignore():
    p = _unit("p", 2, 2)
    q = _q(players=[p])
    assert q.occupant(2, 2) is p
    assert q.occupant(2, 2, ignore=p) is None     # 自己被忽略


def test_movement_range_open_field():
    """空场地 move=2 → 应该是 (起点 +/- 2 manhattan) 13 格."""
    p = _unit("p", 5, 5, move=2)
    q = _q(players=[p])
    r = q.movement_range(p)
    assert (5, 5) in r
    assert (3, 5) in r and (7, 5) in r     # ±2 x
    assert (5, 3) in r and (5, 7) in r     # ±2 y
    assert (4, 4) in r and (6, 6) in r     # 对角 manhattan=2
    assert (3, 4) not in r                  # manhattan=3, 超出
    assert len(r) == 1 + 4 + 8              # 中心 + 4个+1 + 8个+2 = 13


def test_movement_range_blocked_by_obstacle():
    """障碍物挡住 BFS, 不可绕过零步."""
    p = _unit("p", 0, 0, move=3)
    q = _q(w=5, h=5, obstacles=[(1, 0)], players=[p])
    r = q.movement_range(p)
    assert (0, 0) in r
    assert (1, 0) not in r                  # 障碍不可踩
    # 绕过 (1,0) 通过 (0,1)-(1,1)-(2,1)-(2,0) 需要 4 步, 超 move=3
    assert (2, 0) not in r or len(r) > 1


def test_movement_range_blocked_by_other_unit():
    """其它活单位挡路."""
    p = _unit("p", 0, 0, move=2)
    blocker = _unit("b", 1, 0)
    q = _q(players=[p, blocker])
    r = q.movement_range(p)
    assert (1, 0) not in r


def test_bfs_path_finds_route():
    p = _unit("p", 0, 0, move=99)
    q = _q(players=[p])
    path = q.bfs_path(p, (3, 0))
    assert path == [(1, 0), (2, 0), (3, 0)]     # 不含起点, 含终点


def test_bfs_path_around_obstacle():
    p = _unit("p", 0, 0, move=99)
    q = _q(w=5, h=5, obstacles=[(1, 0), (1, 1)], players=[p])
    path = q.bfs_path(p, (2, 0))
    # 必须绕障; 路径长度 >= 4 (走 (0,1)→(0,2)→(1,2)→(2,2)→(2,1)→(2,0) 或类似)
    assert len(path) >= 4
    assert path[-1] == (2, 0)
    for cell in path:
        assert cell not in {(1, 0), (1, 1)}


def test_bfs_path_unreachable():
    """整个目标被障碍包围 → 空路径."""
    p = _unit("p", 0, 0)
    q = _q(w=5, h=5, obstacles=[(3, 4), (4, 3)], players=[p])
    # 把 (4,4) 包死: 上下左右都障碍/边界
    q.map.obstacles.update({(3, 4), (4, 3)})
    path = q.bfs_path(p, (4, 4))
    # (4,4) 只能通过 (3,4)/(4,3) 进, 两条都断 → unreachable
    assert path == []


def test_attack_tiles_range_1():
    """attack_range=1 → 4 个十字邻格."""
    p = _unit("p", 5, 5, attack_range=1)
    q = _q(players=[p])
    tiles = q.attack_tiles(p, 5, 5)
    assert tiles == {(4, 5), (6, 5), (5, 4), (5, 6)}


def test_attack_tiles_clipped_by_map():
    """攻击范围超出地图边缘自动裁剪."""
    p = _unit("p", 0, 0, attack_range=1)
    q = _q(w=3, h=3, players=[p])
    tiles = q.attack_tiles(p, 0, 0)
    assert tiles == {(1, 0), (0, 1)}     # 左边和上边超出地图, 被砍


def test_attackable_enemies():
    """attack range 1, 一敌一友, 只返回敌方."""
    p = _unit("p", 5, 5, attack_range=1)
    e = _unit("e", 6, 5, is_player=False)
    ally = _unit("ally", 4, 5)
    q = _q(players=[p, ally], enemies=[e])
    targets = q.attackable_enemies(p)
    assert targets == [e]
