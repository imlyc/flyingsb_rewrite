"""快速 smoke test: 跑垂直斬 UP seq 看事件流."""
from anim_engine import Engine, Entity, encode_op
from raw_attack_seqs import ATK_C  # any seq table works


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
    print(f"after attach: ticks={e.ticks} offset={e.offset} frame={e.frame_idx} flags={hex(e.flags)}")
    print(f"frames seen during attach: {frames_seen}")
    assert e.ticks == 3, "should block at first FM with ticks=3"
    assert e.frame_idx == 0

    # tick 3 frames — ticks counts down 3,2,1, then 0 → run next op (FM frame=1 + WAIT 2)
    for i in range(5):
        eng.tick()
        print(f"after tick {i+1}: ticks={e.ticks} offset={e.offset} frame={e.frame_idx} flags={hex(e.flags)}")
    print(f"all frames: {frames_seen}")


def test_signal_routing():
    """验证 op 0x0e SIGNAL 路由给 active_action."""
    eng = Engine()
    log = []

    def my_wrapper(action, engine):
        log.append(('wrapper', action.state_code, action.signal_target.id if action.signal_target else None))
        # 模拟 DOIT_melee: state -100 = IMPACT, do something
        if action.state_code == -100:
            action.user_data['hit_count'] = action.user_data.get('hit_count', 0) + 1

    action = eng.spawn(think_fn=my_wrapper)
    eng.active_action = action
    print(f"action created, init log: {log}")

    unit = eng.spawn()
    seq = (
        encode_op(0x04, 5, 0, 0)      # FM (non-blocking) — set frame
        + encode_op(0x0e, -100)        # SIGNAL IMPACT
        + encode_op(0x04, 5, 1, 5)    # FM ticks=5 — block
        + encode_op(0x0e, -110)        # SIGNAL END
        + encode_op(0x00)
    )
    eng.attach_seq(unit, seq)
    print(f"after attach: log={log}")
    print(f"action.user_data: {action.user_data}")
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
    print(f"after attach unknown-op seq: ticks={e.ticks} frame={e.frame_idx}")
    assert e.frame_idx == 7, "should have skipped unknown op and run FM"


def test_legacy_atk_c():
    """跑实际游戏数据 ATK_C UP (美娜普攻 6 帧/dir)."""
    from anim_engine import tuple_to_bytecode
    from raw_attack_seqs import ATK_C
    eng = Engine()

    # 假装挂个 wrapper 接信号
    sigs = []
    def wrapper(action, e):
        sigs.append((action.state_code, action.signal_target.id if action.signal_target else None))
    action = eng.spawn(think_fn=wrapper)
    eng.active_action = action

    unit = eng.spawn()
    seq_bc = tuple_to_bytecode(ATK_C[0])  # UP
    print(f"ATK_C[UP] tuple len = {len(ATK_C[0])}, bytecode len = {len(seq_bc)} bytes")

    events = []
    eng.on('frame_change', lambda e, slot, fr: events.append(('frame', slot & 0xffff, fr)))
    eng.on('sound_play', lambda e, sid: events.append(('sound', sid)))

    eng.attach_seq(unit, seq_bc)
    print(f"after attach: ticks={unit.ticks} offset={unit.offset} flags={hex(unit.flags)}")
    print(f"first events: {events[:5]}")
    print(f"signals seen during attach: {sigs[1:]}  (excluding init -1)")

    # 推帧到结束
    max_ticks = 500
    while unit.is_playing() and max_ticks > 0:
        eng.tick()
        max_ticks -= 1
    print(f"sequence finished after {500 - max_ticks} ticks, total events={len(events)}, signals={len(sigs)-1}")


if __name__ == '__main__':
    print("=== test_basic_ops ===")
    test_basic_ops()
    print("\n=== test_signal_routing ===")
    test_signal_routing()
    print("\n=== test_unknown_op_skipped ===")
    test_unknown_op_skipped()
    print("\n=== test_legacy_atk_c ===")
    test_legacy_atk_c()
    print("\nall green ✓")
