"""共享的单位渲染工具: 帧选择 + anchor 对齐 blit.

世界地图和战斗场景都用. 战斗场景额外有 attack/reaction 状态, 自己在调用方处理后再
fallback 到这里的 locomotion picker.
"""
from __future__ import annotations

import pygame

from core.anim_state import AnimationState
from core.sprites import (
    CharacterSprite,
    Direction,
    IdleSprite,
    WeakenedSprite,
    facing_to_direction,
)

# 重导出, 方便上层 import
__all__ = ["AnimationState", "pick_locomotion_frame", "blit_unit", "blit_shadow"]


def pick_locomotion_frame(
    walk_sprite: CharacterSprite,
    idle_sprite: IdleSprite | None,
    facing: tuple[int, int],
    anim: AnimationState,
    walk_period_ms: int = 80,
    idle_period_ms: int = 400,
    flying: bool = False,
    weakened_sprite: WeakenedSprite | None = None,
    weakened_period_ms: int = 280,
) -> tuple[pygame.Surface, tuple[int, int]]:
    """根据 (facing, anim) 返回 (frame, feet_anchor).
    优先级: 走路帧 > 虚弱帧 (HP<40%, 仅站立时) > 待机呼吸帧.
    anchor 按 *方向* 共享 (sprite.feet_for_facing), 同方向所有动画帧共用 — 防迈步左右晃.
    虚弱帧的 anchor 复用 walk_sprite 的 (= 站立姿势的脚点), 避免半蹲姿势自动检测偏移.
    flying=True: 飞行单位待机/移动都用 walk atlas 循环 (扇翅膀), 节奏 = idle_period_ms.
    weakened_sprite!=None: 站立时用 ps_*04 ping-pong (col 1↔2, 周期 280ms);
    移动时仍用走路帧 (虚弱不影响移动姿势, 跟原版一致).
    """
    if flying:
        # 飞行: 不区分静止/移动, 整圈扇翅膀总时长 = 其他角色呼吸总时长 (2 帧 × idle_period_ms).
        # 帧时 = 2 × idle_period_ms / walk_frames (CCROW 4 帧 → 200ms/帧, 配 idle_period_ms=400).
        # 累加两路时间避免静↔动切换重置
        t = anim.anim_time_ms + anim.idle_time_ms
        # 虚弱优先于飞行扇翅膀: HP<40% 时切到 ps_*04 ping-pong (跟地面单位同节奏).
        # 用累加 t 避免 reaction 间隙的时间重置.
        if weakened_sprite is not None:
            phase = int(t // weakened_period_ms) % 2
            return weakened_sprite.frame_for_facing(facing, phase), walk_sprite.feet_for_facing(facing)
        flap_period_ms = max(1, idle_period_ms * 2 // walk_sprite.walk_frames)
        anim_idx = int(t // flap_period_ms) % walk_sprite.walk_frames
        return walk_sprite.frame_for_facing(facing, anim_idx), walk_sprite.feet_for_facing(facing)
    if anim.anim_time_ms > 0:
        # 移动中: 走路帧优先 (虚弱状态也直立移动, 跟原版一致)
        anim_idx = int(anim.anim_time_ms // walk_period_ms) % walk_sprite.walk_frames
        return walk_sprite.frame_for_facing(facing, anim_idx), walk_sprite.feet_for_facing(facing)
    if weakened_sprite is not None:
        # 站立 + 虚弱: ps_*04 ping-pong. anchor 复用 walk sprite (= 站立姿势脚点),
        # 不用 weakened 自己的检测 (蹲姿身体偏移会让脚点 x 跑偏).
        phase = int(anim.idle_time_ms // weakened_period_ms) % 2
        return weakened_sprite.frame_for_facing(facing, phase), walk_sprite.feet_for_facing(facing)
    if idle_sprite is not None:
        phase = int(anim.idle_time_ms // idle_period_ms) % 2
        return idle_sprite.frame_for_facing(facing, phase), idle_sprite.feet_for_facing(facing)
    return walk_sprite.frame_for_facing(facing, 0), walk_sprite.feet_for_facing(facing)


def blit_unit(
    surface: pygame.Surface,
    frame: pygame.Surface,
    anchor: tuple[int, int],
    tile_center_x: int,
    tile_center_y: int,
    offset_x: int = 0,
    offset_y: int = 0,
    alpha: int | None = None,
) -> int:
    """把 frame 按 anchor (= feet 在 sprite 内坐标) 对齐到 tile 中心 + offset.
    返回 sprite 顶部 y (供调用方放 HP 标签等).
    """
    if alpha is not None:
        frame = frame.copy()
        frame.set_alpha(alpha)
    ax, ay = anchor
    blit_x = tile_center_x - ax + offset_x
    blit_y = tile_center_y - ay + offset_y
    surface.blit(frame, (blit_x, blit_y))
    return blit_y   # sprite 顶部 y


def blit_shadow(
    surface: pygame.Surface,
    shadow_surf: pygame.Surface,
    tile_center_x: int,
    tile_center_y: int,
) -> None:
    """阴影 center 对 tile 中心, 脚踩阴影正中."""
    rect = shadow_surf.get_rect(center=(tile_center_x, tile_center_y))
    surface.blit(shadow_surf, rect)
