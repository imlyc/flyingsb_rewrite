"""20 个 op handler (0x00-0x13) + 注册装饰器 + struct helpers.

每个 handler 自己 advance offset. 阻塞类 (有 ticks 的) 设 eng._break=True 让
advancer 停下等待下一帧.
"""

from __future__ import annotations
import struct
from typing import Callable, Optional, TYPE_CHECKING

from core.anim_engine.entity import Entity

if TYPE_CHECKING:
    from core.anim_engine.engine import Engine


# ============ Op handler 注册 ============

DISPATCH: list[Optional[Callable[['Engine', Entity], None]]] = [None] * 0x14


def op(op_id: int):
    """装饰器: 注册 op handler."""
    def deco(fn):
        DISPATCH[op_id] = fn
        return fn
    return deco


def _u16(seq: bytes, off: int) -> int: return struct.unpack_from('<H', seq, off)[0]
def _i16(seq: bytes, off: int) -> int: return struct.unpack_from('<h', seq, off)[0]
def _u32(seq: bytes, off: int) -> int: return struct.unpack_from('<I', seq, off)[0]


# ============ 20 个 op handlers ============

@op(0x00)
def op_exit(eng: 'Engine', e: Entity):
    """EXIT: clear seq + ticks + offset, drop playing flag, force break."""
    e.flags &= ~0x20000
    e.seq = b''
    e.ticks = 0
    e.offset = 0
    eng._break = True

@op(0x01)
def op_reset_offset(eng, e):
    """RESET_OFFSET: loop back to start of seq."""
    e.offset = 0

@op(0x02)
def op_save_render(eng, e):
    """SAVE_RENDER: backup atlas + frame state."""
    e.save_atlas_base, e.save_atlas_slot, e.save_frame_idx = e.atlas_base, e.atlas_slot, e.frame_idx
    e.offset += e.seq[e.offset + 1]

@op(0x03)
def op_restore_render(eng, e):
    """RESTORE_RENDER."""
    e.atlas_base, e.atlas_slot, e.frame_idx = e.save_atlas_base, e.save_atlas_slot, e.save_frame_idx
    e.offset += e.seq[e.offset + 1]

@op(0x04)
def op_fm(eng, e):
    """FM (mode 0): atlas_slot:u16, frame_idx:u32, ticks:u16. size=10."""
    base = e.offset
    e.atlas_slot = _u16(e.seq, base + 2)         # mode 0 (high 16 = 0)
    e.frame_idx  = _u32(e.seq, base + 4)
    e.ticks      = _u16(e.seq, base + 8)
    if e.ticks: eng._break = True
    e.offset += e.seq[base + 1]

@op(0x05)
def op_fm_mode1(eng, e):
    """FM mode 1: atlas_slot | 0x10000."""
    base = e.offset
    e.atlas_slot = _u16(e.seq, base + 2) | 0x10000
    e.frame_idx  = _u32(e.seq, base + 4)
    e.ticks      = _u16(e.seq, base + 8)
    if e.ticks: eng._break = True
    e.offset += e.seq[base + 1]

@op(0x06)
def op_fm_mode2(eng, e):
    """FM mode 2 / IDLE: atlas_slot | 0x20000. (战斗主用)"""
    base = e.offset
    e.atlas_slot = _u16(e.seq, base + 2) | 0x20000
    e.frame_idx  = _u32(e.seq, base + 4)
    e.ticks      = _u16(e.seq, base + 8)
    if e.ticks: eng._break = True
    e.offset += e.seq[base + 1]

@op(0x07)
def op_set_frame(eng, e):
    """SET_FRAME: 只改 frame_idx, 保 atlas. payload: frame:u32, ticks:u16. size=8."""
    base = e.offset
    e.frame_idx = _u32(e.seq, base + 2)
    e.ticks     = _u16(e.seq, base + 6)
    if e.ticks: eng._break = True
    e.offset += e.seq[base + 1]

@op(0x08)
def op_wait(eng, e):
    """WAIT: ticks:u16. size=4."""
    base = e.offset
    e.ticks = _u16(e.seq, base + 2)
    if e.ticks: eng._break = True
    e.offset += e.seq[base + 1]

@op(0x09)
def op_save_pos(eng, e):
    """SAVE_POS: memcpy unit+0x8 → +0x3c, 0x24=36 bytes (= x/y/z/target_x/y/z + 朝向 等)."""
    e.pos_buf = struct.pack('<6i', e.x, e.y, e.z, e.target_x, e.target_y, e.target_z) + b'\x00' * 12
    e.offset += e.seq[e.offset + 1]

@op(0x0a)
def op_restore_pos(eng, e):
    """RESTORE_POS."""
    if len(e.pos_buf) >= 24:
        vals = struct.unpack_from('<6i', e.pos_buf, 0)
        e.x, e.y, e.z, e.target_x, e.target_y, e.target_z = vals
    e.offset += e.seq[e.offset + 1]

@op(0x0b)
def op_move(eng, e):
    """MOVE: dx,dy,dz:i16, ticks:u16. coords are 16.16 fixed → dx*0x10000.
    Emits 'move' event so subscribers can capture MOVE's *own* ticks before
    next op (e.g. FM) overwrites e.ticks."""
    base = e.offset
    dx, dy, dz, t = _i16(e.seq, base + 2), _i16(e.seq, base + 4), _i16(e.seq, base + 6), _u16(e.seq, base + 8)
    e.x += dx << 16
    e.y += dy << 16
    e.z += dz << 16
    e.ticks = t
    if t: eng._break = True
    eng._emit('move', e, dx, dy, dz, t)
    e.offset += e.seq[base + 1]

@op(0x0c)
def op_move_target(eng, e):
    """MOVE_TARGET: 同 MOVE 但写 target_xyz."""
    base = e.offset
    dx, dy, dz, t = _i16(e.seq, base + 2), _i16(e.seq, base + 4), _i16(e.seq, base + 6), _u16(e.seq, base + 8)
    e.target_x += dx << 16
    e.target_y += dy << 16
    e.target_z += dz << 16
    e.ticks = t
    if t: eng._break = True
    e.offset += e.seq[base + 1]

@op(0x0d)
def op_inc_action_state(eng, e):
    """INC_ACTION_STATE: 全局 active action 的 state += 1."""
    if eng.active_action is not None:
        eng.active_action.state_code += 1
    e.offset += e.seq[e.offset + 1]

@op(0x0e)
def op_signal(eng, e):
    """SIGNAL: 设 active_action.state_code = signal, 调 wrapper. wrapper 可改 state 持久化."""
    base = e.offset
    sig = _i16(e.seq, base + 2)
    e.offset += e.seq[base + 1]   # 先推进 offset (handler 顺序在原版里)
    eng._signal(e, sig)

@op(0x0f)
def op_or_flags(eng, e):
    """OR_FLAGS: unit.flags |= u32. size=6."""
    base = e.offset
    e.flags |= _u32(e.seq, base + 2)
    e.offset += e.seq[base + 1]

@op(0x10)
def op_and_not_flags(eng, e):
    """AND_NOT_FLAGS: unit.flags &= ~u32."""
    base = e.offset
    e.flags &= ~_u32(e.seq, base + 2)
    e.offset += e.seq[base + 1]

@op(0x11)
def op_sound_play(eng, e):
    """SOUND_PLAY: id:u16."""
    base = e.offset
    sid = _u16(e.seq, base + 2)
    e.offset += e.seq[base + 1]
    eng._emit('sound_play', e, sid)

@op(0x12)
def op_sound_stop(eng, e):
    """SOUND_STOP: id:u16."""
    base = e.offset
    sid = _u16(e.seq, base + 2)
    e.offset += e.seq[base + 1]
    eng._emit('sound_stop', e, sid)

@op(0x13)
def op_set_swing_sound(eng, e):
    """SET_SWING_SOUND: 写全局 (DOIT_melee IMPACT 时用)."""
    base = e.offset
    eng.swing_sound = _u16(e.seq, base + 2)
    e.offset += e.seq[base + 1]
