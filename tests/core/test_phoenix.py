"""三藏 凤凰掌 0x17 投射物: 原地由小变大 → 飞向 target → 敌人周围连爆 8 个 efock01.

严格还原 exe (caster dispatcher FUN_004febad + phoenix think FUN_004fe717):
  - state 0 不调物理, 只播 grow seq (帧 0-4) → 凤凰在 caster 原地长大, 无位移.
  - 抵达 target 后每 4 tick spawn 1 个 efock01 爆炸, 共 8 个, 爆完发 SIG_IMPACT_2 结算.
"""

import random

from core.anim_engine.engine import Engine
from core.projectile import (
    EFOCK01_ATLAS,
    PHOENIX_BURST_COUNT,
    PHOENIX_GROW_FRAMES,
    _PHOENIX_FLY,
    _PHOENIX_GROW,
    spawn_phoenix_effect,
)


class _Battle:
    def __init__(self):
        self.rng = random.Random(0)
        self.engine = Engine()


class _Caster:
    def __init__(self, x, y, facing):
        self.x, self.y, self.facing = x, y, facing


def test_phoenix_grows_in_place_then_flies_then_explodes():
    b = _Battle()
    caster = _Caster(2, 5, (1, 0))      # facing RT
    e = spawn_phoenix_effect(b, caster, (8, 5))
    assert e.state_code == _PHOENIX_GROW

    spawn_x, spawn_y = e.x, e.y
    grow_frames = set()
    moved_during_grow = False
    burst_ids = set()
    phoenix_destroyed = False

    for _ in range(400):
        if e.state_code == _PHOENIX_GROW:
            grow_frames.add(e.frame_idx)
        b.engine.tick()
        if e.state_code == _PHOENIX_GROW and (e.x != spawn_x or e.y != spawn_y):
            moved_during_grow = True
        for x in b.engine.entities:
            if x is not e and x.atlas_slot == EFOCK01_ATLAS:
                burst_ids.add(id(x))
        if (e.flags & 0x800) == 0 or e not in b.engine.entities:
            phoenix_destroyed = True
            break

    # 1) 原地由小变大: 长大期零位移, 播帧 0-4
    assert not moved_during_grow, "凤凰长大期不应位移"
    assert grow_frames == set(range(PHOENIX_GROW_FRAMES)), grow_frames
    # 2) 起飞后确实飞出去了 (位移)
    assert e.state_code != _PHOENIX_GROW
    # 3) 命中后连爆 8 个 efock01
    assert len(burst_ids) == PHOENIX_BURST_COUNT, f"应爆 {PHOENIX_BURST_COUNT} 个, got {len(burst_ids)}"
    # 4) 爆完凤凰销毁
    assert phoenix_destroyed, "8 爆后凤凰应销毁"


def test_phoenix_flies_toward_target_after_grow():
    """长大完成进 FLY 后, 凤凰朝 target 方向位移 (facing RT → x 增大)."""
    b = _Battle()
    caster = _Caster(2, 5, (1, 0))
    e = spawn_phoenix_effect(b, caster, (8, 5))
    # tick 到进入 FLY
    last_x = e.x
    saw_fly_move = False
    for _ in range(60):
        b.engine.tick()
        if e.state_code == _PHOENIX_FLY:
            if e.x > last_x:
                saw_fly_move = True
            last_x = e.x
    assert saw_fly_move, "FLY 阶段应朝 target (RT) 位移"
