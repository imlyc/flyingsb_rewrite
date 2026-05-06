"""渲染 10 主角 × 4 朝向 校验图.

输出 PNG. 每行一个角色, 每列一个 atlas row (0..3). 列标题写出 sprites.py
里 DEFAULT_DIRECTION_ROWS 当前的解释 (UP=0, DOWN=1, RIGHT=2, LEFT=3).
肉眼对比图中角色实际朝向是否匹配标题.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((1, 1))

from core.character_sprites import CHARACTER_SPRITES, sprite_resource  # noqa: E402
from core.sprites import DEFAULT_DIRECTION_ROWS, Direction, load_character_sprite  # noqa: E402

# 反查: row -> Direction 名称
ROW_TO_DIR: dict[int, str] = {row: d.name for d, row in DEFAULT_DIRECTION_ROWS.items()}

CELL_W, CELL_H = 80, 110
LABEL_W = 110
HEADER_H = 30
PAD = 4

names = list(CHARACTER_SPRITES.keys())
n_rows = len(names)
n_cols = 4  # atlas 的 4 行

W = LABEL_W + n_cols * CELL_W + PAD * 2
H = HEADER_H + n_rows * CELL_H + PAD * 2

surface = pygame.Surface((W, H))
surface.fill((245, 245, 245))

font_big = pygame.font.SysFont("PingFang SC", 16)
font_small = pygame.font.SysFont("Menlo", 12)

# 列标题
for col in range(n_cols):
    x = LABEL_W + col * CELL_W
    title = f"row {col}"
    sub = ROW_TO_DIR.get(col, "?")
    t1 = font_small.render(title, True, (60, 60, 60))
    t2 = font_big.render(sub, True, (10, 10, 10))
    surface.blit(t1, (x + 8, 4))
    surface.blit(t2, (x + 8, 16))

# 棋盘格背景, 透明可见
def checker(rect: pygame.Rect):
    for cy in range(rect.top, rect.bottom, 8):
        for cx in range(rect.left, rect.right, 8):
            if ((cx // 8) + (cy // 8)) % 2 == 0:
                pygame.draw.rect(surface, (220, 220, 220), pygame.Rect(cx, cy, 8, 8))

for ridx, name in enumerate(names):
    y = HEADER_H + ridx * CELL_H
    res = sprite_resource(name)
    label = f"{name}\n{res}"
    for i, line in enumerate(label.split("\n")):
        t = font_big.render(line, True, (10, 10, 10)) if i == 0 else font_small.render(line, True, (90, 90, 90))
        surface.blit(t, (4, y + 8 + i * 18))
    cs = load_character_sprite(res)
    for col in range(n_cols):
        x = LABEL_W + col * CELL_W
        cell = pygame.Rect(x + 4, y + 4, 64, 96)
        checker(cell)
        if col < cs.sheet.rows:
            frame = cs.sheet.frame(0, col)  # col=0 (idle), row=col (atlas row id)
            surface.blit(frame, cell.topleft)
        pygame.draw.rect(surface, (180, 180, 180), cell, 1)

OUT = ROOT.parent / "origin" / "images" / "verify_directions.png"
OUT.parent.mkdir(parents=True, exist_ok=True)
pygame.image.save(surface, str(OUT))
print(f"saved {OUT}")
