"""伤害数字 widget (per-digit drip + rise + hold + flash).

仿原版 FUN_004d05d8 / 04d0488 / 04d0330. 详细时序见类 docstring.
"""

from __future__ import annotations

import pygame

from core.sprites.loaders import (
    SBTLFONT_DAMAGE_BASE_FRAME,
    SBTLFONT_HEAL_BASE_FRAME,
    SBTLFONT_MISS_FRAMES,
)


class FloatText:
    """伤害数字 (per-digit drip + rise + hold + flash) — 仿原版 FUN_004d05d8/04d0488/04d0330.
    时序 (40ms/tick):
      drip:  spawn 一位 / 80ms (奇 tick 触发, 跟 exe FUN_004d0488 +0x144 & 1 同节奏)
      rise:  spawn 后 ~5 ticks (200ms) 弧线上升到峰值
      hold:  32 ticks (1280ms) 静止悬停
      flash: 32 ticks (1280ms) 每 2 ticks (80ms) 翻可见性
      done:  消失
    每位用 fm_SBTLFONT atlas frames 13..22 (= digit 0..9), MISS 用 frames 23/24/25/25.
    """
    TICK_MS = 30
    DRIP_PERIOD_TICKS = 2          # 1 位 / 2 ticks (= 80ms/digit)
    RISE_TICKS = 10                 # 400ms 完整跳跃 (起跳 → 峰 → 落回原点)
    HOLD_TICKS = 32                 # 1280ms 静止 (落回原点后)
    FLASH_TICKS = 32                # 1280ms 闪烁
    FLASH_TOGGLE_TICKS = 2          # 80ms 闪烁周期
    DIGIT_STRIDE_PX = 10            # 位间距 (跟 exe `local_14 * 0xa0000` = 10px 一致)
    RISE_PEAK_PX = 36               # 跳跃峰值高度

    def __init__(self, damage: int, remaining_hp: int,
                 world_x: int, world_y: int, started_at: int,
                 miss: bool = False, heal: bool = False) -> None:
        self.damage = damage
        self.remaining_hp = remaining_hp   # 兼容字段, 不在 float 里渲染 (持久 HP 标签另渲)
        self.world_x = world_x
        self.world_y = world_y
        self.started_at = started_at
        self.miss = miss
        self.heal = heal
        # 单行 frame 序列: MISS 红字母 / heal row-0 数字 / 普通红色 damage 数字
        if miss:
            self._frames = list(SBTLFONT_MISS_FRAMES)
        else:
            base = SBTLFONT_HEAL_BASE_FRAME if heal else SBTLFONT_DAMAGE_BASE_FRAME
            self._frames = [base + int(c) for c in str(max(0, damage))]
        self._n = len(self._frames)

    def _digit_state(self, digit_idx: int, now_ms: int) -> tuple[int, str, int]:
        """返回 (life_ticks, phase, sub_phase_ticks). phase ∈ 'pre','rise','hold','flash','done'."""
        spawn_offset_ms = digit_idx * self.DRIP_PERIOD_TICKS * self.TICK_MS
        elapsed = now_ms - self.started_at - spawn_offset_ms
        if elapsed < 0:
            return -1, 'pre', 0
        ticks = elapsed // self.TICK_MS
        if ticks < self.RISE_TICKS:
            return ticks, 'rise', ticks
        ticks -= self.RISE_TICKS
        if ticks < self.HOLD_TICKS:
            return ticks, 'hold', ticks
        ticks -= self.HOLD_TICKS
        if ticks < self.FLASH_TICKS:
            return ticks, 'flash', ticks
        return ticks, 'done', ticks

    def alive(self, now_ms: int) -> bool:
        # 全部 digit 都 done 才算结束
        last_idx = self._n - 1
        _, phase, _ = self._digit_state(last_idx, now_ms)
        return phase != 'done'

    @property
    def flash_started(self) -> bool:
        """是否任何一位进了 flash 阶段 (= 死亡动画触发点)."""
        return False   # 用 flash_started_at(now) 取代; 留 stub 兼容

    def flash_started_at(self, now_ms: int) -> bool:
        # 第一位最早进 flash, 用它当判据
        _, phase, _ = self._digit_state(0, now_ms)
        return phase in ('flash', 'done')

    def draw(self, surface: pygame.Surface,
             big_font: pygame.font.Font, small_font: pygame.font.Font,
             cam_x: int, cam_y: int, now_ms: int) -> None:
        from core.sprites.loaders import sbtlfont_frame
        total_w = (self._n - 1) * self.DIGIT_STRIDE_PX + 10
        base_x = self.world_x - cam_x - total_w // 2
        base_y = self.world_y - cam_y
        for i, frame_idx in enumerate(self._frames):
            _, phase, sub = self._digit_state(i, now_ms)
            if phase in ('pre', 'done'):
                continue
            if phase == 'flash' and (sub // self.FLASH_TOGGLE_TICKS) % 2 == 1:
                continue
            if phase == 'rise':
                t = sub / self.RISE_TICKS
                arc = 4.0 * t * (1.0 - t)
                dy = int(self.RISE_PEAK_PX * arc)
            else:
                dy = 0
            try:
                surf, ax, ay = sbtlfont_frame(frame_idx)
            except (FileNotFoundError, IndexError):
                continue
            # monospace 10px 槽 + ax 把窄字符居中 (I/1 宽 6, ax=-2 → 左 padding 2px).
            x = base_x + i * self.DIGIT_STRIDE_PX - ax
            y = base_y - dy
            surface.blit(surf, (x, y - surf.get_height()))
