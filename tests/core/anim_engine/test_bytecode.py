"""encode_op / tuple_to_bytecode 编码 + 解码 roundtrip."""

import struct

from core.anim_engine.bytecode import encode_op, tuple_to_bytecode
from core.anim_engine.entity import SIG_END, SIG_IMPACT


def _u16(b, off): return struct.unpack_from('<H', b, off)[0]
def _i16(b, off): return struct.unpack_from('<h', b, off)[0]
def _u32(b, off): return struct.unpack_from('<I', b, off)[0]


def test_encode_fm():
    """FM op: [0x04, 10, slot:u16, frame:u32, ticks:u16]."""
    out = encode_op(0x04, 5, 7, 3)
    assert out[0] == 0x04
    assert out[1] == 10
    assert _u16(out, 2) == 5      # slot
    assert _u32(out, 4) == 7      # frame
    assert _u16(out, 8) == 3      # ticks


def test_encode_move():
    """MOVE: dx,dy,dz signed i16 + ticks u16."""
    out = encode_op(0x0b, -16, 8, 0, 5)
    assert out[0] == 0x0b
    assert out[1] == 10
    assert _i16(out, 2) == -16
    assert _i16(out, 4) == 8
    assert _i16(out, 6) == 0
    assert _u16(out, 8) == 5


def test_encode_signal():
    """SIGNAL: [0x0e, 4, sig:i16]. 负数信号常见 (-100 / -110)."""
    out = encode_op(0x0e, SIG_IMPACT)
    assert out[0] == 0x0e
    assert out[1] == 4
    assert _i16(out, 2) == -100


def test_encode_exit():
    """EXIT 实测 size=2 (字节流 `00 02`), 不是早期 spec 写的 4."""
    out = encode_op(0x00)
    assert out == bytes([0x00, 2])


def test_tuple_to_bytecode_mixed():
    """tuple seq → 字节码, 验证总长 + 几个关键 op."""
    seq = [
        ('fm', 5, 7, 3),
        ('move', -16, 0, 5),
        ('impact',),
        ('end',),
    ]
    bc = tuple_to_bytecode(seq)
    # 长度: FM 10 + MOVE 10 + SIGNAL 4 + SIGNAL 4 = 28
    assert len(bc) == 28
    assert bc[0] == 0x04      # fm
    assert bc[10] == 0x0b     # move
    assert bc[20] == 0x0e     # signal
    assert _i16(bc, 22) == SIG_IMPACT
    assert _i16(bc, 26) == SIG_END


def test_tuple_to_bytecode_idle_and_sound():
    """idle 用 op 0x06; sound (0x0411) 路由到 op 0x11."""
    seq = [
        ('idle', 3, 1, 2),
        ('sound', 42, 0x0411),
    ]
    bc = tuple_to_bytecode(seq)
    assert bc[0] == 0x06
    assert bc[10] == 0x11
    assert _u16(bc, 12) == 42


def test_tuple_to_bytecode_move_3vs4_args():
    """move 支持 3D (dx,dy,dz,ticks) 和 2D (dx,dy,ticks, dz=0)."""
    bc3 = tuple_to_bytecode([('move', 1, 2, 5)])         # dz auto = 0
    bc4 = tuple_to_bytecode([('move', 1, 2, 0, 5)])
    assert bc3 == bc4


def test_unknown_tuple_raises():
    """unknown tuple → ValueError."""
    import pytest
    with pytest.raises(ValueError):
        tuple_to_bytecode([('what', 1, 2)])
