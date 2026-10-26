"""原版真实地图 (.map + tileset .pcx/.mat) 加载 / 渲染 / 通行判定 —— 全部按 exe 真值.

地图格式 (逆向自 map.cpp: 加载 FUN_004b5ac3 / 表 FUN_004b851c, 2026-10-12):
  .map = 0x1E0 字节头 + **两层** [tiles(W×H u32) + attrs(W×H u32)]
    头部每层 0x30 字节 (12 u32): u[6]=W, u[7]=H (第二层在 u[12+6]/u[12+7], 0×0 = 无第二层);
    全部 487 张图都满足 len == 0x1E0 + 8·W0·H0 + 8·W1·H1.
    第 0 层 = 地面 (P), 第 1 层 = 高处 (S: 桥 / 城墙顶 / 二楼), 各自有瓦片与属性.
  attrs 每格: 低 16 位 = exe 表 ATTR_TABLE[0x104] (VA 0x6521D4) 的下标, 高 16 位 = type(2b)+level(3b):
    cell = ATTR_TABLE[idx] & ~0x1F | (attr>>16)%4 | ((attr>>18)&7)<<2
    bit 9      = 实心 (不可进入)                         —— FUN_004b4e6b / FUN_0049e2b5
    bit 5..8   = 从本格**出去**时被挡的方向 (上/下/左/右)  —— 栅栏 / 悬崖边
    bit 19..20 = 事件类型 (1 = 传送/触发), bit 21..25 = 事件(jmp)下标, bit 26..28 = 朝向
  **地图 ↔ 图集** 不是同名关系: exe 里有一张 500 项地图表 (VA 0x6474D0, 位置 ID 为下标),
    每项给出 map 资源名 + tileset 资源名 (487 张里 425 张用别人的图集) → assets/map_table.json
    (tools/extract_map_table.py). 图集 = <tileset>P.pcx (地面层) / <tileset>S.pcx (高层),
    <tileset>S.pcx 与 P 同网格: 第 N 格 = P 第 N 格的"镂空版" (树冠/屋檐只留物件像素, 其余黑=透明),
    压精灵时用它 (FUN_004b8aa9: 有镂空版用镂空版, 否则整格). .mat 每瓦片 u32: P 里 0 = 空格不画;
    S 里 0 = 没有镂空版.
  .mfo = 文本元数据 (mapname / pcpos / jmp ...), 由 tools/extract_events.py 解析.

本类同时实现 BattleScene / WorldMapScene 期望的 "地形提供者" 接口:
  w / h / draw_terrain(surface, cam_x, cam_y, rows) / draw_overlay(...) / _camera_offset()
  passable(x, y) / can_move(x, y, dx, dy) / build_battle_map()

通行: 原版玩家的判定是 FUN_0049e2b5(x, y, dir, 0x32):
  目标格 bit9 实心 → 不能走; 本格 bit(5+dir) → 不能朝该方向出去. 没有别的规则.
  层: 原版玩家带一个"层号" (pcpos 的 z); 两层 = 两个海拔区域 (五指村: 草地=0, 东南红土台地=1,
  木梯连接; 山地图 TOH0_* 出生在第 1 层, 第 0 层根本没碰撞). 切层 (FUN_004b4f56):
  目标格 bit12 = 坡/梯口, 朝向 = bit26..28: 沿该朝向走上去 → 到第 1 层, 逆向走上去 → 回第 0 层.
  (bit17 的另一种切层 433 格 / 38 张图 尚未实现.)
"""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path

import pygame

from core.battle.data import BattleMap
from core.sprites.base import TILE_W, TILE_H

ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = ROOT / "assets" / "maps"
MAP_TABLE_PATH = ROOT / "assets" / "map_table.json"
ATTR_TABLE_PATH = ROOT / "assets" / "map_attr_table.json"

HEADER_BYTES = 0x1E0
LAYER_HDR_U32 = 12

# 竞技场默认用的地图 (TARA = 竞技场 hall)
DEFAULT_ARENA_MAP = "TARA_01P"     # 西州格鬥場 擂台 (地图表 #249), 全图连通; TARA_00P 只是入口
# 世界地图默认用的地图 (T_LOC0 = 东海之滨)
DEFAULT_WORLD_MAP = "T_LOC0_P"

CELL_SOLID = 1 << 9
CELL_EDGE_SHIFT = 5          # bit5..8: 上/下/左/右
DIR_UP, DIR_DOWN, DIR_LEFT, DIR_RIGHT = 0, 1, 2, 3
DIR_OF_DELTA = {(0, -1): DIR_UP, (0, 1): DIR_DOWN, (-1, 0): DIR_LEFT, (1, 0): DIR_RIGHT}

MAT_EMPTY, MAT_OVER, MAT_UNDER = 0, 0x100, 0x200
CELL_TALL = 1 << 0           # type bit0: 高物件 (墙/屋顶/树/桥), 画在其基线行以北的精灵之上
CELL_RAMP = 1 << 12          # 坡/梯口: 进入时按朝向切层
CELL_STAIR = 1 << 17         # 崖梯: 朝实心格走时跨 2 格 (FUN_004b4f56 返回 flag 2)
CELL_STAIR_DIRECTED = 1 << 10  # 崖梯只允许 bit26..28 的朝向
# 斜梯 (属性下标 0x32..0x3B, exe 表 50..59): (下标区间, 按键方向, 附加 dy, 斜向方向码)
_DIAG = ((0x32, 0x35, DIR_RIGHT, -1, 4), (0x33, 0x36, DIR_LEFT, 1, 5),
         (0x37, 0x3A, DIR_RIGHT, 1, 7), (0x38, 0x3B, DIR_LEFT, -1, 6))
# 移动方向码 (FUN_004b4f56 返回值高字节): 0 上 1 下 2 左 3 右, 斜梯上 4 右上 5 左下 6 左上 7 右下
OPPOSITE = {DIR_UP: DIR_DOWN, DIR_DOWN: DIR_UP, DIR_LEFT: DIR_RIGHT, DIR_RIGHT: DIR_LEFT,
            4: 5, 5: 4, 6: 7, 7: 6}
COLORKEY_INDEX = 0           # 8bpp PCX 调色板 0 号 (黑) = 透明 (S 层图集全靠它)

# 兼容旧代码/测试引用 (旧的"高 16 位 flag"启发式, 已被 exe 真值取代, 仅保留符号)
WALK_FLAGS = frozenset({0, 3, 7})


def flag_walkable(f: int) -> bool:
    return (f & 3) != 3 or (f >> 2) <= 1


_inst_cache: dict[str, "RealMap"] = {}
_map_table: dict[str, dict] | None = None
_attr_table: list[int] | None = None


# ---------------- 资源探测 ----------------
def maps_available() -> bool:
    return MAPS_DIR.is_dir() and any(MAPS_DIR.glob("*.map"))


def list_maps() -> list[str]:
    if not MAPS_DIR.is_dir():
        return []
    return sorted(p.stem for p in MAPS_DIR.glob("*.map"))


def is_available(base: str) -> bool:
    return (MAPS_DIR / f"{base}.map").exists()


def map_table() -> dict[str, dict]:
    """{map 资源名: {id, tileset, bgm, name, ...}} (assets/map_table.json); 缺文件 → {}."""
    global _map_table
    if _map_table is None:
        _map_table = {}
        if MAP_TABLE_PATH.exists():
            for row in json.loads(MAP_TABLE_PATH.read_text(encoding="utf-8")):
                _map_table[row["map"]] = row
    return _map_table


def attr_table() -> list[int] | None:
    global _attr_table
    if _attr_table is None and ATTR_TABLE_PATH.exists():
        _attr_table = json.loads(ATTR_TABLE_PATH.read_text(encoding="utf-8"))
    return _attr_table


def decode_cell(attr: int, table: list[int] | None) -> int:
    """.map 属性 u32 → exe 运行时 cell 值 (FUN_004b5ac3 的换算)."""
    idx = attr & 0xFFFF
    if table is None:
        # 没有 exe 表时退化: 只认 type==3 且 level>=2 为实心 (旧启发式)
        return 0 if flag_walkable(attr >> 16) else CELL_SOLID
    if idx >= len(table):
        return 0
    return (table[idx] & ~0x1F) | ((attr >> 16) % 4) | (((attr >> 18) & 7) << 2)


def _load_surface(name: str) -> pygame.Surface | None:
    path = MAPS_DIR / f"{name}.pcx"
    if not path.exists():
        return None
    surf = pygame.image.load(str(path))
    if surf.get_bitsize() == 8:
        key = surf.get_palette_at(COLORKEY_INDEX)
    else:
        key = surf.get_at((0, 0))
    surf.set_colorkey(key)
    if pygame.display.get_surface() is not None:
        surf = surf.convert()
        surf.set_colorkey(key)
    return surf


def _load_mat(name: str) -> list[int] | None:
    path = MAPS_DIR / f"{name}.mat"
    if not path.exists():
        return None
    raw = path.read_bytes()
    u = struct.unpack("<%dI" % (len(raw) // 4), raw[: len(raw) // 4 * 4])
    return list(u[LAYER_HDR_U32:])


# ---------------- RealMap ----------------
class RealMap:
    """一张原版地图 (两层可视 + 通行). 兼作 BattleScene 的地形提供者."""

    def __init__(self, base: str) -> None:
        self.base = base
        raw = (MAPS_DIR / f"{base}.map").read_bytes()
        hdr = struct.unpack_from("<%dI" % (2 * LAYER_HDR_U32), raw, 0)
        self.w, self.h = hdr[6], hdr[7]
        self.w1, self.h1 = hdr[LAYER_HDR_U32 + 6], hdr[LAYER_HDR_U32 + 7]
        n0, n1 = self.w * self.h, self.w1 * self.h1
        if len(raw) < HEADER_BYTES + 8 * (n0 + n1):
            raise ValueError(f"{base}.map 尺寸不符 ({len(raw)} B, 期望 {HEADER_BYTES + 8 * (n0 + n1)})")
        off = HEADER_BYTES
        self.grid = list(struct.unpack_from(f"<{n0}I", raw, off)); off += n0 * 4
        self.attr = list(struct.unpack_from(f"<{n0}I", raw, off)); off += n0 * 4
        self.grid1 = list(struct.unpack_from(f"<{n1}I", raw, off)); off += n1 * 4
        self.attr1 = list(struct.unpack_from(f"<{n1}I", raw, off))

        table = attr_table()
        self.cells = [decode_cell(a, table) for a in self.attr]
        self.cells1 = [decode_cell(a, table) for a in self.attr1]
        # 第 1 层只有与第 0 层同尺寸时才参与通行并集 (高处桥/城墙顶)
        self._layer1 = n1 == n0 and n1 > 0
        # 兼容旧接口: tail[i] = (第 1 层瓦片, 第 1 层属性)
        self.tail: list[tuple[int, int]] = (
            list(zip(self.grid1, self.attr1)) if self._layer1 else [(0, 0)] * n0)

        self.ts_name = self._resolve_tileset()
        self.tileset = _load_surface(self.ts_name)
        if self.tileset is None:
            raise FileNotFoundError(f"{base}: 图集 {self.ts_name}.pcx 不存在")
        tw, th = self.tileset.get_size()
        self.ts_cols, self.ts_rows = tw // TILE_W, th // TILE_H
        self.cell_w, self.cell_h = TILE_W, TILE_H
        self.mat = _load_mat(self.ts_name)
        s_name = self.ts_name[:-1] + "S"
        self.tileset_s = _load_surface(s_name)          # 镂空版图集 (压精灵用)
        self.mat_s = _load_mat(s_name) if self.tileset_s is not None else None
        if self.tileset_s is not None:
            sw, sh = self.tileset_s.get_size()
            self.ts_cols_s, self.ts_rows_s = sw // TILE_W, sh // TILE_H
        else:
            self.ts_cols_s = self.ts_rows_s = 0
        self.pcpos = self._read_pcpos()
        # 分层卷动 (原版 FUN_004b42b0 / FUN_004b439e): 每层 [中心(格,16.16), 环绕标志, 比例(16.16), 自动速度, 计数].
        # 载图时默认 中心=(w/2,h/2) 比例=1 → 两层跟镜头 1:1; .mfo 的 "scroll L = ..." 行覆盖 (序章云图 TCL0:
        # 层 0 中心 (0,24) 比例 y 0.3125 = 远景云层慢速视差; 天空图 TDS5 等: 比例 0.3125 + 环绕).
        # 活动层 (角色/镜头所在, 画在精灵间) = 地图表 flags >> 1 (FUN_004b851c: DAT_007eb554).
        row = map_table().get(self.base) or {}
        self.active_layer = (row.get("flags", 0) >> 1) & 1
        self.scroll = self._read_scroll()
        self.parallax = self.active_layer != 0 or any(
            sc != self._default_scroll(L) for L, sc in enumerate(self.scroll))
        # "高物件"瓦片 (cell type bit0: 墙/屋顶/树/桥): 原版 FUN_004b8aa9 在画完精灵后按
        # 基线 (y + 1 + level) 行再盖一遍 → 角色在它北边就被挡住. 按基线行分组.
        # 按**角色所在层**的属性判 (FUN_004b8aa9 用 param_1=层 读 cell): 站在桥上 (层 1) 时桥格
        # 在层 1 的属性是普通地面, 不再盖人; 站在桥下 (层 0) 时桥格是高物件, 盖人.
        self._rebuild_tall()
        # 层 1 有自己的瓦片 (天空图等) 才用它画, 否则 (五指村的桥) 画层 0 的瓦片
        self._layer1_has_tiles = self._layer1 and any(self.grid1)
        # 默认通行层: 出生点所在层 (有第 1 层数据时才允许 1); 场景按玩家当前层传 layer 参数
        self.layer = 1 if (self._layer1 and self.pcpos and self.pcpos[0][2] == 1) else 0
        self.cells_active = self.cells1 if self.layer == 1 else self.cells

    # ---- 资源解析 ----
    def _resolve_tileset(self) -> str:
        row = map_table().get(self.base)
        if row and (MAPS_DIR / f"{row['tileset']}.pcx").exists():
            return row["tileset"]
        # 没有 exe 地图表时的退化: 同名 → 同页前缀 → 任意
        if (MAPS_DIR / f"{self.base}.pcx").exists():
            return self.base
        cands = sorted(p.stem for p in MAPS_DIR.glob("*P.pcx"))
        page = [c for c in cands if c[:5] == self.base[:5]]
        if page:
            return page[0]
        if not cands:
            raise FileNotFoundError(f"{self.base}: 没有任何 tileset")
        return cands[0]

    def _read_pcpos(self) -> list[tuple[int, int, int]]:
        """.mfo 的 pcpos 行 → [(x, y, z)]."""
        path = MAPS_DIR / f"{self.base}.mfo"
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="cp949", errors="replace").splitlines():
            m = re.match(r"\s*pcpos\s+\d+\s*=\s*([-\d]+)\s*,\s*([-\d]+)\s*,\s*([-\d]+)", line)
            if m:
                out.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
        return out

    def _rebuild_tall(self) -> None:
        self._tall: list[dict[int, list[tuple[int, int]]]] = [{}, {}]
        for L, cells in ((0, self.cells), (1, self.cells1 if self._layer1 else [])):
            for i, v in enumerate(cells):
                if v & CELL_TALL:
                    y = i // self.w
                    r = min(self.h - 1, y + ((v >> 2) & 7))
                    self._tall[L].setdefault(r, []).append((i % self.w, y))

    def patch_cells(self, x0: int, y0: int, w: int, h: int, cells: list[list[int]]) -> None:
        """门/机关 (FUN_004b82f4): 把 w×h 格的 [层0瓦片, 层0属性, 层1瓦片, 层1属性] 写进地图并重算通行."""
        table = attr_table()
        k = 0
        for j in range(h):
            for i in range(w):
                x, y = x0 + i, y0 + j
                if k >= len(cells):
                    return
                t0, a0, t1, a1 = cells[k]
                k += 1
                if not self.in_bounds(x, y):
                    continue
                idx = y * self.w + x
                self.grid[idx], self.attr[idx] = t0, a0
                self.cells[idx] = decode_cell(a0, table)
                if self._layer1:
                    self.grid1[idx], self.attr1[idx] = t1, a1
                    self.cells1[idx] = decode_cell(a1, table)
                    self.tail[idx] = (t1, a1)
        self._rebuild_tall()
        self._layer1_has_tiles = self._layer1 and any(self.grid1)

    def _default_scroll(self, L: int) -> dict:
        w, h = (self.w, self.h) if L == 0 else (self.w1, self.h1)
        return {"half": (w // 2, h // 2), "wrap": (1, 1), "scale": (1.0, 1.0), "speed": (0.0, 0.0)}

    def _read_scroll(self) -> list[dict]:
        """.mfo 的 scroll 行 → 每层卷动参数 (FUN_004b42b0 的 11 个参数顺序:
        偏移x,y(载图后由 FUN_004b439e 重算, 忽略), 中心x,y (16.16 格), 环绕x,y (-1 = 环绕), 比例x,y (16.16),
        自动速度x,y (16.16 像素/帧), 计数)."""
        out = [self._default_scroll(0), self._default_scroll(1)]
        path = MAPS_DIR / f"{self.base}.mfo"
        if not path.exists():
            return out
        for line in path.read_text(encoding="cp949", errors="replace").splitlines():
            m = re.match(r"\s*scroll\s+(\d+)\s*=\s*(.+)", line)
            if not m:
                continue
            L = int(m.group(1))
            try:
                v = [int(t.strip(), 0) for t in m.group(2).split("//")[0].split(",")]
            except ValueError:
                continue
            if L > 1 or len(v) < 10:
                continue
            s16 = lambda x: x - (1 << 32) if x >= 0x80000000 else x
            out[L] = {"half": (s16(v[2]) >> 16, s16(v[3]) >> 16),
                      "wrap": (s16(v[4]), s16(v[5])),
                      "scale": (s16(v[6]) / 65536.0, s16(v[7]) / 65536.0),
                      "speed": (s16(v[8]) / 65536.0, s16(v[9]) / 65536.0)}
        return out

    def layer_center(self, L: int, cam_cx: float, cam_cy: float, t: int = 0) -> tuple[float, float]:
        """层 L 的画面中心 (像素) — FUN_004b439e: 镜头中心相对活动层中心的位移按比例缩放, 加上该层中心和自动卷动."""
        a, sl = self.scroll[self.active_layer], self.scroll[L]
        dx = cam_cx - a["half"][0] * TILE_W
        dy = cam_cy - a["half"][1] * TILE_H
        ox = sl["half"][0] * TILE_W + dx * (sl["scale"][0] / (a["scale"][0] or 1.0)) + sl["speed"][0] * t
        oy = sl["half"][1] * TILE_H + dy * (sl["scale"][1] / (a["scale"][1] or 1.0)) + sl["speed"][1] * t
        w, h = (self.w, self.h) if L == 0 else (self.w1, self.h1)
        if sl["wrap"][0] == -1 and w:
            ox %= w * TILE_W
        if sl["wrap"][1] == -1 and h:
            oy %= h * TILE_H
        return ox, oy

    def draw_layer(self, surface: pygame.Surface, L: int, cam_x: int, cam_y: int,
                   rows: tuple[int, int] | None = None) -> None:
        """只画第 L 层的瓦片, 原点 (cam_x, cam_y) 为该层自己的卷动原点 (视差时各层不同); 环绕层按模平铺."""
        grid = self.grid if L == 0 else self.grid1
        w, h = (self.w, self.h) if L == 0 else (self.w1, self.h1)
        if not grid or not w or not h:
            return
        sc = self.scroll[L]
        sw, sh = surface.get_size()
        x0, x1 = cam_x // TILE_W, (cam_x + sw) // TILE_W + 1
        y0, y1 = cam_y // TILE_H, (cam_y + sh) // TILE_H + 1
        if sc["wrap"][0] != -1:
            x0, x1 = max(0, x0), min(w, x1)
        if sc["wrap"][1] != -1:
            y0, y1 = max(0, y0), min(h, y1)
        if rows is not None:
            y0, y1 = max(y0, rows[0]), min(y1, rows[1])
        ts, cols, maxt = self.tileset, self.ts_cols, self.ts_cols * self.ts_rows
        for y in range(y0, y1):
            row = (y % h) * w
            for x in range(x0, x1):
                idx = grid[row + (x % w)]
                if idx >= maxt or (L == 1 and idx == 0):
                    continue
                if self.mat and idx < len(self.mat) and self.mat[idx] == MAT_EMPTY:
                    continue
                src = pygame.Rect((idx % cols) * TILE_W, (idx // cols) * TILE_H, TILE_W, TILE_H)
                surface.blit(ts, (x * TILE_W - cam_x, y * TILE_H - cam_y), src)

    # ---- 查询 ----
    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def tile_index(self, x: int, y: int) -> int:
        return self.grid[y * self.w + x]

    def flag(self, x: int, y: int) -> int:
        """旧接口: 属性高 16 位 (type + 4*level)."""
        return self.attr[y * self.w + x] >> 16

    def cell(self, x: int, y: int, layer: int = 0) -> int:
        cells = self.cells1 if (layer and self._layer1) else self.cells
        return cells[y * self.w + x]

    def tail_at(self, x: int, y: int) -> tuple[int, int]:
        return self.tail[y * self.w + x]

    def event_at(self, x: int, y: int) -> tuple[int, int, int] | None:
        """(事件类型, jmp 下标, 朝向) —— 第 0 层 cell 的 bit19..28; 无事件 → None."""
        v = self.cells_active[y * self.w + x]
        kind = (v >> 19) & 3
        if not kind:
            return None
        return kind, (v >> 21) & 0x1F, (v >> 26) & 7

    def _cells(self, layer: int | None) -> list[int]:
        if layer is None:
            return self.cells_active
        return self.cells1 if (layer == 1 and self._layer1) else self.cells

    def layer_at(self, x: int, y: int) -> int:
        """某格该站在哪一层: 有 pcpos 记录用它的 z, 否则默认层 (两层都可站时取默认层)."""
        for (px, py, z) in self.pcpos:
            if (px, py) == (x, y):
                return 1 if (z == 1 and self._layer1) else 0
        if not self.passable(x, y, self.layer) and self._layer1 and self.passable(x, y, 1 - self.layer):
            return 1 - self.layer
        return self.layer

    def passable(self, x: int, y: int, layer: int | None = None) -> bool:
        """可站 = 在图内且该层该格不实心 (bit9). layer=None → 默认层."""
        if not self.in_bounds(x, y):
            return False
        return not (self._cells(layer)[y * self.w + x] & CELL_SOLID)

    def step(self, x: int, y: int, dx: int, dy: int, layer: int | None = None) -> tuple[bool, int]:
        """从 (x,y) 朝 (dx,dy) 走一步 → (能否走, 走完所在层). 见 move()."""
        ok, nz, _nx, _ny = self.move(x, y, dx, dy, layer)
        return ok, nz

    def move(self, x: int, y: int, dx: int, dy: int, layer: int | None = None
             ) -> tuple[bool, int, int, int]:
        """原版玩家走一步 (FUN_004b4f56 + FUN_0049e2b5) → (能否走, 新层, 新 x, 新 y).
        · 目标格实心 / 本格该方向出边被挡 → 不能走
        · 目标格是坡口 (bit12) → 按朝向切层
        · 本格 bit17 (崖梯) 且 (无 bit10 或 朝向匹配) 且 下一格实心、再下一格可站 → 跨 2 格
        · 本格属性下标 0x32..0x3B (斜梯): 左右移动变成斜向 (见 _DIAG)"""
        if layer is None:
            layer = self.layer
        if layer == 1 and not self._layer1:          # 单层图没有第 1 层: 一律按第 0 层算
            layer = 0
        d = DIR_OF_DELTA.get((dx, dy))
        cells = self._cells(layer)
        cur = cells[y * self.w + x] if self.in_bounds(x, y) else 0
        if d is not None and (cur >> CELL_EDGE_SHIFT) & 0xF & (1 << d):
            return False, layer, x, y
        if d is not None and self.in_bounds(x, y):
            idx = self.attr[y * self.w + x] & 0xFFFF if layer == 0 else self.attr1[y * self.w + x] & 0xFFFF
            for lo, hi, dd, ddy, code in _DIAG:
                if dd == d and lo <= idx <= hi:
                    nx, ny = x + dx, y + ddy
                    nl = layer
                    if not self.passable(nx, ny, layer):
                        # 斜梯落点在本层实心 → 原版标 flag 4 直接换层 (另一层可站才走)
                        if not (self._layer1 and self.passable(nx, ny, 1 - layer)):
                            return False, layer, x, y
                        nl = 1 - layer
                    return True, self._ramp_layer(nx, ny, code, nl), nx, ny
            if cur & CELL_STAIR and (not cur & CELL_STAIR_DIRECTED or ((cur >> 26) & 7) == d):
                x1, y1, x2, y2 = x + dx, y + dy, x + 2 * dx, y + 2 * dy
                if (self.in_bounds(x1, y1) and cells[y1 * self.w + x1] & CELL_SOLID
                        and self.passable(x2, y2, layer)):
                    return True, layer, x2, y2
        nx, ny = x + dx, y + dy
        if not self.passable(nx, ny, layer):
            return False, layer, x, y
        if d is not None:
            layer = self._ramp_layer(nx, ny, d, layer)
        return True, layer, nx, ny

    def _ramp_layer(self, x: int, y: int, code: int, layer: int) -> int:
        """进入 (x,y) 时若它是坡口 (bit12): 顺着坡的朝向 (bit26..28) 走 → 第 1 层, 逆向 → 第 0 层."""
        if not self._layer1:
            return layer
        tgt = self._cells(layer)[y * self.w + x]
        if not tgt & CELL_RAMP:
            return layer
        ramp_dir = (tgt >> 26) & 7
        if code == ramp_dir:
            return 1
        if code == OPPOSITE.get(ramp_dir, -1):
            return 0
        return layer

    def can_move(self, x: int, y: int, dx: int, dy: int, layer: int | None = None) -> bool:
        return self.step(x, y, dx, dy, layer)[0]

    def start_pos(self) -> tuple[int, int]:
        """玩家起始格: 优先 .mfo pcpos[0], 否则地图中心最近的可通行格."""
        for (px, py, z) in self.pcpos:
            if self.passable(px, py, 1 if z == 1 else 0):
                return (px, py)
        cx, cy = self.w // 2, self.h // 2
        best: tuple[int, int] | None = None
        best_d = 10 ** 9
        for y in range(self.h):
            for x in range(self.w):
                if self.passable(x, y):
                    d = abs(x - cx) + abs(y - cy)
                    if d < best_d:
                        best_d, best = d, (x, y)
        return best or (1, 1)

    def obstacles(self) -> set[tuple[int, int]]:
        return {(x, y) for y in range(self.h) for x in range(self.w)
                if not self.passable(x, y)}

    # ---- BattleScene / WorldMapScene 地形提供者接口 ----
    def build_battle_map(self) -> BattleMap:
        bm = BattleMap(self.w, self.h)
        bm.obstacles |= self.obstacles()
        return bm

    def _camera_offset(self) -> tuple[int, int]:
        return (max(0, (self.w * TILE_W) // 2 - 400),
                max(0, (self.h * TILE_H) // 2 - 300))

    # ---- 渲染 ----
    def _visible_range(self, surface: pygame.Surface, cam_x: int, cam_y: int,
                       rows: tuple[int, int] | None) -> tuple[int, int, int, int]:
        sw, sh = surface.get_size()
        x0 = max(0, cam_x // TILE_W)
        y0 = max(0, cam_y // TILE_H)
        x1 = min(self.w, (cam_x + sw) // TILE_W + 1)
        y1 = min(self.h, (cam_y + sh) // TILE_H + 1)
        if rows is not None:
            y0, y1 = max(y0, rows[0]), min(y1, rows[1])
        return x0, y0, x1, y1

    def _blit_layer(self, surface, cam_x, cam_y, rng, grid, ts, cols, rows, mat, want,
                    skip_zero: bool = False) -> None:
        x0, y0, x1, y1 = rng
        maxt = cols * rows
        for y in range(y0, y1):
            row = y * self.w
            for x in range(x0, x1):
                idx = grid[row + x]
                if idx >= maxt or (skip_zero and idx == 0):
                    continue
                m = mat[idx] if mat and idx < len(mat) else MAT_UNDER
                if m == MAT_EMPTY or (want is not None and m != want):
                    continue
                src = pygame.Rect((idx % cols) * TILE_W, (idx // cols) * TILE_H, TILE_W, TILE_H)
                surface.blit(ts, (x * TILE_W - cam_x, y * TILE_H - cam_y), src)

    def draw_terrain(self, surface: pygame.Surface, cam_x: int, cam_y: int,
                     rows: tuple[int, int] | None = None) -> None:
        """画角色**下面**的东西: 地面层全部 + 高层里 .mat 标 0x200 的瓦片.
        `rows=(y0, y1)` 只画这些行 —— 供场景做 2.5D 按行交错绘制."""
        rng = self._visible_range(surface, cam_x, cam_y, rows)
        self._blit_layer(surface, cam_x, cam_y, rng, self.grid, self.tileset,
                         self.ts_cols, self.ts_rows, self.mat, None)
        if self._layer1:
            # 高处层的瓦片用同一张 P 图集 (0 = 空格)
            self._blit_layer(surface, cam_x, cam_y, rng, self.grid1, self.tileset,
                             self.ts_cols, self.ts_rows, self.mat, None, skip_zero=True)

    def draw_tall(self, surface: pygame.Surface, cam_x: int, cam_y: int, row: int,
                  layer: int | None = None) -> None:
        """把基线落在 `row` 行的高物件瓦片再盖一遍 (原版 FUN_004b8aa9 的 "瓦片压精灵" 规则):
        瓦片 (x, y, level) 的基线 = y + level 行; 场景在画完该行精灵后调用 → 基线以北的角色被挡住.
        `layer` = 角色所在层 (决定用哪一层的属性判高物件)."""
        if layer is None:
            layer = self.layer
        L = 1 if (layer == 1 and self._layer1) else 0
        grid = self.grid1 if (L == 1 and self._layer1_has_tiles) else self.grid
        for (x, y) in self._tall[L].get(row, ()):
            idx = grid[y * self.w + x]
            if idx >= self.ts_cols * self.ts_rows:
                continue
            if self.mat and idx < len(self.mat) and self.mat[idx] == MAT_EMPTY:
                continue
            sx, sy = x * TILE_W - cam_x, y * TILE_H - cam_y
            if sx < -TILE_W or sy < -TILE_H or sx > surface.get_width() or sy > surface.get_height():
                continue
            # 有镂空版 (S 图集同号格, S.mat != 0) 就用镂空版: 树冠/屋檐只盖物件像素, 不盖地面
            if (self.tileset_s is not None and self.mat_s and idx < len(self.mat_s)
                    and self.mat_s[idx] != MAT_EMPTY and idx < self.ts_cols_s * self.ts_rows_s):
                ts, cols = self.tileset_s, self.ts_cols_s
            else:
                ts, cols = self.tileset, self.ts_cols
            src = pygame.Rect((idx % cols) * TILE_W, (idx // cols) * TILE_H, TILE_W, TILE_H)
            surface.blit(ts, (sx, sy), src)

    def draw_overlay(self, surface: pygame.Surface, cam_x: int, cam_y: int,
                     rows: tuple[int, int] | None = None) -> None:
        """兼容旧接口: 压精灵的逻辑已全部在 draw_tall 里, 这里不再画东西."""
        return


_DOORS: dict[int, dict] | None = None


def door_table() -> dict[int, dict]:
    """exe 门表 (tools/extract_doors): id → {map, x, y, w, h, open, closed}."""
    global _DOORS
    if _DOORS is None:
        path = ROOT / "assets" / "door_table.json"
        _DOORS = {}
        if path.exists():
            for r in json.loads(path.read_text(encoding="utf-8")):
                _DOORS[r["id"]] = r
    return _DOORS


def load(base: str) -> RealMap:
    """按名加载并缓存一张地图. 缺资源抛 FileNotFoundError."""
    if not is_available(base):
        raise FileNotFoundError(f"地图不存在: {base}")
    if base not in _inst_cache:
        _inst_cache[base] = RealMap(base)
    return _inst_cache[base]
