"""
通用动画字节码引擎 — 1:1 复刻 FlyingSB.exe 的 seq 字节码解释器 + 实体池 + per-tick advancer.

架构 (来自反向 ANIM_ENGINE_SPEC.md):
  - 单一字节码格式: [op_id:u8][total_size:u8][payload]
  - 20 个 op (0x00-0x13), 7 个会阻塞 (设 ticks > 0), 其余流式跑过
  - 实体池: 每个 entity 都有 seq_ptr/ticks/offset, advancer 每帧推所有实体
  - SIGNAL (op 0x0e) 是 seq 跟外部状态机的双向桥, hookable

不复刻的:
  - 不用 764 槽固定数组, 用 Python list 动态管理
  - 不用全局 BREAK_FLAG, 用本地变量
  - render mode 0/1/2 留给上层渲染器解释 atlas_slot 高 16 位
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional
import struct


# ============ 常量 / 信号 ============

# 阻塞 op 集合 (ticks > 0 时停)
BLOCKING_OPS = frozenset({0x04, 0x05, 0x06, 0x07, 0x08, 0x0b, 0x0c})

# 已知 SIGNAL (op 0x0e 的 a 参数, signed i16)
SIG_IMPACT       = -100
SIG_IMPACT_2     = -250
SIG_POST_IMPACT  = -105
SIG_END          = -110
SIG_INIT         = -1000
SIG_MID          = -1001
SIG_TRANSITION_A = -1002
SIG_TRANSITION_B = -1003
SIG_ATLAS_SWAP_A = -1004
SIG_ATLAS_SWAP_B = -1005


# ============ Entity ============

@dataclass
class Entity:
    """运行时动画实体 — 对应 exe 里 0x1ac=428B 的 entity slot."""
    # 标识
    id: int = -1                           # pool index, -1 = unmanaged

    # 渲染状态
    flags: int = 0                         # +0x04   bit 6=visible, bit 17=playing, bit 16=done
    x: int = 0                             # +0x08   16.16 fixed point world coords
    y: int = 0                             # +0x0c
    z: int = 0                             # +0x10
    target_x: int = 0                      # +0x20   op 0x0c 写
    target_y: int = 0                      # +0x24
    target_z: int = 0                      # +0x28
    pos_buf: bytes = b'\x00' * 0x24        # +0x3c   op 0x09/0a save/restore (36 字节)

    atlas_base: int = 0                    # +0x130  per-char atlas region base
    atlas_slot: int = 0                    # +0x134  低 16=slot id, 高 16=render mode (0/1/2)
    frame_idx: int = 0                     # +0x138

    # render state save (op 0x02/0x03)
    save_atlas_base: int = 0               # +0x15c
    save_atlas_slot: int = 0               # +0x160
    save_frame_idx: int = 0                # +0x164

    # think / state
    think_fn: Optional[Callable[['Entity', 'Engine'], None]] = None  # +0x148
    state_code: int = 0                    # +0x14c

    # seq runtime
    seq: bytes = b''                       # +0x150 (just store bytes directly)
    ticks: int = 0                         # +0x154
    offset: int = 0                        # +0x158

    # signal context (op 0x0e 临时设)
    signal_target: Optional['Entity'] = None  # +0x1a8

    # 自由扩展槽 (DOIT_melee 用 +0x3c..0x7d 当 impact_results, +0x110 当 caster.id 之类)
    user_data: dict = field(default_factory=dict)

    def is_playing(self) -> bool:
        return bool(self.flags & 0x20000) and len(self.seq) > 0


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


# ============ Engine ============

class Engine:
    """
    动画引擎: 管实体池 + 跑 advancer + 路由 SIGNAL.

    用法:
        eng = Engine()
        eng.on('signal', my_signal_handler)    # 订阅 wrapper 状态机响应
        eng.on('sound_play', sfx_player)
        eng.on('frame_change', renderer)        # render hook (optional)

        unit = eng.spawn(think_fn=None)         # 创建实体
        eng.attach_seq(unit, seq_bytes)         # 挂 seq, 跑到第一个阻塞
        ...
        eng.tick()                              # 主循环每帧调一次
    """

    def __init__(self):
        self.entities: list[Entity] = []
        self.active_action: Optional[Entity] = None  # 对应 exe DAT_008698dc
        self.swing_sound: int = -1                   # 对应 0x6566c0
        self._break: bool = False
        self._handlers: dict[str, list[Callable]] = {}

    # --- 事件订阅 ---

    def on(self, event: str, fn: Callable):
        """订阅事件: 'signal'(entity, sig_id), 'sound_play'(entity, id), 'sound_stop'(entity, id),
        'frame_change'(entity, atlas_slot, frame_idx), 'move'(entity, dx, dy, dz, ticks)."""
        self._handlers.setdefault(event, []).append(fn)

    def _emit(self, event: str, *args):
        for fn in self._handlers.get(event, ()):
            fn(*args)

    # --- 实体管理 ---

    def spawn(self, think_fn: Optional[Callable] = None) -> Entity:
        """创建新实体, 对应 OBJ_create. 立即调一次 think_fn(state=-1) 做 init."""
        e = Entity()
        e.id = len(self.entities)
        e.flags = 0x800
        if think_fn is not None:
            e.flags |= 0x10000
            e.think_fn = think_fn
            e.state_code = -1
            think_fn(e, self)        # init call
            e.state_code = 0
        self.entities.append(e)
        return e

    def destroy(self, e: Entity):
        """对应 FUN_004c4a6f. 清字段, 不真删 (留个洞 = 原版语义)."""
        e.flags = 0
        e.seq = b''
        e.ticks = 0
        e.offset = 0
        e.think_fn = None
        e.state_code = 0
        e.signal_target = None
        e.user_data.clear()

    # --- seq 操作 ---

    def attach_seq(self, e: Entity, seq: bytes):
        """对应 FUN_00438d40 attach_seq: 挂 seq + 立即跑到第一个阻塞 op."""
        e.flags |= 0x20040           # bit 6 (visible) + bit 17 (playing)
        e.seq = seq
        e.ticks = 0
        e.offset = 0
        self._break = False
        while not self._break:
            self._dispatch_one(e)

    def _dispatch_one(self, e: Entity):
        """跑下一个 op. handler 自己负责 advance offset."""
        if e.offset >= len(e.seq):
            # 越界 = 隐式 EXIT (seq 跑完没 op 0x00). 原版 exe 靠后续 attach_seq 覆盖,
            # 我们这里直接清 playing flag 让 advancer 不再处理.
            e.flags &= ~0x20000
            self._break = True
            return
        op_id = e.seq[e.offset]
        handler = DISPATCH[op_id] if 0 <= op_id < len(DISPATCH) else None
        if handler is None:
            # 未知 op: 按 size byte 跳过 (字节码自描述, 安全)
            sz = e.seq[e.offset + 1] if e.offset + 1 < len(e.seq) else 1
            e.offset += max(sz, 1)
            return
        prev_state = e.state_code
        prev_frame = (e.atlas_slot, e.frame_idx)
        handler(self, e)
        # render hook
        if (e.atlas_slot, e.frame_idx) != prev_frame:
            self._emit('frame_change', e, e.atlas_slot, e.frame_idx)

    def _signal(self, source_unit: Entity, sig: int):
        """op 0x0e 实现: 把 signal 路由给 active_action 的 think_fn."""
        # 先发事件给外部订阅
        self._emit('signal', source_unit, sig)
        # 内部 wrapper 路由 (对应 FUN_004cba90)
        if self.active_action is None or self.active_action.think_fn is None:
            return
        a = self.active_action
        a.signal_target = source_unit
        old_state = a.state_code
        a.state_code = sig
        a.think_fn(a, self)
        if a.state_code == sig:
            a.state_code = old_state
        a.signal_target = None

    # --- per-frame advancer ---

    def tick(self):
        """对应 FUN_00438e00. 每帧调一次, 推所有活实体."""
        for e in self.entities:
            if not e.is_playing():
                continue
            self._break = False
            while not self._break:
                if e.ticks == 0:
                    self._dispatch_one(e)
                else:
                    e.ticks -= 1
                    self._break = True


# ============ Convenience: build seq bytecode ============

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
        0x00: 4, 0x01: 4, 0x02: 4, 0x03: 4,
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
