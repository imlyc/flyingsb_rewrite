"""DirectionalHold: tap-vs-hold 区分逻辑.

注: "tap 仅转向, 不走" 语义其实在调用方 (朝向不对时早 return), 不在 should_walk.
should_walk 的实际语义: 边沿 / 已在连走 / 持续按住够久 任一条件成立 → 走一步.
"""

from core.movement_input import DirectionalHold


def test_edge_triggers_walk_immediately():
    """边沿就 walk (tap-and-go, 调用方靠 facing 判断挡住)."""
    h = DirectionalHold()
    edge = h.tick((1, 0), dt_ms=1)
    assert edge is True
    assert h.should_walk(edge, hold_delay_ms=80)


def test_after_edge_continues_walking_without_delay():
    """边沿一次后 walking=True; 后续帧即使未到 hold_delay 也继续走."""
    h = DirectionalHold()
    h.tick((1, 0), dt_ms=1)
    h.should_walk(True, hold_delay_ms=80)        # 触发 walking=True
    # 下一帧: 不是边沿, dt 很小, 但应继续走 (连续按住)
    edge2 = h.tick((1, 0), dt_ms=1)
    assert not edge2
    assert h.should_walk(edge2, hold_delay_ms=80)


def test_hold_without_initial_walk_eventually_triggers():
    """如果首帧不触发 should_walk (e.g. 朝向不对), 持续按住超阈值后也能走."""
    h = DirectionalHold()
    h.tick((1, 0), dt_ms=1)        # 边沿
    h.tick((1, 0), dt_ms=50)        # 累积 50ms, 还没超 80
    edge = h.tick((1, 0), dt_ms=50) # 累积 101ms 已超 80
    assert not edge
    assert h.should_walk(edge, hold_delay_ms=80)


def test_direction_change_resets_walking_and_clock():
    """换方向 → 新边沿, walking 清零, held_ms 归零."""
    h = DirectionalHold()
    h.tick((1, 0), dt_ms=200)
    h.should_walk(False, hold_delay_ms=80)   # 进 walking 状态
    edge = h.tick((0, 1), dt_ms=1)            # 换方向
    assert edge is True
    assert h.held_ms == 0
    assert h.walking is False                 # 新方向需要重新触发


def test_release_resets():
    h = DirectionalHold()
    h.tick((1, 0), dt_ms=200)
    h.reset()
    assert h.held_dir == (0, 0)
    assert h.held_ms == 0
    assert h.walking is False
    edge = h.tick((1, 0), dt_ms=1)
    assert edge is True
