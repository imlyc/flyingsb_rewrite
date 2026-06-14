"""Entity dataclass + 信号常量 + 阻塞 op 集合.

对应 exe 里 0x1ac=428B 的 entity slot. 字段偏移注释来自 ANIM_ENGINE_SPEC.md.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional


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

    # 速度 (16.16 fixed/tick) — 给 think_fn 物理用 (e.g. 抛物线投射物). 普通 entity 默认 0.
    vx: int = 0
    vy: int = 0
    vz: int = 0

    # signal context (op 0x0e 临时设)
    signal_target: Optional['Entity'] = None  # +0x1a8

    # 自由扩展槽 (DOIT_melee 用 +0x3c..0x7d 当 impact_results, +0x110 当 caster.id 之类)
    user_data: dict = field(default_factory=dict)

    # 池回收簿记 (engine 用): _born_tick = spawn 时的 tick 序号 (防本帧被 think); _pooled = 已归还空闲表.
    _born_tick: int = -1
    _pooled: bool = False

    def is_playing(self) -> bool:
        return bool(self.flags & 0x20000) and len(self.seq) > 0

    def reset(self) -> None:
        """复用槽位前清回初始态 (= 原版 entity slot 回收). 不动 id (= 固定槽位号)."""
        self.flags = 0
        self.x = self.y = self.z = 0
        self.target_x = self.target_y = self.target_z = 0
        self.pos_buf = b'\x00' * 0x24
        self.atlas_base = self.atlas_slot = self.frame_idx = 0
        self.save_atlas_base = self.save_atlas_slot = self.save_frame_idx = 0
        self.think_fn = None
        self.state_code = 0
        self.seq = b''
        self.ticks = self.offset = 0
        self.vx = self.vy = self.vz = 0
        self.signal_target = None
        self.user_data = {}      # 新 dict (而非 clear): 任何对旧 dict 的悬挂引用看不到新数据
