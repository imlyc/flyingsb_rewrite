"""道具图标: `assets/ui/SITEM.png` (原版物品图标集).

规格 (实测): 640x240, 每格 **20x20**, 共 **32 列 x 12 行 = 384 格**;
**格号 == core.items 的 item_id** (已核对: 0=普通帽子 / 2=圆锥帽子 / 3=皮帽子 /
299=恢复药(葫芦) / 302=药草(花) / 305=仙桃(桃) ...).
每格自带 2px 边框; 格内背景为纯黑 → 抠黑底后叠到界面上.
"""

from __future__ import annotations

from pathlib import Path

import pygame

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "assets" / "ui" / "SITEM.png"

CELL = 20
COLS = 32
ROWS = 12

_sheet: pygame.Surface | None = None
_cache: dict[int, pygame.Surface | None] = {}


def _load() -> pygame.Surface | None:
    global _sheet
    if _sheet is None:
        if not SHEET.exists():
            return None
        img = pygame.image.load(str(SHEET))
        try:
            img = img.convert()
        except pygame.error:
            pass
        _sheet = img
    return _sheet


def icon(item_id: int) -> pygame.Surface | None:
    """item_id → 20x20 图标 (黑底已抠); 越界/缺资源返回 None."""
    if item_id in _cache:
        return _cache[item_id]
    sheet = _load()
    surf: pygame.Surface | None = None
    if sheet is not None and 0 <= item_id < COLS * ROWS:
        cell = sheet.subsurface(
            pygame.Rect((item_id % COLS) * CELL, (item_id // COLS) * CELL, CELL, CELL)).copy()
        cell.set_colorkey((0, 0, 0))
        surf = cell
    _cache[item_id] = surf
    return surf


def draw(surface: pygame.Surface, item_id: int, x: int, y: int) -> int:
    """在 (x,y) 画该道具图标, 返回图标宽度 (缺失时返回 0)."""
    s = icon(item_id)
    if s is None:
        return 0
    surface.blit(s, (x, y))
    return CELL
