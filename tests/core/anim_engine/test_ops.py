"""单独验证关键 op handler 的副作用. 跟 test_bytecode 互补:
   bytecode 测编码格式, ops 测解释行为."""

from core.anim_engine.bytecode import encode_op
from core.anim_engine.engine import Engine
from core.anim_engine.entity import Entity


def _run(seq: bytes) -> tuple[Engine, Entity]:
    eng = Engine()
    e = eng.spawn()
    eng.attach_seq(e, seq)
    return eng, e


# ---- op 0x00 EXIT ----

def test_exit_clears_playing_flag():
    """EXIT: 清 seq, 清 playing flag, 不再接受 tick."""
    eng, e = _run(encode_op(0x00))
    assert not e.is_playing()
    assert e.seq == b''


# ---- op 0x04 FM ----

def test_fm_sets_atlas_slot_and_frame():
    """FM mode 0: atlas_slot 高 16 位 = 0."""
    eng, e = _run(encode_op(0x04, 5, 7, 3) + encode_op(0x00))
    assert e.atlas_slot == 5            # 高 16 位 = 0 (mode 0)
    assert e.frame_idx == 7
    assert e.ticks == 3                  # blocking


def test_fm_mode2_sets_high_bit():
    """FM mode 2 (op 0x06) 在 atlas_slot 上 OR 0x20000."""
    eng, e = _run(encode_op(0x06, 5, 7, 0) + encode_op(0x00))
    assert e.atlas_slot == 5 | 0x20000


# ---- op 0x07 SET_FRAME ----

def test_set_frame_only_changes_frame_keeps_atlas():
    """先用 FM 设 atlas, 再 SET_FRAME 只动 frame_idx."""
    eng, e = _run(
        encode_op(0x04, 5, 7, 0) +       # FM atlas=5 frame=7
        encode_op(0x07, 99, 0) +         # SET_FRAME frame=99 ticks=0
        encode_op(0x00)
    )
    assert e.atlas_slot == 5             # atlas 没动
    assert e.frame_idx == 99


# ---- op 0x08 WAIT ----

def test_wait_blocks():
    """WAIT ticks=5 → e.ticks=5 + 停在此 op."""
    eng, e = _run(encode_op(0x08, 5) + encode_op(0x00))
    assert e.ticks == 5
    assert e.is_playing()


def test_wait_counts_down_per_tick():
    """每 eng.tick() 让 ticks -= 1."""
    eng, e = _run(encode_op(0x08, 3) + encode_op(0x00))
    assert e.ticks == 3
    eng.tick(); assert e.ticks == 2
    eng.tick(); assert e.ticks == 1
    eng.tick(); assert e.ticks == 0      # 第 3 tick 减到 0, 但还没跑下一 op
    eng.tick()                            # 第 4 tick 才 dispatch EXIT
    assert not e.is_playing()


# ---- op 0x0b MOVE ----

def test_move_writes_16_16_fixed_point():
    """MOVE dx=5 → e.x += 5 << 16 = 5.0 in 16.16 fixed."""
    eng, e = _run(encode_op(0x0b, 5, -3, 0, 2) + encode_op(0x00))
    assert e.x == 5 << 16
    assert e.y == -3 << 16
    assert e.z == 0
    assert e.ticks == 2


def test_move_emits_event_with_dx_dy_ticks():
    """订阅 'move' 事件能拿到原始 dx/dy/dz/ticks (不是 16.16)."""
    eng = Engine()
    e = eng.spawn()
    captured = []
    eng.on('move', lambda ent, dx, dy, dz, t: captured.append((dx, dy, dz, t)))
    eng.attach_seq(e, encode_op(0x0b, 8, -4, 0, 5) + encode_op(0x00))
    assert captured == [(8, -4, 0, 5)]


# ---- op 0x0e SIGNAL ----

def test_signal_emits_event_and_routes_to_action():
    """SIGNAL 双路径: 'signal' 事件 + 写 active_action.state_code."""
    eng = Engine()
    captured_signals = []
    eng.on('signal', lambda ent, sig: captured_signals.append(sig))

    routed = []
    def wrapper(action, engine):
        if action.state_code == -100:    # only IMPACT
            routed.append(action.state_code)

    action = eng.spawn(think_fn=wrapper)
    eng.active_action = action

    unit = eng.spawn()
    eng.attach_seq(unit, encode_op(0x0e, -100) + encode_op(0x00))
    assert -100 in captured_signals
    assert routed == [-100]


def test_signal_with_no_active_action_only_emits_event():
    """没 active_action 也不崩, 但 wrapper 不调."""
    eng = Engine()
    captured = []
    eng.on('signal', lambda ent, sig: captured.append(sig))
    e = eng.spawn()
    eng.attach_seq(e, encode_op(0x0e, -110) + encode_op(0x00))
    assert captured == [-110]


# ---- op 0x0f / 0x10 flags ----

def test_or_flags_and_and_not_flags():
    """OR 设 bit, AND_NOT 清 bit."""
    eng = Engine()
    e = eng.spawn()
    eng.attach_seq(e,
        encode_op(0x0f, 0x40000) +       # OR 0x40000
        encode_op(0x10, 0x40000) +       # AND_NOT 0x40000
        encode_op(0x00)
    )
    # spawn 默认 flags=0x800; attach_seq 加 0x20040; 然后 OR/AND_NOT 0x40000 抵消 + EXIT 清 0x20000
    assert e.flags & 0x40000 == 0


# ---- 路径融合 ----

def test_blocking_op_breaks_dispatch_loop():
    """attach_seq 应跑到第一个阻塞 op 就停, 不一路跑到 EXIT."""
    eng = Engine()
    e = eng.spawn()
    eng.attach_seq(e,
        encode_op(0x04, 1, 0, 0) +        # FM ticks=0 (non-blocking)
        encode_op(0x04, 2, 0, 0) +        # FM ticks=0 (non-blocking)
        encode_op(0x08, 10) +             # WAIT ticks=10 (blocks here)
        encode_op(0x04, 99, 0, 0) +       # 这条不该被跑到
        encode_op(0x00)
    )
    # FM op 跑到第 3 个 (atlas_slot=2 是第二个 FM 设的)
    assert e.atlas_slot == 2
    assert e.ticks == 10
    assert e.frame_idx == 0    # 第 4 个 FM (atlas=99) 没跑, frame 还是上一个 FM 的 0
