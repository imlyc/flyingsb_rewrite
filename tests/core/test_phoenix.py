"""三藏 凤凰掌 0x17 投射物 (2026-10-22 实录校准): 原地长大 (seq 帧 0-4) → 弹簧飞向 target → 越过后匀速飞出屏外
→ 之后每 4 tick 一个 efock01 共 8 个 → 全播完 SIG_IMPACT_2 结算.
"""

import random

from core.anim_engine.engine import Engine
from core.projectile import (
    EFOCK01_ATLAS,
    PHOENIX_BURST_COUNT,
    _PHOENIX_FLY,
    _PHOENIX_GROW,
    spawn_phoenix_effect,
)

PHOENIX_GROW_FRAMES = 5     # 长大 seq 0x67312c 帧 0-4


class _Q:
    def occupant(self, x, y):
        return None


class _Battle:
    def __init__(self):
        self.rng = random.Random(0)
        self.engine = Engine()
        self.q = _Q()
        self.float_pending = 0
        self.damage_events = []


class _Caster:
    def __init__(self, x, y, facing):
        self.x, self.y, self.facing = x, y, facing
        self.entity = None
        self.is_player = True
        self.pending_skill_id = 0x17
        self.cast_hold = True
        self.suppress_hit_fx = False
        self.suppress_hit_reaction = False


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
        if not phoenix_destroyed and e.state_code == _PHOENIX_GROW:
            grow_frames.add(e.frame_idx)
        b.engine.tick()
        if (e.flags & 0x800) == 0 or e.user_data.get('target_x') is None:   # 销毁 (槽位可能被火/协调实体复用)
            phoenix_destroyed = True
        if not phoenix_destroyed and e.state_code == _PHOENIX_GROW and (e.x != spawn_x or e.y != spawn_y):
            moved_during_grow = True
        for x in b.engine.entities:
            if x.atlas_slot == EFOCK01_ATLAS and x.user_data.get('ember'):
                burst_ids.add(id(x))
        if phoenix_destroyed and len(burst_ids) >= PHOENIX_BURST_COUNT:
            break

    # 1) 原地由小变大: 长大期零位移, 播帧 0-4
    assert not moved_during_grow, "凤凰长大期不应位移"
    assert grow_frames == set(range(PHOENIX_GROW_FRAMES)), grow_frames
    # 2) 起飞后确实飞出去了 (飞出屏外销毁)
    # 3) 命中后连爆 8 个 efock01
    assert len(burst_ids) == PHOENIX_BURST_COUNT, f"应爆 {PHOENIX_BURST_COUNT} 个, got {len(burst_ids)}"
    # 4) 凤凰飞出屏外销毁 (火在它之后放)
    assert phoenix_destroyed, "凤凰飞出屏外应销毁"


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
