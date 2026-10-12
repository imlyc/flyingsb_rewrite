"""角色小头像 / 说话人头像.

原版**没有独立的头像图集** (442 个 `ps_*.pcx` 全是 64×96 的行走网格), 所以这里取角色
**立姿精灵的头部区域**裁下并缩放作为头像 (对话/商店/背包共用).

key 可以是:
  · 角色中文名 (如 "孙悟空") → core.character_sprites.sprite_resource 解析;
  · 直接给图集资源名 (如 "ps_CMAN000", 手工 NPC 用).
"""

from __future__ import annotations

import pygame

_cache: dict[tuple[str, int], pygame.Surface | None] = {}


def _resource(key: str) -> str | None:
    if not key:
        return None
    if key.lower().startswith("ps_") or key.lower().startswith("fm_"):
        return key
    try:
        from core.character_sprites import CHARACTER_SPRITES, sprite_resource
        if key in CHARACTER_SPRITES:
            return sprite_resource(key)
    except Exception:
        pass
    return None


def head_face(key: str, size: int = 32) -> pygame.Surface | None:
    """key → size×size 头像 (头部+上身, 透明底); 解析不到返回 None."""
    ck = (key, size)
    if ck in _cache:
        return _cache[ck]
    surf: pygame.Surface | None = None
    res = _resource(key)
    if res:
        try:
            from core.sprites.loaders import get_character_sprite
            cs = get_character_sprite(res)
            frame = cs.frame_for_facing((0, 1), 0)      # 正面立姿帧
            if isinstance(frame, tuple):
                frame = frame[0]
            fw, fh = frame.get_size()
            crop = frame.subsurface(pygame.Rect(0, 0, min(fw, 64), min(fh, 64))).copy()
            try:
                crop = crop.convert_alpha()             # 色键 → 透明 (否则缩放后露绿底)
            except pygame.error:
                pass
            surf = pygame.transform.smoothscale(crop, (size, size))
        except Exception:
            surf = None
    _cache[ck] = surf
    return surf
