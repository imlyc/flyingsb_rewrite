"""按图修正宝箱坐标 (assets/chest_fixes.json).

原理: 权威宝箱表 (chests.json, 1022 箱) 对绝大多数图坐标正确 (经门口径可达 94.5%),
但**少数图的 y 坐标系颠倒** —— 典型是小森林 TBB0___P: 原样 4 箱全嵌在 7 行厚的实心树墙
小龛里 (flag=11 全包围, .mfo 无 jmp、无 transitions, 原版不可能走进去), y 翻转后 4 箱
全落在上方开阔草地 (渲染确认: 翻转位旁还有烘焙的物品美术)。

本工具扫出候选图 (原样可达率 < 翻转可达率 且原样明显差), 供人工渲染确认后写入
chest_fixes.json。**不自动写入** —— 逐图渲染对比 (红=原样, 绿=翻转) 再定, 防误修。

用法:
    python tools/calibrate_chest_coords.py            # 列出候选
    python tools/calibrate_chest_coords.py --render   # 候选图渲染对比图 _chest_cmp/<base>.png
"""
from __future__ import annotations

import json
import os
import sys
from collections import deque
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pygame  # noqa: E402

from core import real_map as realm  # noqa: E402
from core import world_graph as wg  # noqa: E402
from core.sprites.base import TILE_W, TILE_H  # noqa: E402

ASSETS = ROOT / "assets"


def _reachable(m: "realm.RealMap", tr: set) -> set:
    seeds = list(tr) or [m.start_pos()]
    seen, q = set(), deque()
    for s in seeds:
        if m.passable(*s) or s in tr:
            seen.add(s)
            q.append(s)
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if (nx, ny) in seen or not m.in_bounds(nx, ny):
                continue
            if m.passable(nx, ny) or (nx, ny) in tr:
                seen.add((nx, ny))
                q.append((nx, ny))
    return seen


def _hit(seen: set, m: "realm.RealMap", x: int, y: int) -> bool:
    return any(p in seen for p in ((x, y), (x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
               if m.in_bounds(*p))


def main() -> int:
    pygame.init()
    pygame.display.set_mode((64, 64))
    chests = json.loads((ASSETS / "chests.json").read_text(encoding="utf-8"))["maps"]
    render = "--render" in sys.argv
    out_dir = ROOT / "_chest_cmp"
    candidates = []
    for base, lst in chests.items():
        try:
            m = realm.load(base)
        except Exception:
            continue
        if not lst:
            continue
        seen = _reachable(m, wg.transitions(base))
        a = sum(1 for c in lst if _hit(seen, m, int(c["x"]), int(c["y"])))
        f = sum(1 for c in lst if _hit(seen, m, int(c["x"]), m.h - 1 - int(c["y"])))
        if f > a:                                    # 翻转严格更好 -> 候选
            candidates.append((base, len(lst), a, f))
            print(f"候选 {base}: 共{len(lst)} 原样可达{a} 翻转可达{f}")
            if render:
                _render_compare(base, m, lst, out_dir)
    print(f"\n共 {len(candidates)} 张候选图 (翻转严格更好)。")
    print("逐图看 _chest_cmp/<base>.png (红=原样, 绿=翻转), 确认后把图名写进 assets/chest_fixes.json 的 y_flip。")
    return 0


def _render_compare(base: str, m, lst: list, out_dir: Path) -> None:
    out_dir.mkdir(exist_ok=True)
    img = pygame.Surface((m.w * TILE_W, m.h * TILE_H))
    m.draw_terrain(img, 0, 0)
    for c in lst:
        x, y = int(c["x"]), int(c["y"])
        pygame.draw.rect(img, (255, 40, 40), (x * TILE_W, y * TILE_H, TILE_W, TILE_H), 2)
        yy = m.h - 1 - y
        pygame.draw.rect(img, (40, 255, 40), (x * TILE_W, yy * TILE_H, TILE_W, TILE_H), 2)
    s = min(2.0, 1400 / img.get_width())
    small = pygame.transform.smoothscale(
        img, (int(img.get_width() * s), int(img.get_height() * s)))
    pygame.image.save(small, str(out_dir / f"{base}.png"))


if __name__ == "__main__":
    raise SystemExit(main())
