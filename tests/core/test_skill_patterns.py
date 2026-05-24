"""技能 AOE pattern 计算: 旋转 / 边界 / 5 个已知锚点真值对比."""

from core.battle.data import BattleMap, BattleUnit
from core.skill_patterns import (
    _rotate,
    compute_skill_pattern,
    compute_skill_strike,
    skill_template_idx,
)


def _unit(facing=(0, -1), x=10, y=10):
    u = BattleUnit(name="x", level=1, max_hp=10, hp=10, max_mp=0, mp=0, sg=0,
                   attack=5, defence=0, agile=10, move=3, is_player=True)
    u.x, u.y = x, y
    u.facing = facing
    return u


def _map(w=30, h=30):
    return BattleMap(w, h)


# ---- 旋转工具 ----

def test_rotate_identity_when_facing_up():
    assert _rotate(0, -1, (0, -1)) == (0, -1)  # forward stays forward
    assert _rotate(1, 0, (0, -1)) == (1, 0)
    assert _rotate(-1, 0, (0, -1)) == (-1, 0)


def test_rotate_to_right():
    # default up forward (0,-1) → right facing forward (1, 0)
    assert _rotate(0, -1, (1, 0)) == (1, 0)
    # default up side (+1, 0) right side under up = right under facing-right = (0, 1) = down
    assert _rotate(1, 0, (1, 0)) == (0, 1)


def test_rotate_to_down():
    assert _rotate(0, -1, (0, 1)) == (0, 1)
    assert _rotate(1, 0, (0, 1)) == (-1, 0)


def test_rotate_to_left():
    assert _rotate(0, -1, (-1, 0)) == (-1, 0)
    assert _rotate(1, 0, (-1, 0)) == (0, -1)


# ---- skill_id → tmpl_idx 映射 ----

def test_skill_template_idx_known_anchors():
    # 5 用户实测点 (project_skill_system.md)
    assert skill_template_idx(0x08) == 22   # 超亂舞
    assert skill_template_idx(0x14) == 0    # 南瓜破
    assert skill_template_idx(0x18) == 0    # 三藏神拳
    assert skill_template_idx(0x20) == 0    # 垂直斬
    assert skill_template_idx(0x21) == 83   # 赤雲波
    assert skill_template_idx(0x24) == 0    # 無限刀


def test_skill_template_idx_unknown():
    assert skill_template_idx(0xff) is None


# ---- 默认 tmpl 0 (普攻类): 前 1 + 单点 ----

def test_tmpl0_pattern_facing_up():
    u = _unit(facing=(0, -1), x=10, y=10)
    assert compute_skill_pattern(u, _map(), 0x14) == {(10, 9)}


def test_tmpl0_pattern_facing_right():
    u = _unit(facing=(1, 0), x=10, y=10)
    assert compute_skill_pattern(u, _map(), 0x14) == {(11, 10)}


def test_tmpl0_strike_single():
    u = _unit(facing=(1, 0), x=10, y=10)
    assert compute_skill_strike(u, (11, 10), 0x14) == {(11, 10)}


# ---- tmpl 22 (超亂舞): cursor = self, damage = 11x11 全屏 ----

def test_tmpl22_pattern_self_only():
    u = _unit(facing=(0, -1), x=10, y=10)
    assert compute_skill_pattern(u, _map(), 0x08) == {(10, 10)}


def test_tmpl22_strike_full_11x11_without_map():
    u = _unit(facing=(0, -1), x=10, y=10)
    hit = compute_skill_strike(u, (10, 10), 0x08)
    # 不传 map: 退化为 11x11 grid (121 格)
    assert len(hit) == 121
    assert (10, 10) in hit
    assert (5, 5) in hit
    assert (15, 15) in hit


def test_tmpl22_strike_fullscreen_covers_entire_map():
    """超亂舞 set2 p16 = 全 4 → 传 map 时应覆盖整张地图 (不受 11x11 grid 限制)."""
    u = _unit(facing=(0, -1), x=0, y=0)
    m = _map(15, 10)
    hit = compute_skill_strike(u, (0, 0), 0x08, m)
    # 整张 map 全格
    assert len(hit) == 15 * 10
    assert (0, 0) in hit
    assert (14, 9) in hit


# ---- tmpl 83 (赤雲波): cursor T-shape forward 4 格, damage 十字 5 格 ----

def test_tmpl83_pattern_facing_up():
    u = _unit(facing=(0, -1), x=10, y=10)
    # set1 p20: row 2 col 4/5/6 + row 3 col 5  (center row=5/col=5)
    # 偏移 (dx, dy): (-1,-3), (0,-3), (1,-3), (0,-2)
    expected = {(9, 7), (10, 7), (11, 7), (10, 8)}
    assert compute_skill_pattern(u, _map(), 0x21) == expected


def test_tmpl83_pattern_facing_right():
    u = _unit(facing=(1, 0), x=10, y=10)
    # 旋转 (-1,-3)→(3,-1),(0,-3)→(3,0),(1,-3)→(3,1),(0,-2)→(2,0)
    expected = {(13, 9), (13, 10), (13, 11), (12, 10)}
    assert compute_skill_pattern(u, _map(), 0x21) == expected


def test_tmpl83_strike_cross_5_facing_up():
    u = _unit(facing=(0, -1), x=10, y=10)
    # 落点 cursor=(10,9); set2 p2 = 十字 5 格中心 cursor
    hit = compute_skill_strike(u, (10, 9), 0x21)
    assert hit == {(10, 9), (10, 8), (10, 10), (9, 9), (11, 9)}


# ---- 边界 ----

def test_pattern_clipped_at_map_edge():
    u = _unit(facing=(0, -1), x=10, y=0)
    # forward 出界, 应为空 set
    assert compute_skill_pattern(u, _map(), 0x14) == set()


def test_strike_NOT_clipped_at_map_edge():
    """strike 是给 combat 用来枚举 tile→敌人, 越界 tile 在 tactics.damage_range
    里被 in_bounds 过滤. 这里 compute_skill_strike 本身不过滤 (跟 set1 pattern 一致的 dx/dy 输出)."""
    u = _unit(facing=(0, -1), x=10, y=0)
    hit = compute_skill_strike(u, (10, 0), 0x14)
    # 单点 = cursor 本身; cursor 在边界但 strike 不剔除 (剔除在 damage_range)
    assert hit == {(10, 0)}


# ---- 未知 skill_id 兜底 ----

def test_unknown_skill_returns_empty_pattern():
    u = _unit()
    assert compute_skill_pattern(u, _map(), 0xff) == set()


def test_unknown_skill_strike_falls_back_to_cursor():
    u = _unit()
    assert compute_skill_strike(u, (5, 5), 0xff) == {(5, 5)}
