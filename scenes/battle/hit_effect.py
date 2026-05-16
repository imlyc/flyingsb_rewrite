"""命中特效 widget — 仿原版 DOIT_melee IMPACT spawn 的 blood entity.

每帧 ticks 可配 (= 原版 FM op 的 ticks 字段). 支持随机抖动偏移 (= 原版
FUN_005336c7() & 15 - 8 的 ±8px). 单 effect 跑完所有 frames 后自动消失.
"""

from __future__ import annotations

import pygame

from core.fm_frames import FM_FRAMES
from core.hit_effect_seq import HIT_EFFECT_TICK_MS
from core.sprites.loaders import get_fm_surface


class HitEffect:
    __slots__ = ("world_x", "world_y", "atlas_key", "frames",
                 "frame_ms", "started_at", "offset_x", "offset_y")

    def __init__(self, world_x: int, world_y: int,
                 atlas_key: str, frames: list[int], frame_ticks: int,
                 started_at: int,
                 offset_x: int = 0, offset_y: int = 0) -> None:
        self.world_x = world_x
        self.world_y = world_y
        self.atlas_key = atlas_key
        self.frames = frames
        self.frame_ms = frame_ticks * HIT_EFFECT_TICK_MS
        self.started_at = started_at
        self.offset_x = offset_x
        self.offset_y = offset_y

    def _frame_idx(self, now_ms: int) -> int | None:
        elapsed = now_ms - self.started_at
        if elapsed < 0:
            return None
        slot = elapsed // self.frame_ms
        if slot >= len(self.frames):
            return None
        return self.frames[slot]

    def alive(self, now_ms: int) -> bool:
        return self._frame_idx(now_ms) is not None

    def draw(self, surface: pygame.Surface, cam_x: int, cam_y: int, now_ms: int) -> None:
        fi = self._frame_idx(now_ms)
        if fi is None:
            return
        try:
            atlas_surf = get_fm_surface("fm_" + self.atlas_key.upper())
        except FileNotFoundError:
            return
        frames = FM_FRAMES.get(self.atlas_key)
        if frames is None or fi >= len(frames):
            return
        fx, fy, fw, fh, ax, ay = frames[fi]
        sub = atlas_surf.subsurface(pygame.Rect(fx, fy, fw, fh))
        # 锚点语义同 unit sprite: (ax, ay) 是 frame 内贴在世界点的位置.
        dx = self.world_x + self.offset_x - cam_x - ax
        dy = self.world_y + self.offset_y - cam_y - ay
        surface.blit(sub, (dx, dy))
