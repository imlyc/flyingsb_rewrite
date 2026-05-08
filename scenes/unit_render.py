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
) -> tuple[pygame.Surface, tuple[int, int]]:
    """根据 (facing, anim) 返回 (frame, feet_anchor).
    优先级: 走路帧 > 待机呼吸帧.
    anchor 按 *方向* 共享 (sprite.feet_for_facing), 同方向所有动画帧共用 — 防迈步左右晃.
    """
    if anim.anim_time_ms > 0:
        anim_idx = int(anim.anim_time_ms // walk_period_ms) % walk_sprite.walk_frames
        return walk_sprite.frame_for_facing(facing, anim_idx), walk_sprite.feet_for_facing(facing)
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
