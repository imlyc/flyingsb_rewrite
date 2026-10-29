"""战斗走格 = 原版运动状态机 + 姿态函数 FUN_004c2492 (core.battle.locomotion).
期望序列取自原版实录 (wine/captures/*: 232 段走格, 每 tick 一行实体表)."""

from core.battle.data import BattleUnit
from core.battle.locomotion import IDLE, WALK, Locomotion, pose
from scenes.battle.update import LOCO_TICK_MS, _tick_unit_positions


class _Scene:
    def __init__(self, units):
        self.battle = type("B", (), {"all_units": units})()


def _unit(player=True, type_flags=0):
    u = BattleUnit(name="捕山" if player else "e", level=1, max_hp=20, hp=20, max_mp=0, mp=0, sg=0,
                   attack=0, defence=0, agile=0, move=0, is_player=player, type_flags=type_flags)
    u.x, u.y = 5, 5
    u.snap_render()
    return u


def _walk(u, path, ticks):
    """沿 path 走, 每 tick 记 (走路列 or 'I', render_x, render_y)."""
    sc = _Scene([u])
    u.move_path = list(path)
    u.x, u.y = path[-1]
    out = []
    for _ in range(ticks):
        _tick_unit_positions(sc, LOCO_TICK_MS)
        atlas, col, _row = u.loco_pose
        out.append((col if atlas == WALK else "I", u.render_x, u.render_y))
    return out


def test_one_tile_four_ticks_quarter_steps():
    u = _unit()
    u.facing = (0, -1)
    seq = _walk(u, [(5, 4)], 5)
    assert [s[2] for s in seq] == [4.75, 4.5, 4.25, 4.0, 4.0]
    assert [s[0] for s in seq][:4] == [1, 2, 1, 0]      # phase 0 起步; 第 4 tick = 到格 (状态 0 计数 1) 走路图第 0 列
    assert seq[4][0] == "I"                              # 之后进待机图


def test_continuous_walk_alternates_feet_across_moves():
    u = _unit()
    u.facing = (1, 0)
    a = _walk(u, [(6, 5), (7, 5)], 8)
    b = _walk(u, [(8, 5)], 4)                            # 另一次移动: phase 接着翻
    cols = "".join(str(s[0]) for s in a + b)
    assert cols == "121034301210"                        # 实录 en127 / en12 同型


def test_variant_tables_from_recordings():
    for flags, want in ((0x40, "11201100"), (0x14000080, "12302100")):    # 敌人表 flags & 0xc0: CBL 变体 1 / 河皮 变体 2
        u = _unit(player=False, type_flags=flags)
        u.facing = (0, -1)
        seq = _walk(u, [(5, 4), (5, 3)], 8)
        assert "".join(str(s[0]) for s in seq) == want


def test_idle_breathing_period_and_weak_only_players():
    lo = Locomotion(counter=1)
    frames = [pose(lo, (1, 0), period=8) for _ in range(16)]
    assert frames[0] == (IDLE, 3, 0) and frames[6] == (IDLE, 3, 1)     # 计数 2..7 → 第 0 行, 8.. → 第 1 行
    assert pose(Locomotion(counter=5), (0, 1), player=False, weak=True)[0] == IDLE   # 敌人不进虚弱图
    assert pose(Locomotion(counter=5), (0, 1), player=True, weak=True)[0] == "weak"
    assert pose(Locomotion(counter=5), (0, 1), frozen=True) == (WALK, 0, 1)        # 睡眠/痲痺定格
