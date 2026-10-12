"""把 assets/maps 里提取出的原版地图 (.map/.mfo/.pcx) 解析并渲染成 PNG 预览.

原版地图格式 (逆向自 mapset.dll 资源, 已用多张地图互验):
  .map = 120 个 u32 头部 + 2 张 W×H 的 u32 网格
    头部 (10 条 × 12 u32):
      u[0]=2 版本, u[1]=15 常量, u[2]/u[3] ?, u[4]/u[5] ?,
      u[6]=W 宽, u[7]=H 高, u[8]=tileset 列数, u[9]=tileset 行数,
      u[10]/u[11] 运行时指针 (忽略)
    网格 A = 可视瓦片索引 (0..cols*rows-1), 行优先
    网格 B = 碰撞/属性: 每格 u32, 高 16 位是 flag, 低 16 位是 tile 索引
  恒等式: 120 + 2*W*H == 文件 u32 总数 (已对 TARA_00P/TAM0_00P/T_LOC0_P/T_LOC1_P/T_LOC2_P 验证)
  .mfo = 文本元数据 (mapname / pcpos / jmp / battleset)
  .pcx = tileset 图集, 单格 64×48 (= core.sprites.base.TILE_W/TILE_H)

输出:
  assets/maps_preview/<base>.png   渲染好的地图
  assets/maps_preview/_index.json  地图索引 (名称/尺寸/瓦片集/pcpos)

跑法: cd rewrite && venv/Scripts/python -m tools.extract_maps
"""

from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAPS = ROOT / "assets" / "maps"
OUT = ROOT / "assets" / "maps_preview"

TILE_W = 64   # = core.sprites.base.TILE_W
TILE_H = 48   # = core.sprites.base.TILE_H
HEADER_U32 = 120


def _u32s(path: Path) -> list[int]:
    b = path.read_bytes()
    return list(struct.unpack("<%dI" % (len(b) // 4), b[: len(b) // 4 * 4]))


def parse_map(base: str) -> dict | None:
    """解析 <base>.map. 返回 None 表示不是本格式 (恒等式不成立)."""
    mp = MAPS / f"{base}.map"
    if not mp.exists():
        return None
    u = _u32s(mp)
    w, h = u[6], u[7]
    ts_cols, ts_rows = u[8], u[9]
    if not (1 <= w <= 256 and 1 <= h <= 256 and 1 <= ts_cols <= 256 and 1 <= ts_rows <= 256):
        return None
    if len(u) < HEADER_U32 + 2 * w * h:
        return None
    cells = w * h
    grid_a = u[HEADER_U32:HEADER_U32 + cells]
    grid_b = u[HEADER_U32 + cells:HEADER_U32 + 2 * cells]
    return {
        "w": w, "h": h, "ts_cols": ts_cols, "ts_rows": ts_rows,
        "grid_a": grid_a, "grid_b": grid_b,
    }


def parse_mfo(base: str) -> dict:
    """解析 <base>.mfo 文本 (GBK). 取 mapname + pcpos."""
    p = MAPS / f"{base}.mfo"
    info = {"mapname": None, "pcpos": []}
    if not p.exists():
        return info
    try:
        text = p.read_bytes().decode("cp949", "replace")   # .mfo 地名/注释是原版韩文
    except Exception:
        return info
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("mapname"):
            q = s.split("=", 1)[1].strip().strip('"').strip()
            info["mapname"] = q
        elif s.startswith("pcpos"):
            rhs = s.split("=", 1)[1]
            rhs = rhs.split("//")[0]
            nums = [int(x) for x in rhs.replace(",", " ").split() if x.lstrip("-").isdigit()]
            if len(nums) >= 2:
                info["pcpos"].append((nums[0], nums[1]))
    return info


def build_ts_index() -> dict[tuple[int, int], list[str]]:
    """扫描所有 P 面 tileset, 按网格尺寸 (cols, rows) 建索引.

    原版多张地图共用同一 tileset, 头部 u[8]/u[9] 记的就是 tileset 网格尺寸,
    所以按尺寸即可唯一定位 (同名地图优先, 见 find_tileset).
    """
    import pygame
    idx: dict[tuple[int, int], list[str]] = {}
    for p in MAPS.glob("*.pcx"):
        if not p.stem.endswith("P"):        # 只要 P 面 (S 面是对应阴影层)
            continue
        w, h = pygame.image.load(str(p)).get_size()
        idx.setdefault((w // TILE_W, h // TILE_H), []).append(p.stem)
    for v in idx.values():
        v.sort()
    return idx


def find_tileset(base: str, ts_cols: int, ts_rows: int,
                 index: dict[tuple[int, int], list[str]]) -> tuple[str, Path] | None:
    """定位地图用到的 tileset: 同名优先, 否则按网格尺寸匹配 (同页前缀优先)."""
    exact = MAPS / f"{base}.pcx"
    if exact.exists() and base.endswith("P"):
        return base, exact
    cands = index.get((ts_cols, ts_rows), [])
    if not cands:
        return None
    page = base[:5]
    same_page = [c for c in cands if c[:5] == page]
    pick = (same_page or cands)[0]
    return pick, MAPS / f"{pick}.pcx"


def render(base: str, info: dict, ts_name: str, ts_path: Path, out_png: Path) -> None:
    import pygame
    surf = pygame.image.load(str(ts_path)).convert()
    cw = surf.get_width() // info["ts_cols"]
    ch = surf.get_height() // info["ts_rows"]
    w, h, cells = info["w"], info["h"], info["grid_a"]
    img = pygame.Surface((w * TILE_W, h * TILE_H))
    img.fill((15, 15, 25))
    maxtile = info["ts_cols"] * info["ts_rows"]
    for r in range(h):
        for c in range(w):
            idx = cells[r * w + c]
            if idx >= maxtile:
                continue
            src = pygame.Rect((idx % info["ts_cols"]) * cw,
                              (idx // info["ts_cols"]) * ch, cw, ch)
            img.blit(surf, (c * TILE_W, r * TILE_H), src)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(img, str(out_png))


def main() -> int:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame
    pygame.init()
    pygame.display.set_mode((1, 1))

    bases = sorted(p.stem for p in MAPS.glob("*.map"))
    ts_index = build_ts_index()
    index: list[dict] = []
    ok = 0
    skipped = 0
    for base in bases:
        info = parse_map(base)
        if info is None:
            skipped += 1
            continue
        ts = find_tileset(base, info["ts_cols"], info["ts_rows"], ts_index)
        mfo = parse_mfo(base)
        entry = {
            "base": base,
            "mapname": mfo["mapname"],
            "pcpos": mfo["pcpos"],
            "w": info["w"], "h": info["h"],
            "ts_cols": info["ts_cols"], "ts_rows": info["ts_rows"],
            "tileset": ts[0] if ts else None,
        }
        if ts:
            try:
                render(base, info, ts[0], ts[1], OUT / f"{base}.png")
                entry["preview"] = f"{base}.png"
                ok += 1
            except Exception as e:
                entry["error"] = str(e)
        index.append(entry)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"解析 {len(bases)} 个 .map: 渲染 {ok}, 无图集 {len(index) - ok}, 跳过 {skipped}")
    print(f"索引: {(OUT / '_index.json').relative_to(ROOT)}")
    print(f"预览: {(OUT).relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
