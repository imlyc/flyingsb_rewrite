"""快速 smoke test: 跑垂直斬 UP seq 看事件流.

原 core/test_anim_engine.py 搬过来, 改用 core.* 全路径 import.
"""

from core.anim_engine.engine import Engine
from core.anim_engine.bytecode import encode_op


def test_basic_ops():
    """编几个 op 跑一下, 验证 advancer 行为."""
    eng = Engine()
    e = eng.spawn()

    # seq: FM(slot=5, frame=0, ticks=3) + FM(slot=5, frame=1, ticks=0) + WAIT(2) + EXIT
    seq = (
        encode_op(0x04, 5, 0, 3)      # FM ticks=3 → blocking
        + encode_op(0x04, 5, 1, 0)    # FM ticks=0 → non-blocking
        + encode_op(0x08, 2)          # WAIT ticks=2 → blocking
        + encode_op(0x00)             # EXIT
    )

    frames_seen = []
    eng.on('frame_change', lambda ent, slot, fr: frames_seen.append((ent.ticks, slot & 0xffff, fr)))

    eng.attach_seq(e, seq)
    assert e.ticks == 3, "should block at first FM with ticks=3"
    assert e.frame_idx == 0

    # tick 几帧让 seq 推进
    for _ in range(5):
        eng.tick()


def test_signal_routing():
    """验证 op 0x0e SIGNAL 路由给 active_action."""
    eng = Engine()

    def my_wrapper(action, engine):
        # 模拟 DOIT_melee: state -100 = IMPACT, do something
        if action.state_code == -100:
            action.user_data['hit_count'] = action.user_data.get('hit_count', 0) + 1

    action = eng.spawn(think_fn=my_wrapper)
    eng.active_action = action

    unit = eng.spawn()
    seq = (
        encode_op(0x04, 5, 0, 0)      # FM (non-blocking) — set frame
        + encode_op(0x0e, -100)        # SIGNAL IMPACT
        + encode_op(0x04, 5, 1, 5)    # FM ticks=5 — block
        + encode_op(0x0e, -110)        # SIGNAL END
        + encode_op(0x00)
    )
    eng.attach_seq(unit, seq)
    assert action.user_data.get('hit_count') == 1


def test_unknown_op_skipped():
    """未知 op 应该按 size byte 跳过, 不崩溃."""
    eng = Engine()
    e = eng.spawn()
    seq = (
        bytes([0x99, 4, 0x00, 0x00])   # 未知 op, size 4
        + encode_op(0x04, 5, 7, 2)     # 应该跑到这里
        + encode_op(0x00)
    )
    eng.attach_seq(e, seq)
    assert e.frame_idx == 7, "should have skipped unknown op and run FM"


def test_legacy_atk_c():
    """跑实际游戏数据 ATK_C UP (美娜普攻 6 帧/dir)."""
    from core.anim_engine.bytecode import tuple_to_bytecode
    from core.raw_attack_seqs import ATK_C
    eng = Engine()

    sigs = []
    def wrapper(action, e):
        sigs.append((action.state_code, action.signal_target.id if action.signal_target else None))
    action = eng.spawn(think_fn=wrapper)
    eng.active_action = action

    unit = eng.spawn()
    seq_bc = tuple_to_bytecode(ATK_C[0])  # UP

    events = []
    eng.on('frame_change', lambda e, slot, fr: events.append(('frame', slot & 0xffff, fr)))
    eng.on('sound_play', lambda e, sid: events.append(('sound', sid)))

    eng.attach_seq(unit, seq_bc)

    # 推帧到结束 (有上限防 seq 写错卡死)
    max_ticks = 500
    while unit.is_playing() and max_ticks > 0:
        eng.tick()
        max_ticks -= 1
    assert max_ticks > 0, "ATK_C UP seq took too many ticks (suspicious infinite loop)"
    assert len(events) > 0, "ATK_C UP should emit frame_change events"
