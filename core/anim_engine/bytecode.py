"""Convenience: 把 raw_attack_seqs.py 的 tuple seq 转成 bytecode."""

from __future__ import annotations
import struct
from typing import Optional

from core.anim_engine.entity import SIG_END, SIG_IMPACT


def tuple_to_bytecode(tuple_seq: list) -> bytes:
    """
    把现有的 raw_attack_seqs.py 的 tuple seq 转成 bytecode.
    支持 op tuple:
      ('fm', slot, frame, ticks)         → op 0x04
      ('idle', slot, frame, ticks)       → op 0x06
      ('move', dx, dy, ticks)            → op 0x0b (dz=0)
      ('move', dx, dy, dz, ticks)        → op 0x0b
      ('sound', id, op_hex)              → 0x11 (0x0411) / 0x12 (0x0413 实际是 SET_SWING_SOUND? 见下)
      ('impact',)                         → op 0x0e SIGNAL -100
      ('impact', sig)                     → op 0x0e SIGNAL <sig> (-250 等)
      ('jump', sig)                       → op 0x0e SIGNAL <sig>
      ('end',)                            → op 0x0e SIGNAL -110
      ('raw', op_hex, a, b, c, d)        → 原样 10B (未解码 op, 用 op_hex 低字节 + size 0x0a)
    """
    # op_hex 0x0411 → 字节码 op 0x11 (PLAY); 0x0413 → op 0x13 (SET_SWING_SOUND)
    SOUND_HEX_TO_OP = {0x0411: 0x11, 0x0413: 0x13}

    out = bytearray()
    for t in tuple_seq:
        kind = t[0]
        if kind == 'fm':
            _, slot, frame, ticks = t
            out += encode_op(0x04, slot, frame, ticks)
        elif kind == 'idle':
            _, slot, frame, ticks = t
            out += encode_op(0x06, slot, frame, ticks)
        elif kind == 'move':
            if len(t) == 4:
                _, dx, dy, ticks = t
                dz = 0
            else:
                _, dx, dy, dz, ticks = t
            out += encode_op(0x0b, dx, dy, dz, ticks)
        elif kind == 'sound':
            _, sid, op_hex = t
            out += encode_op(SOUND_HEX_TO_OP.get(op_hex, 0x11), sid)
        elif kind == 'impact':
            sig = t[1] if len(t) > 1 else SIG_IMPACT
            out += encode_op(0x0e, sig)
        elif kind == 'jump':
            out += encode_op(0x0e, t[1])
        elif kind == 'end':
            out += encode_op(0x0e, SIG_END)
        elif kind == 'exit':
            # 实测 EXIT op 是 2B (`00 02`), 不是 ANIM_ENGINE_SPEC 早期写的 4B
            out += bytes([0x00, 0x02])
        elif kind == 'raw':
            # 10B raw op: [op_low, 0x0a, a, b, c, d] (4 × i16)
            _, op_hex, a, b, c, d = t
            out += bytes([op_hex & 0xff, 0x0a]) + struct.pack('<hhhh', a, b, c, d)
        else:
            raise ValueError(f"unknown tuple op: {t!r}")
    return bytes(out)


def encode_op(op_id: int, *fields, size: Optional[int] = None) -> bytes:
    """
    编码一个 op. 简化版, fields 按 op spec 的字节顺序传:

      encode_op(0x04, slot, frame, ticks)            # FM
      encode_op(0x0b, dx, dy, dz, ticks)             # MOVE
      encode_op(0x0e, signal_id)                     # SIGNAL
      encode_op(0x00)                                # EXIT (size 4, no payload)

    size 留 None 用 op_id 默认 size; 否则覆盖.
    """
    DEFAULT_SIZE = {
        0x00: 2,                        # EXIT (实测 2B)
        0x01: 4, 0x02: 4, 0x03: 4,
        0x04: 10, 0x05: 10, 0x06: 10,
        0x07: 8, 0x08: 4, 0x09: 4, 0x0a: 4,
        0x0b: 10, 0x0c: 10,
        0x0d: 4, 0x0e: 4,
        0x0f: 6, 0x10: 6,
        0x11: 4, 0x12: 4, 0x13: 4,
    }
    sz = size if size is not None else DEFAULT_SIZE[op_id]
    header = bytes([op_id, sz])
    payload = b''
    if op_id in (0x04, 0x05, 0x06):     # slot:u16, frame:u32, ticks:u16
        slot, frame, ticks = fields
        payload = struct.pack('<HIH', slot, frame, ticks)
    elif op_id == 0x07:                  # frame:u32, ticks:u16
        payload = struct.pack('<IH', *fields)
    elif op_id == 0x08:                  # ticks:u16
        payload = struct.pack('<H', *fields)
    elif op_id in (0x0b, 0x0c):          # dx,dy,dz:i16, ticks:u16
        payload = struct.pack('<hhhH', *fields)
    elif op_id == 0x0e:                  # signal:i16
        payload = struct.pack('<h', *fields) + b'\x00\x00'  # pad to size 4
        return header + payload[:sz - 2]
    elif op_id in (0x0f, 0x10):          # flags:u32
        payload = struct.pack('<I', *fields)
    elif op_id in (0x11, 0x12, 0x13):    # id:u16
        payload = struct.pack('<H', *fields) + b'\x00' * 0
    # fill / truncate to size
    payload = (payload + b'\x00' * sz)[:sz - 2]
    return header + payload
