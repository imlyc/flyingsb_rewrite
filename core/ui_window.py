"""原版窗口框渲染 (九宫格). 素材: assets/ui/WHDLGBOX.pcx (原版对话框/信息框图集).

WHDLGBOX 里几种窗口 (按非透明区块):
  olive  y0-62    橄榄绿渐变 (菜单底色)
  teal   y96-162  青绿色窗口
  brown  y288-367 **棕色编织 —— 对白/信息框** (与攻略截图里的木框一致)
  wood   y383-446 木纹边 + 橄榄底

用法:
    win = NineSlice(BOX_RECTS["brown"])
    win.draw(surface, pygame.Rect(x, y, w, h))
八向边角固定、边条拉伸、中心纹理平铺 (保留编织质感, 不糊).
"""

from __future__ import annotations

from pathlib import Path

import pygame

ROOT = Path(__file__).resolve().parent.parent
SHEET_PATH = ROOT / "assets" / "ui" / "WHDLGBOX.pcx"

# 各窗口在原图上的区域 (x, y, w, h)
BOX_RECTS = {
    "olive": (0, 0, 512, 62),
    "teal": (0, 96, 512, 66),
    "brown": (0, 288, 512, 80),
    "wood": (0, 383, 512, 64),
}

_sheet: pygame.Surface | None = None


# 原图用**两种纯绿**做透明键 (拼图边界处两种都出现), 都要抠掉
_KEY_COLORS = ((0, 143, 0), (0, 255, 0))


def _load_sheet() -> pygame.Surface:
    global _sheet
    if _sheet is None:
        src = pygame.image.load(str(SHEET_PATH))
        w, h = src.get_size()
        out = pygame.Surface((w, h), pygame.SRCALPHA)
        out.blit(src, (0, 0))
        for y in range(h):
            for x in range(w):
                if src.get_at((x, y))[:3] in _KEY_COLORS:
                    out.set_at((x, y), (0, 0, 0, 0))
        _sheet = out
    return _sheet


class NineSlice:
    """把图集里一块窗口切成 9 片; 边角原样, 边条拉伸, 中心平铺."""

    def __init__(self, rect: tuple[int, int, int, int], margin: int = 8,
                 tile: int = 16) -> None:
        sheet = _load_sheet()
        x, y, w, h = rect
        m = margin
        self.m = m
        self.tl = sheet.subsurface((x, y, m, m)).copy()
        self.tr = sheet.subsurface((x + w - m, y, m, m)).copy()
        self.bl = sheet.subsurface((x, y + h - m, m, m)).copy()
        self.br = sheet.subsurface((x + w - m, y + h - m, m, m)).copy()
        self.top = sheet.subsurface((x + m, y, max(1, w - 2 * m), m)).copy()
        self.bottom = sheet.subsurface((x + m, y + h - m, max(1, w - 2 * m), m)).copy()
        self.left = sheet.subsurface((x, y + m, m, max(1, h - 2 * m))).copy()
        self.right = sheet.subsurface((x + w - m, y + m, m, max(1, h - 2 * m))).copy()
        # 中心取一小块做平铺源 (保留编织纹理)
        cx = x + (w - tile) // 2
        cy = y + (h - tile) // 2
        self.center = sheet.subsurface((cx, cy, tile, tile)).copy()

    @property
    def margin(self) -> int:
        return self.m

    def draw(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        m = self.m
        x, y, w, h = rect
        if w < 2 * m or h < 2 * m:              # 太小则退化为整块拉伸
            surface.blit(pygame.transform.scale(self.center, (max(1, w), max(1, h))),
                         (x, y))
            return
        iw, ih = w - 2 * m, h - 2 * m
        surface.blit(self.tl, (x, y))
        surface.blit(self.tr, (x + w - m, y))
        surface.blit(self.bl, (x, y + h - m))
        surface.blit(self.br, (x + w - m, y + h - m))
        surface.blit(pygame.transform.scale(self.top, (iw, m)), (x + m, y))
        surface.blit(pygame.transform.scale(self.bottom, (iw, m)), (x + m, y + h - m))
        surface.blit(pygame.transform.scale(self.left, (m, ih)), (x, y + m))
        surface.blit(pygame.transform.scale(self.right, (m, ih)), (x + w - m, y + m))
        # 中心: 纹理平铺 (裁剪到内容区, 免得越界)
        old = surface.get_clip()
        surface.set_clip(pygame.Rect(x + m, y + m, iw, ih))
        tw, th = self.center.get_size()
        for ty in range(0, ih, th):
            for tx in range(0, iw, tw):
                surface.blit(self.center, (x + m + tx, y + m + ty))
        surface.set_clip(old)


# 常用窗口 (懒加载缓存)
_CACHE: dict[str, NineSlice] = {}


def window(kind: str = "brown", margin: int = 8, tile: int = 16) -> NineSlice | None:
    key = f"{kind}:{margin}:{tile}"
    if key not in _CACHE:
        rect = BOX_RECTS.get(kind)
        if rect is None or not SHEET_PATH.exists():
            return None
        try:
            _CACHE[key] = NineSlice(rect, margin, tile)
        except Exception:
            return None
    return _CACHE[key]
