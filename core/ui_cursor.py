"""原版光标/指针图标: `assets/ui/WHARROW.png` (原版按键/方向箭头图集).

WHARROW 里是各色的**方向箭头**(下/左上/右上/上). 列表选择光标用其中的白色下箭头
旋转成 →(右) 使用.
"""

from __future__ import annotations

from pathlib import Path

import pygame

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "assets" / "ui" / "WHARROW.png"

# 白色下箭头 (实测位置: 第 1 行第 1 个)
_ARROW_DOWN = (44, 0, 20, 18)
# 旋转角 (pygame.rotate 逆时针): 下→右/左 各试; 这里 90 = 下箭头转成朝右
_ROT = {"down": 0, "right": 90, "up": 180, "left": 270}

_sheet: pygame.Surface | None = None
_cache: dict[str, pygame.Surface | None] = {}


def arrow(direction: str = "right") -> pygame.Surface | None:
    """方向箭头 (默认朝右, 用作列表光标); 缺素材返回 None."""
    if direction in _cache:
        return _cache[direction]
    global _sheet
    if _sheet is None:
        if not SHEET.exists():
            _sheet = None
        else:
            src = pygame.image.load(str(SHEET))
            out = pygame.Surface(src.get_size(), pygame.SRCALPHA)
            out.blit(src, (0, 0))
            for y in range(src.get_height()):
                for x in range(src.get_width()):
                    if src.get_at((x, y))[:3] in ((0, 143, 0), (0, 255, 0)):
                        out.set_at((x, y), (0, 0, 0, 0))
            _sheet = out
    surf = None
    if _sheet is not None:
        try:
            base = _sheet.subsurface(pygame.Rect(*_ARROW_DOWN)).copy()
            surf = pygame.transform.rotate(base, _ROT.get(direction, 0))
        except Exception:
            surf = None
    _cache[direction] = surf
    return surf
