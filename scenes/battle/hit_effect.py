"""命中特效渲染 — 直接读 anim_engine entity (kind='hit_effect') 的状态.

每个 effect 是一个独立 entity, 由 combat._spawn_effect_entity 创建, 跑标准 FM op 字节码
(= 原版 FUN_004d0c90 blood_spawn 同套路). 渲染不需要时基, 只读 entity.frame_idx +
entity.x/y (16.16 fixed 世界像素).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from core.fm_frames import FM_FRAMES
from core.sprites.loaders import get_fm_surface

if TYPE_CHECKING:
    from scenes.battle.scene import BattleScene


def draw_hit_effects(scene: "BattleScene", cam_x: int, cam_y: int) -> None:
    """扫 engine.entities 找 kind='hit_effect' 的实体, 按 atlas_key + frame_idx 画."""
    for ent in scene.battle.engine.entities:
        if ent.user_data.get('kind') != 'hit_effect':
            continue
        # EXIT op 触发后 playing flag 落下; 该 entity 不再画 (= 自然消失)
        if not ent.is_playing():
            continue
        atlas_key = ent.user_data.get('atlas_key')
        if not atlas_key:
            continue
        frames = FM_FRAMES.get(atlas_key)
        if frames is None or not (0 <= ent.frame_idx < len(frames)):
            continue
        try:
            atlas_surf = get_fm_surface("fm_" + atlas_key.upper())
        except FileNotFoundError:
            continue
        fx, fy, fw, fh, ax, ay = frames[ent.frame_idx]
        sub = atlas_surf.subsurface(pygame.Rect(fx, fy, fw, fh))
        sx = (ent.x >> 16) - cam_x - ax
        sy = (ent.y >> 16) - cam_y - ay
        scene.surface.blit(sub, (sx, sy))
