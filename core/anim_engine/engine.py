"""Engine 主类: 管实体池 + 跑 advancer + 路由 SIGNAL."""

from __future__ import annotations
from typing import Callable, Optional

from core.anim_engine.entity import Entity
from core.anim_engine.ops import DISPATCH


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
