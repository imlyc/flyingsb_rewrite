"""原版真实地图 (.map + tileset .pcx) 加载 / 渲染 / 通行判定.

地图格式 (逆向自 mapset.dll 资源; 见 tools/extract_maps.py 顶部注释):
  .map = 120 个 u32 头部 + 2 张 W×H 的 u32 网格
    u[6]=宽W, u[7]=高H, u[8]/u[9]=tileset 网格列/行
    网格 A = 可视瓦片索引 (行优先); 网格 B = 属性/覆盖层 (flag 非 0 = 墙/障碍)
    尾部    = 可选 8 字节/格的 object/event 数据 (城镇/迷宫才有)
  .mfo = 文本元数据 (mapname / pcpos)
  .pcx = tileset 图集, 单格 64×48 (= core.sprites.base.TILE_W/TILE_H)

本类同时实现 BattleScene / WorldMapScene 期望的 "地形提供者" 接口:
  w / h / draw_terrain(surface, cam_x, cam_y) / _camera_offset() / passable(x, y)
  build_battle_map()

通行规则 (实测校准):
  不可通行 = 出界 OR "空" 瓦片 (色键/纯黑/蓝水) OR 属性层 flag 不在 WALK_FLAGS 内
  flag = 网格B 高 16 位 (低 16 位是**屋顶覆盖层**的瓦片号, 与通行无关):
    0  = 地面 (可走)
    3  = 门 / 门槛 / 台阶      —— 可走
    7  = 楼梯踏步 / 低矮可跨结构 —— 可走
    11 / 13 / 15 / 19 / 23 = 墙体·屋顶·树篱·家具 (实心)
  实证 (2026-09-28): 雅士兰 TAS0___P 右下拱门旁那道斜向石阶, 踏步格 flag=7 (最下一级 3),
  周围灰石墙 flag=11/15; 五指村的木梯是 flag=0; 房子**立面那一行本身是 flag=0**
  (玩家要走到门口), 屋顶/屋檐才是 11/13/15。此前只认 flag==0, 导致楼梯上不去。
  门的落点/触发仍由上层 WorldMapScene 按传送点坐标处理 (见 passable_at)。
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pygame

from core.battle.data import BattleMap
from core.sprites.base import TILE_W, TILE_H

MAPS_DIR = Path(__file__).resolve().parent.parent / "assets" / "maps"
HEADER_U32 = 120

# 竞技场默认用的地图 (TARA = 竞技场 hall)
DEFAULT_ARENA_MAP = "TARA_00P"
# 世界地图默认用的地图 (T_LOC0 = 东海之滨)
DEFAULT_WORLD_MAP = "T_LOC0_P"

# 地图外框厚度 (原版这些图的黑边; 近黑瓦片只在这里判空, 见 passable)
FRAME = 1

# 覆盖层里确认画不对的瓦片 (按图集): TFI0 的 4/5/6/7/9 = **45° 过渡三角瓦片**
# (土/草、石/草的斜接角, 共 65 格, 分布在房门口/屋角/路边), 100 = 底行 y=39 的房墙斜角条
# (4 格连续同瓦, 疑似截断房屋)。原版对过渡瓦做翻转/混合处理 (机制未逆向), 直接画就是
# 散落三角碎片 + 底边乱条 (2026-09-29 用户两次截图) → 跳过不画 (宁缺勿错, 已两次验证)。
_OVERLAY_TILE_SKIP: dict[str, frozenset[int]] = {"TFI0___P": frozenset({4, 5, 6, 7, 9, 100})}

_VOID_EXEMPT: dict[str, frozenset[int]] | None = None


_WALK_OVER: dict[str, frozenset[int]] | None = None


def _walk_over_tiles() -> dict[str, frozenset[int]]:
    """`assets/void_tiles.json` 的 `walk_over`: **原版其实能跨过去的结构瓦片**白名单。

    有些门洞/门槛在图里画成结构图样 (flag type3 level≥2, 属性层与墙同码)，提取数据分不出来。
    这张表由 `tools/calibrate_void_tiles.py` 推出来: 取其"挡住权威宝箱唯一通路"的瓦片号
    (并加安全阀: 单个瓦片全游戏放开 > 200 格就丢弃, 防把普通墙当闸门)。
    与手写的 `_WALK_OVER_TILES` 同机制, 只是数据驱动。
    """
    global _WALK_OVER
    if _WALK_OVER is None:
        _WALK_OVER = {}
        try:
            p = Path(__file__).resolve().parent.parent / "assets" / "void_tiles.json"
            data = json.loads(p.read_text(encoding="utf-8"))
            _WALK_OVER = {k: frozenset(v) for k, v in (data.get("walk_over") or {}).items()}
        except Exception:
            pass
    return _WALK_OVER


def _void_exemptions() -> dict[str, frozenset[int]]:
    """`assets/void_tiles.json`: **被原版数据当"可站格"用过的瓦片**, 一律从空瓦片集合里豁免。

    由 `tools/calibrate_void_tiles.py` 生成 —— 证据 = 瓦片出现在 door / spawn / .mfo pcpos /
    权威宝箱表的格子上 (这些格原版必须能站)。修掉"启发式把真地板当空"导致的
    门/宝箱走不到 (实测: 门不可达 160 -> 72, 宝箱可达 79.7% -> 87.8%)。
    """
    global _VOID_EXEMPT
    if _VOID_EXEMPT is None:
        _VOID_EXEMPT = {}
        try:
            p = Path(__file__).resolve().parent.parent / "assets" / "void_tiles.json"
            data = json.loads(p.read_text(encoding="utf-8"))
            _VOID_EXEMPT = {k: frozenset(v) for k, v in (data.get("exempt") or {}).items()}
        except Exception:      # 缺文件/坏文件 -> 退化为纯启发式, 不影响运行
            pass
    return _VOID_EXEMPT

# 属性层 (网格B) 高 16 位 = **type + 4 * level** (type 0..3, level 0..7; 全局取值全落在此式上):
#   type 0=地面/地板   1=地面系特殊格   2=地面系特殊格   3=结构(墙/屋顶/台阶/桥), level = 抬高高度
# 通行按 type/level 组合判 (2026-09-29 用原版自己的数据校准):
#   type != 3                              -> 可走 (含 2/5/6/9/10/13/14)
#   type == 3 且 level <= 1 (即 flag 3/7)  -> 可走 (门·门槛 / 台阶·矮梯)
#   type == 3 且 level >= 2 (11,15,19,23,27,31) -> 实心
# 实证 (权威全宝箱表 1022 箱 + 486 个官方出生点):
#   · 排除门格后, 官方出生点的 flag 全落在 {0, 3} —— 没有任何一个在 11/13/15 上 (门格由传送放行);
#   · 宝箱落在 flag 0(719) / 11(99) / 15(89) / 7(47) / 13(31) / 3(24) / 5(6) / 19(4) / 9(2) / 27(1);
#   · 其中 **flag=13 (type1 level3) 上有 46 个官方出生点 + 31 个宝箱** —— 旧规则只认 {0,3,7} 会把它当墙 ✗;
#   · BFS 连通性对比 (从各图出生点出发, 宝箱格或紧邻格可达算覆盖):
#       旧 {0,3,7} = 90.1%   新 type/level = 91.3%  (101 -> 89 个不可达)
WALK_FLAGS = frozenset({0, 3, 7})   # 保留：{0,3,7} 的等价集合, 供老代码/测试引用


def flag_walkable(f: int) -> bool:
    """属性层高 16 位 -> 是否可走 (type/level 规则, 见上)."""
    return (f & 3) != 3 or (f >> 2) <= 1

# 抬高的"桥 / 楼梯"瓦片白名单: 键 = **图集名**, 值 = 该图集里属于桥·梯的瓦片号。
# 这类格在属性层与屋顶/墙同码 (type=3, level>=2), 靠码值分不出来; 但同一图集内**瓦片号含义固定**,
# 所以按美术白名单放行 (玩家能踩上台阶/桥)。实证: 五指村 TFI0___P 那道带栏杆的木梯/桥(过石墙)。
_WALK_OVER_TILES: dict[str, frozenset[int]] = {
    "TFI0___P": frozenset({16, 17, 36, 37,                              # 梯顶
                           56, 57, 76, 77, 38, 39, 58, 59, 78, 79, 92, 75}),  # 梯身
}

# 按**地图**放行的格子: 屋内隔墙上的门 (拱形木门) 通向另一侧, 但门后的格子属性层标成了墙。
# 数据里墙与地面同码, 只能按位置特判。键 = 地图名。
# 小森林 TBB0 的宝箱在两个树墙凹槽里, 原版有**两条林间隧道**通向它们 —— 即从清洁区穿 7 格
# 树墙直下到凹槽 (x=5 与 x=17 两列, 行 11..17)。原版碰撞是**逐格**的 (树墙里有可穿的具体格子),
# 我们没提取到原版碰撞表, 这里用最短穿墙路径算出的具体格精确模拟。
# 2026-09-29 用户三轮实测定稿: ①不能整片可走 ("大多数树穿不了") ②不能贴地图外框绕
# ③"有的树可以穿" = 这两条隧道。✅ 凹槽宝箱连通, 全图可走 138/621 (树冠全放开 621 被否决)。
_EXTRA_WALKABLE: dict[str, set[tuple[int, int]]] = {
    "TFI0_04P": {(4, 9), (4, 8)},        # (4,10) 的门 → 通向里面卧室
    "TBB0___P": {
        (5, 11), (5, 12), (5, 13), (5, 14), (5, 15), (5, 16), (5, 17),
        (17, 11), (17, 12), (17, 13), (17, 14), (17, 15), (17, 16), (17, 17),
    },
}

# 按**图集**封禁的"假可走"瓦片: 属性层 flag=3/7 (门/台阶) 但美术是纯物体 (树桩/木桶堆/柴堆/
# 水桶/原木/房墙), 原版靠 tile 级碰撞表挡人 (提取数据里分不出, 见 project_map_collision.md)。
# 2026-09-29 用户实测: 五指村能站上木桶堆/大原木/房墙。加进前先跑使用统计 (门/箱/出生点零冲突)。
_SOLID_TILES: dict[str, frozenset[int]] = {
    "TFI0___P": frozenset({
        388, 329, 349,            # 木桶堆/盘圈 (宝箱台下与柴堆间)
        327, 347, 328, 348,       # 斧头树桩 / 大树桩 / 柴堆
        369, 260, 276,            # 水桶 / 立式原木
        261, 280, 281, 341,       # 房子石墙·窗 (flag 3/7 但显然是墙; 门在 (7,30) 传送点, 不受影响)
    }),
}

_inst_cache: dict[str, "RealMap"] = {}
_ts_index: dict[tuple[int, int], list[str]] | None = None


# ---------------- 资源探测 ----------------
def maps_available() -> bool:
    return MAPS_DIR.is_dir() and any(MAPS_DIR.glob("*.map"))


def list_maps() -> list[str]:
    if not MAPS_DIR.is_dir():
        return []
    return sorted(p.stem for p in MAPS_DIR.glob("*.map"))


def is_available(base: str) -> bool:
    return (MAPS_DIR / f"{base}.map").exists()


def _image_size(path: Path) -> tuple[int, int]:
    return pygame.image.load(str(path)).get_size()


def _tileset_index() -> dict[tuple[int, int], list[str]]:
    """所有 P 面 tileset 按网格尺寸 (cols, rows) 建索引."""
    global _ts_index
    if _ts_index is None:
        idx: dict[tuple[int, int], list[str]] = {}
        if MAPS_DIR.is_dir():
            for p in MAPS_DIR.glob("*.pcx"):
                if not p.stem.endswith("P"):
                    continue
                w, h = _image_size(p)
                idx.setdefault((w // TILE_W, h // TILE_H), []).append(p.stem)
            for v in idx.values():
                v.sort()
        _ts_index = idx
    return _ts_index


def _load_tileset_surface(name: str) -> pygame.Surface:
    path = MAPS_DIR / f"{name}.pcx"
    surf = pygame.image.load(str(path))
    if pygame.display.get_surface() is not None:
        surf = surf.convert()
    return surf


# ---------------- RealMap ----------------
class RealMap:
    """一张原版地图 (可视层 + 通行). 兼作 BattleScene 的地形提供者."""

    def __init__(self, base: str) -> None:
        self.base = base
        raw = (MAPS_DIR / f"{base}.map").read_bytes()
        u = list(struct.unpack("<%dI" % (len(raw) // 4), raw[: len(raw) // 4 * 4]))
        self.w, self.h = u[6], u[7]
        self.ts_cols, self.ts_rows = u[8], u[9]
        if len(u) < HEADER_U32 + 2 * self.w * self.h:
            raise ValueError(f"{base}.map 尺寸不符 ({len(u)} u32, 期望 >= "
                             f"{HEADER_U32 + 2 * self.w * self.h})")
        cells = self.w * self.h
        self.grid = u[HEADER_U32:HEADER_U32 + cells]              # 可视瓦片
        self.attr = u[HEADER_U32 + cells:HEADER_U32 + 2 * cells]  # 属性/覆盖层

        # ---- 第三层: .map 文件尾部通常有 8 字节/格的 object/event 数据 ----
        # 对城镇/迷宫这是宝箱/NPC/建筑对象层; 目前只用它做通行辅助,
        # 真正的对象语义 (哪些对象阻挡、宝箱内容) 仍需 exe/数据表逆向.
        self.tail: list[tuple[int, int]] = [(0, 0)] * cells
        self._parse_tail(raw, cells)

        # tileset: 同名优先, 否则同页/尺寸匹配 (声明尺寸 u[8]/u[9] 只用来"找"图集)
        self.ts_name = self._resolve_tileset()
        self.tileset = _load_tileset_surface(self.ts_name)
        # ⚠ 网格几何必须以**图集实际尺寸**为准, 不能用地图声明的 u[8]/u[9]:
        #   声明值常是脏数据 (如 TFI0_04P 写 16x21, 而它实际用的 TFI0_00P 是 16x16),
        #   按声明算 cell_h = 768//21 = 36 (应为 48) → 每格取错源矩形 → **整图花屏**(横条纹/盘子)。
        tw, th = self.tileset.get_size()
        self.ts_cols, self.ts_rows = tw // TILE_W, th // TILE_H
        self.cell_w, self.cell_h = TILE_W, TILE_H
        self._colorkey, self._water = self._detect_void_tiles()
        self._black = self._detect_black_tiles()        # 近黑瓦片 (外框判空用, 阈值严)
        self._blank = self._detect_blank_tiles()        # 空块瓦片 (渲染跳过用, 阈值宽)
        # ⚠ 近黑**不并入** _void: 室内图用近黑瓦片画暗门/阴影/暗地板, 老的"近黑=空"会把
        #   玩家挡在房内暗处、也堵住部分门口 (全游戏 139/1146 个门走不到)。实测放行后仅 92。
        self._void = self._colorkey | self._water
        # 渲染用的原始空块集合: 豁免**只放宽通行**, 不改渲染 —— 免得把色键/水画出来(旧行为最稳)
        self._void_render = self._void
        _ex = _void_exemptions().get(self.ts_name)           # 原版数据校准过的豁免瓦片
        if _ex:
            self._void = self._void - _ex
            self._black = self._black - _ex
        self._walk_over = _walk_over_tiles().get(self.ts_name, frozenset())   # 门洞/门槛白名单
        self.pcpos = self._read_pcpos()

    # ---- 资源解析 ----
    def _resolve_tileset(self) -> str:
        """找出本图该用的 tileset (.pcx).

        ⚠ mapset.dll 里 **只有 192 个 PCX 却有 487 张 MAP** —— 同一"页"(前 5 字符, 如
        `TFI0_`)的屋子共用一张图集。且部分 .map 头部的 `u[8]/u[9]`(声明尺寸) 是**脏数据**
        (如 `TFI0_04P` 声明 16x21, 但它实际只用到瓦片号 ≤255 = 16x16 就够),
        若按尺寸匹配会挑到毫不相干的图集 (曾把雅士兰的 `TAS0_01P` 配给五指村的屋子 →
        整个地板变成盘子/碗)。故:
          1) 同名 .pcx 直接用;
          2) 否则**先按"同页前缀"挑**, 且该图集必须能覆盖本图用到的最大瓦片号;
          3) 再不行才退回按声明尺寸匹配 (旧行为), 最后兜底任意能覆盖的图集。
        """
        if (MAPS_DIR / f"{self.base}.pcx").exists() and self.base.endswith("P"):
            return self.base
        need = (max(self.grid) + 1) if self.grid else 1     # 需覆盖的瓦片数
        page = self.base[:5]
        pool = _tileset_index()                             # (cols, rows) -> [name]

        # 1) 同页前缀 + 能覆盖瓦片号 (同页里选瓦片数最接近 need 的, 避免撑大图集后取错区域)
        same_page: list[tuple[str, int]] = []
        for (c, r), names in pool.items():
            if c * r < need:
                continue
            for n in names:
                if n[:5] == page:
                    same_page.append((n, c * r))
        if same_page:
            same_page.sort(key=lambda t: (t[1] - need, t[0]))
            return same_page[0][0]

        # 2) 退回按声明尺寸匹配 (同页优先)
        cands = pool.get((self.ts_cols, self.ts_rows))
        if cands:
            pick = next((c for c in cands if c[:5] == page), None)
            return pick or cands[0]

        # 3) 任意能覆盖 need 的图集 (选最接近的)
        cover = [(n, c * r) for (c, r), names in pool.items() if c * r >= need for n in names]
        if cover:
            cover.sort(key=lambda t: (t[1] - need, t[0]))
            return cover[0][0]
        if not pool:
            raise FileNotFoundError(f"{self.base}: 没有任何 tileset")
        return sorted(pool.values())[0][0]

    def _detect_void_tiles(self) -> tuple[set[int], set[int]]:
        """(色键瓦片, 水域瓦片). 两者**任何位置**都不可走 (防止人站色键/水里)."""
        colorkey: set[int] = set()
        water: set[int] = set()
        n = self.ts_cols * self.ts_rows
        for i in range(n):
            cw, ch = self.cell_w, self.cell_h
            x0, y0 = (i % self.ts_cols) * cw, (i // self.ts_cols) * ch
            pts = [(x0 + cw // 4, y0 + ch // 4), (x0 + 3 * cw // 4, y0 + ch // 4),
                   (x0 + cw // 4, y0 + 3 * ch // 4), (x0 + 3 * cw // 4, y0 + 3 * ch // 4),
                   (x0 + cw // 2, y0 + ch // 2)]
            try:
                cols = [self.tileset.get_at(p)[:3] for p in pts]
            except IndexError:
                continue
            uniform = cols[0] == cols[1] == cols[2] == cols[3] == cols[4]
            r, g, b = cols[0]
            ar = sum(c[0] for c in cols) / len(cols)
            ag = sum(c[1] for c in cols) / len(cols)
            ab = sum(c[2] for c in cols) / len(cols)
            if uniform and r > 200 and g < 80 and b > 200:
                colorkey.add(i)                   # 品红 = 色键
            elif ab - ar > 40 and ab - ag > 25 and ab > 90:
                water.add(i)                      # 蓝色水域
        return colorkey, water

    def _detect_black_tiles(self) -> set[int]:
        """均匀近黑瓦片 (纯黑/近黑). 只在**地图外框**上判空, 见 `passable`.

        室内图也拿这类瓦片画**暗门/门洞/阴影/暗色地板** —— 一律判空会把玩家挡在房内暗处
        (2026-09-28 用户实测: "这块是个门/阴影, 应该能进去, 却被挡住")。
        """
        black: set[int] = set()
        n = self.ts_cols * self.ts_rows
        for i in range(n):
            cw, ch = self.cell_w, self.cell_h
            x0, y0 = (i % self.ts_cols) * cw, (i // self.ts_cols) * ch
            pts = [(x0 + cw // 4, y0 + ch // 4), (x0 + 3 * cw // 4, y0 + ch // 4),
                   (x0 + cw // 4, y0 + 3 * ch // 4), (x0 + 3 * cw // 4, y0 + 3 * ch // 4),
                   (x0 + cw // 2, y0 + ch // 2)]
            try:
                cols = [self.tileset.get_at(p)[:3] for p in pts]
            except IndexError:
                continue
            if all(c == cols[0] for c in cols) and max(cols[0]) < 12:
                black.add(i)
        return black

    def _detect_blank_tiles(self) -> set[int]:
        """"空块"瓦片 = **整体很暗**的瓦片 (纯黑/近黑/深灰, 实测 (0,0,0)/(15,15,15)/带杂点) ——
        **只用于渲染跳过** (覆盖层里的空块画出来就是满地图黑框/黑条)。

        ⚠ 别并进 `_black`: `_black` 参与通行(外框判空), 放宽阈值会多挡门 (实测)。
        用**密集采样 + 平均亮度**判定 (只按 5 点会漏掉"暗但不完全均匀"的瓦片)。
        """
        blank: set[int] = set()
        n = self.ts_cols * self.ts_rows
        cw, ch = self.cell_w, self.cell_h
        for i in range(n):
            x0, y0 = (i % self.ts_cols) * cw, (i // self.ts_cols) * ch
            tot = 0
            cnt = 0
            for gy in range(6):
                for gx in range(8):
                    p = (x0 + (gx * 2 + 1) * cw // 16, y0 + (gy * 2 + 1) * ch // 12)
                    try:
                        r, g, b = self.tileset.get_at(p)[:3]
                    except IndexError:
                        continue
                    tot += max(r, g, b)
                    cnt += 1
            if cnt and tot / cnt < 46:          # 平均亮度很低 → 空块
                blank.add(i)
        return blank

    def _in_frame(self, x: int, y: int) -> bool:
        """是否在地图外框 (原版这些图的黑边; 厚度 FRAME)."""
        return (x < FRAME or y < FRAME
                or x >= self.w - FRAME or y >= self.h - FRAME)

    def _read_pcpos(self) -> list[tuple[int, int]]:
        p = MAPS_DIR / f"{self.base}.mfo"
        out: list[tuple[int, int]] = []
        if not p.exists():
            return out
        try:
            text = p.read_bytes().decode("gbk", "replace")
        except Exception:
            return out
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("pcpos"):
                rhs = s.split("=", 1)[1].split("//")[0]
                nums = [int(x) for x in rhs.replace(",", " ").split() if x.lstrip("-").isdigit()]
                if len(nums) >= 2:
                    out.append((nums[0], nums[1]))
        return out

    def _parse_tail(self, raw: bytes, cells: int) -> None:
        """解析 .map 尾部的 8 字节/格 object/event 层."""
        header_bytes = HEADER_U32 * 4 + 2 * cells * 4
        tail_len = len(raw) - header_bytes
        if tail_len < cells * 8:
            return
        for i in range(cells):
            a, b = struct.unpack_from("<II", raw, header_bytes + i * 8)
            self.tail[i] = (a, b)

    # ---- 查询 ----
    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def tile_index(self, x: int, y: int) -> int:
        return self.grid[y * self.w + x]

    def flag(self, x: int, y: int) -> int:
        return self.attr[y * self.w + x] >> 16

    def tail_at(self, x: int, y: int) -> tuple[int, int]:
        return self.tail[y * self.w + x]

    def passable(self, x: int, y: int) -> bool:
        """可走 = flag 通过 type/level 规则 (见 WALK_FLAGS 上方注释) 且不是空/色键/近黑瓦片; 另有桥·梯白名单.

        ⚠ 曾经的尝试 (2026-09-28, 已回退): 用 "网格B 低16位(覆盖层)!=0 即视为有墙/家具" 来挡
          "走上墙"。**实测该规则会让 417/1146 个传送门走不到** (覆盖层也压在城镇地板/门口上),
          故**不可用**。想区分"墙 vs 地面"仍需原版的按瓦片碰撞表 (未提取到), 只能按瓦片白名单特判。
        """
        if not self.in_bounds(x, y):
            return False
        i = y * self.w + x
        idx = self.grid[i]
        if idx in self._void:                                # 色键/水域: 哪都不能走
            return False
        if idx in self._black and self._in_frame(x, y):      # 地图外框黑边 (别走出地图)
            return False
        if idx in _SOLID_TILES.get(self.ts_name, ()):        # 假可走物体 (树桩/木桶/房墙): 必挡
            return False
        if idx in _WALK_OVER_TILES.get(self.ts_name, ()):    # 可踩的桥/梯 (手写白名单)
            return True
        if idx in self._walk_over:                           # 数据驱动的门洞/门槛白名单
            return True
        if (x, y) in _EXTRA_WALKABLE.get(self.base, ()):     # 按位置特判 (门洞/林间隧道等)
            return True
        return flag_walkable(self.attr[i] >> 16)             # type/level 规则

    def start_pos(self) -> tuple[int, int]:
        """玩家起始格: 优先 .mfo pcpos[0], 否则地图中心最近的可通行格."""
        for (px, py) in self.pcpos:
            if self.passable(px, py):
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

    def draw_overlay(self, surface: pygame.Surface, cam_x: int, cam_y: int,
                     rows: tuple[int, int] | None = None) -> None:
        """绘制**覆盖层 (网格B)**: 屋顶/雨棚/墙沿/房梁 等"上层"美术.

        原版 2.5D 画法: 这层要画在**角色之后** —— 角色走到建筑/墙后面会被正确遮挡
        (否则看起来像"站在墙上/墙上没有房梁挡人", 2026-09-28 用户实测反馈)。
        网格B 低 16 位 = 覆盖层瓦片号, 0 = 该格无上层。
        """
        # ⚠ 跨页回退图集 (如图集 TEV0___P 配给 TBB0___P) 不画覆盖层:
        #   覆盖层瓦片号在别人图集里对不上, 画出来是花斑 (2026-09-29 用户截图实测:
        #   小森林右缘一列沙色错块 + 中部散落斜切块)。曾试图放宽, 被实测否决 ——
        #   226 张跨页图宁可没有覆盖层 ("宁缺勿错", 二次验证)。
        if self.ts_name[:5] != self.base[:5]:
            return
        sw, sh = surface.get_size()
        x0 = max(0, cam_x // TILE_W)
        y0 = max(0, cam_y // TILE_H)
        x1 = min(self.w, (cam_x + sw) // TILE_W + 1)
        y1 = min(self.h, (cam_y + sh) // TILE_H + 1)
        if rows is not None:
            y0, y1 = max(y0, rows[0]), min(y1, rows[1])
        ts, tc, cw, ch = self.tileset, self.ts_cols, self.cell_w, self.cell_h
        maxt = self.ts_cols * self.ts_rows
        for y in range(y0, y1):
            row = y * self.w
            for x in range(x0, x1):
                idx = self.attr[row + x] & 0xFFFF
                if not idx or idx >= maxt:
                    continue
                if idx in self._void_render or idx in self._blank:
                    # 覆盖层里的"空块"(纯黑/近黑/色键) 不是美术, 画出来就是满地图黑框
                    # ⚠ 用 _void_render (豁免前的原始集合): 通行豁免不改变渲染行为
                    continue
                if idx in _OVERLAY_TILE_SKIP.get(self.ts_name, ()):
                    # 确认画不对的覆盖层瓦片 (三角过渡等, 原版带翻转/混合处理)
                    continue
                src = pygame.Rect((idx % tc) * cw, (idx // tc) * ch, cw, ch)
                surface.blit(ts, (x * TILE_W - cam_x, y * TILE_H - cam_y), src)

    def draw_terrain(self, surface: pygame.Surface, cam_x: int, cam_y: int,
                     rows: tuple[int, int] | None = None) -> None:
        """画底层 (网格A)。`rows=(y0, y1)` 只画这些行 —— 供场景做 2.5D 按行交错绘制。

        原版是"画到实体所在行 → 画实体 → 再画南边的行"，这样**南侧的桥板/墙沿会挡住角色**
        (2026-09-29 用户实测: 站在桥上时桥板应遮住角色)。整张图一次性画完就做不到这点。
        """
        sw, sh = surface.get_size()
        x0 = max(0, cam_x // TILE_W)
        y0 = max(0, cam_y // TILE_H)
        x1 = min(self.w, (cam_x + sw) // TILE_W + 1)
        y1 = min(self.h, (cam_y + sh) // TILE_H + 1)
        if rows is not None:
            y0, y1 = max(y0, rows[0]), min(y1, rows[1])
        ts, tc, cw, ch = self.tileset, self.ts_cols, self.cell_w, self.cell_h
        maxt = self.ts_cols * self.ts_rows
        for y in range(y0, y1):
            row = y * self.w
            for x in range(x0, x1):
                idx = self.grid[row + x]
                if idx >= maxt:
                    continue
                if idx in self._colorkey:
                    # 真·色键瓦片 = 透明 (原版此处露出底色/上一屏), 画出来就是品红块
                    continue
                src = pygame.Rect((idx % tc) * cw, (idx // tc) * ch, cw, ch)
                surface.blit(ts, (x * TILE_W - cam_x, y * TILE_H - cam_y), src)


def load(base: str) -> RealMap:
    """按名加载并缓存一张地图. 缺资源抛 FileNotFoundError."""
    if not is_available(base):
        raise FileNotFoundError(f"地图不存在: {base}")
    if base not in _inst_cache:
        _inst_cache[base] = RealMap(base)
    return _inst_cache[base]
