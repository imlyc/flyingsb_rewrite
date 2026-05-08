"""共享的单位渲染工具: 帧选择 + anchor 对齐 blit.

世界地图和战斗场景都用. 战斗场景额外有 attack/reaction 状态, 自己在调用方处理后再
fallback 到这里的 locomotion picker.
"""
from __future__ import annotations

from dataclasses import dataclass

import pygame

from core.sprites import (
    CharacterSprite,
    Direction,
    IdleSprite,
    facing_to_direction,
)


@dataclass
class LocomotionState:
    """走路 / 转身 / 待机三态的输入. 累计时长由调用方维护."""
    facing: tuple[int, int]
    anim_time_ms: int = 0           # 移动中累加 (静止 = 0)
    idle_time_ms: int = 0           # 静止时累加 (移动 = 0)
    turn_remaining_ms: int = 0       # 90° 转身过渡帧剩余时间
    turn_from_facing: tuple[int, int] | None = None
    walk_frame_period_ms: int = 80   # 行走帧切换间隔
    idle_frame_period_ms: int = 400  # 待机呼吸帧切换间隔


def pick_locomotion_frame(
    walk_sprite: CharacterSprite,
    idle_sprite: IdleSprite | None,
    state: LocomotionState,
) -> tuple[pygame.Surface, tuple[int, int]]:
    """根据 locomotion 状态返回 (frame, feet_anchor).
    优先级: 转身过渡 > 走路帧 > 待机呼吸帧.
    anchor 按 *方向* 共享 (sprite.feet_for_facing), 同方向所有动画帧共用 — 防迈步左右晃.
    """
    facing = state.facing

    # 1. 转身过渡帧 (90°, 显示 col 5 的过渡帧)
    if state.turn_remaining_ms > 0 and state.turn_from_facing is not None:
        frame = walk_sprite.turn_frame(
            facing_to_direction(state.turn_from_facing),
            facing_to_direction(facing),
        )
        if frame is not None:
            return frame, walk_sprite.feet_for_facing(facing)

    # 2. 走路帧 (anim_time_ms > 0 = 移动中)
    if state.anim_time_ms > 0:
        anim_idx = int(state.anim_time_ms // state.walk_frame_period_ms) % walk_sprite.walk_frames
        return walk_sprite.frame_for_facing(facing, anim_idx), walk_sprite.feet_for_facing(facing)

    # 3. 待机呼吸 (用 06 idle atlas 两帧交替)
    if idle_sprite is not None:
        phase = int(state.idle_time_ms // state.idle_frame_period_ms) % 2
        return idle_sprite.frame_for_facing(facing, phase), idle_sprite.feet_for_facing(facing)

    # fallback: walk atlas col 0
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
