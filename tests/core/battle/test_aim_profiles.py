"""每个角色的 aim pattern + strike 规则."""

from core.battle.aim_profiles import (
    AIM_PROFILES,
    get_aim_funcs,
    pattern_box,
    pattern_forward_line,
    strike_perpendicular_line,
    strike_single,
)
from core.battle.data import BattleMap, BattleUnit


def _unit(name="x", facing=(1, 0), x=5, y=5):
    u = BattleUnit(name=name, level=1, max_hp=10, hp=10, max_mp=0, mp=0, sg=0,
                   attack=5, defence=0, agile=10, move=3, is_player=True)
    u.x, u.y = x, y
    u.facing = facing
    return u


def _map(w=20, h=20):
    return BattleMap(w, h)


# ---- 基础 pattern / strike 公式 ----

def test_pattern_forward_line_3():
    u = _unit(facing=(1, 0), x=5, y=5)
    p = pattern_forward_line(u, _map(), depth=3)
    assert p == {(6, 5), (7, 5), (8, 5)}


def test_pattern_forward_line_clipped_at_map_edge():
    u = _unit(facing=(1, 0), x=18, y=5)
    p = pattern_forward_line(u, _map(20, 20), depth=3)
    # x=19 在内, x=20/21 越界
    assert p == {(19, 5)}


def test_pattern_box_3_wide_2_deep_facing_right():
    """face right (1,0): 前方 2 深 × 3 横宽 = (x+1..x+2, y-1..y+1)."""
    u = _unit(facing=(1, 0), x=5, y=5)
    p = pattern_box(u, _map(), depth=2, width=3)
    assert p == {
        (6, 4), (6, 5), (6, 6),
        (7, 4), (7, 5), (7, 6),
    }


def test_pattern_box_facing_down():
    """face down (0,1): perp 是 (1, 0). 前方 2 行 × 3 列."""
    u = _unit(facing=(0, 1), x=5, y=5)
    p = pattern_box(u, _map(), depth=2, width=3)
    assert p == {
        (4, 6), (5, 6), (6, 6),
        (4, 7), (5, 7), (6, 7),
    }


def test_strike_perpendicular_line_facing_right():
    """face right, cursor 在 (7, 5): perp = (0, ±1), 线 = (7,4)(7,5)(7,6)."""
    u = _unit(facing=(1, 0))
    s = strike_perpendicular_line(u, (7, 5), length=3)
    assert s == {(7, 4), (7, 5), (7, 6)}


def test_strike_perpendicular_line_facing_down():
    """face down, perp = (1, 0), 线水平."""
    u = _unit(facing=(0, 1))
    s = strike_perpendicular_line(u, (5, 7), length=3)
    assert s == {(4, 7), (5, 7), (6, 7)}


def test_strike_single():
    u = _unit()
    assert strike_single(u, (3, 4)) == {(3, 4)}


# ---- 角色注册表 ----
# 注意: 当前 AIM_PROFILES 为空, 所有角色走 default (= 面前 1 格 / 单点).
# 角色专属 profile 的回归测试等加入新 entry 时再补.

def test_aim_profile_default_fallback():
    """所有未注册角色 → 默认: 攻击范围 = 面前 1 格, 伤害范围 = cursor 单点."""
    for name in ("孙悟空", "蒙面人", "未知角色"):
        pattern_fn, strike_fn = get_aim_funcs(name)
        u = _unit(name=name, facing=(1, 0), x=5, y=5)
        assert pattern_fn(u, _map()) == {(6, 5)}, f"{name} pattern"
        assert strike_fn(u, (6, 5)) == {(6, 5)}, f"{name} strike"
