"""世界地图 (原版 M 键): LMAP00 手绘大地图 + exe 地点表 + 状态标记.

数据 (全部来自原版, 见 tools/extract_worldmap.py):
  · 地点表 44 条: FlyingSB.exe 0x14b41c, 步长 0x54 —— 名称(Big5)/坐标(LMAP00
    像素)/位置 ID (+36, 与 location_map.json 同一 ID 空间, 五指村=22、阿尔夏=348
    与已知枢纽吻合)。
  · 底图 LMAP00.bmp (2000x1600), 标记素材 LMAP_10.pcx
    (4 个红箭头光标 17x17 + 白/红/蓝 3 个状态圆点)。

原版行为: **去过的地点和新开的地图在大地图上显示**。复刻:
  白点 = 去过的 (visited, 存 save.world_visited, 与 chests_opened 同为内存态)
  红点 = 新解锁还没去过的 (闪烁 + 「新」)
  蓝点 = 未解锁 (仅占位, 不可选)
  红箭头 = 光标 (闪烁), 1:1 视口跟随光标, 右上角小地图总览。

解锁: 五指村(22)/雅士兰(10) 初始; 五行山(30/46) 需 LEFT_VILLAGE (与步行
传送门控 world_graph.gate_for 一致); 其余需 WUKONG_JOINED 或去过。
"""

from __future__ import annotations

import json
from pathlib import Path

import pygame

from scenes.base import Scene
from scenes.menu import load_chinese_font

ROOT = Path(__file__).resolve().parent.parent.parent
LMAP_IMG = ROOT / "assets" / "ui" / "LMAP00.bmp"
LMAP_SPR = ROOT / "assets" / "ui" / "LMAP_10.pcx"
WM_LOC = ROOT / "assets" / "worldmap_locations.json"

# 位置 ID → 初始/门控 (语义见模块 docstring)
INITIAL_IDS = {22, 10, 476}               # 五指村 / 雅士兰 / 小森林(序章前起始村)
FLAG_BY_ID = {30: "LEFT_VILLAGE", 46: "LEFT_VILLAGE"}   # 五行山南北
DEFAULT_FLAG = "WUKONG_JOINED"            # 其余地点的第 3 章门控

# LMAP_10.pcx 子贴图 (连接域实测: 见 _probe 输出 / memory)
ARROW_RECTS = [(0, 0, 17, 17), (20, 0, 17, 17), (40, 0, 17, 17), (60, 0, 17, 17)]
DOT_RECTS = {"visited": (0, 20, 8, 8), "new": (10, 20, 9, 9), "locked": (20, 20, 8, 8)}


def load_locations() -> list[dict]:
    """原版 44 条地点; 缺文件时返回空列表 (场景显示缺资源提示)."""
    if not WM_LOC.exists():
        return []
    data = json.loads(WM_LOC.read_text(encoding="utf-8"))
    return data.get("locations", [])


def load_markers() -> dict[str, pygame.Surface] | None:
    """从 LMAP_10.pcx 切出箭头/圆点 (黑底色键). 缺文件返回 None."""
    if not LMAP_SPR.exists():
        return None
    pygame.init()
    img = pygame.image.load(str(LMAP_SPR))
    try:
        sheet = img.convert()          # 需已 set_mode; 无显示窗口时回退原 surface
    except pygame.error:
        sheet = img
    sheet.set_colorkey((0, 0, 0))
    out: dict[str, pygame.Surface] = {}
    for i, r in enumerate(ARROW_RECTS):
        out[f"arrow{i}"] = sheet.subsurface(r).copy()
    for k, r in DOT_RECTS.items():
        out[k] = sheet.subsurface(r).copy()
    return out


class WorldAtlasScene(Scene):
    """世界地图: 1:1 视口 + 状态标记, 选地点 → 进入该地图."""

    BG = (8, 8, 20)

    def __init__(self, surface: pygame.Surface, world: "Scene",
                 audio=None, start_index: int = 0) -> None:
        super().__init__(surface)
        self.world = world
        self.audio = audio
        self.font = load_chinese_font(20)
        self.big = load_chinese_font(28)
        self.small = load_chinese_font(16)
        self._locs = load_locations()
        self._markers = load_markers()
        self._map: pygame.Surface | None = None
        self._thumb: pygame.Surface | None = None   # 小地图
        if LMAP_IMG.exists():
            self._map = pygame.image.load(str(LMAP_IMG)).convert()
            th = self._map.copy()
            th = pygame.transform.smoothscale(th, (160, 128))
            self._thumb = th
        self._vis: list[int] = []        # 可选地点在 self._locs 的下标
        self.cursor = 0
        self._view = [0, 0]              # 视口左上角 (地图像素)
        self._refresh_vis()
        if self._vis:
            self.cursor = min(max(0, start_index), len(self._vis) - 1)
            self._center_on(self._locs[self._vis[self.cursor]])

    # ---- 状态 ----
    def _story_flags(self) -> set:
        story = getattr(self.world, "story", None)
        return set(getattr(getattr(story, "state", None), "flags", None) or ())

    def _visited_ids(self) -> set[int]:
        save = getattr(self.world, "save", None)
        return set(getattr(save, "world_visited", None) or ())

    def _state(self, loc: dict) -> str:
        """visited / new / locked."""
        wid = loc["id"]
        if wid in self._visited_ids():
            return "visited"
        flags = self._story_flags()
        if wid in INITIAL_IDS:
            return "new"
        need = FLAG_BY_ID.get(wid, DEFAULT_FLAG)
        if need in flags:
            return "new"
        return "locked"

    def _refresh_vis(self) -> None:
        self._vis = [i for i, loc in enumerate(self._locs)
                     if self._state(loc) != "locked" and loc.get("base")]

    # ---- 视口 ----
    def _center_on(self, loc: dict) -> None:
        sw, sh = self.surface.get_size()
        vh = sh - 34                                   # 底部信息条
        self._view = [
            max(0, min(loc["x"] - sw // 2, (self._map.get_width() or 1) - sw)),
            max(0, min(loc["y"] - vh // 2, (self._map.get_height() or 1) - vh)),
        ] if self._map else [0, 0]

    # ---- 输入 ----
    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.QUIT:
            return False
        if event.type != pygame.KEYDOWN:
            return True
        if event.key in (pygame.K_ESCAPE, pygame.K_x, pygame.K_m):
            self.next_scene = self.world
        elif not self._vis:
            return True
        elif event.key in (pygame.K_DOWN, pygame.K_s):
            self._move(1)
        elif event.key in (pygame.K_UP, pygame.K_w):
            self._move(-1)
        elif event.key in (pygame.K_RIGHT, pygame.K_d):
            self._move(1)
        elif event.key in (pygame.K_LEFT, pygame.K_a):
            self._move(-1)
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
            self._enter()
        return True

    def _move(self, delta: int) -> None:
        n = len(self._vis)
        self.cursor = (self.cursor + delta) % n
        self._center_on(self._locs[self._vis[self.cursor]])

    def _enter(self) -> None:
        if not self._vis:
            return
        loc = self._locs[self._vis[self.cursor]]
        # auto_beat 默认 True: 抵达剧情地点照常触发该地剧情 (已完成的节点因 done 集合不会重播,
        # 见 core/story StoryState._ready —— 故不必再传 auto_beat=False)
        if not self.world.enter_location(loc["base"]):
            print(f"[世界地图] {loc['name_s']} ({loc['base']}) 缺地图资源")
            return
        print(f"[世界地图] → {loc['name_s']} ({loc['base']})")
        self.next_scene = self.world

    # ---- 渲染 ----
    def draw(self) -> None:
        sw, sh = self.surface.get_size()
        self.surface.fill(self.BG)
        vh = sh - 34
        self.surface.blit(self.big.render("世 界 地 图", True, (255, 214, 96)), (16, 12))
        hint = self.small.render(
            "方向键 选地点   Enter 进入   ESC 返回   ●去过 ●新 ●未解锁",
            True, (150, 142, 176))
        self.surface.blit(hint, (sw - hint.get_width() - 16, 20))

        if self._map is None:
            self.surface.blit(self.font.render(
                "缺 assets/ui/LMAP00.bmp (先跑 tools.extract_dll)", True, (230, 226, 240)),
                (24, sh // 2))
            return
        if self._locs:
            self._draw_map(sw, vh)
            self._draw_minimap(sw)
        self._draw_infobar(sw, sh)

    def _draw_map(self, sw: int, vh: int) -> None:
        vx, vy = self._view
        self.surface.blit(self._map, (0, 0), (vx, vy, min(sw, 2000), min(vh, 1600)))
        blink = (pygame.time.get_ticks() // 400) % 2 == 0
        m = self._markers
        for i, loc in enumerate(self._locs):
            x, y = loc["x"] - vx, loc["y"] - vy
            if not (-20 <= x <= sw + 20 and -20 <= y <= vh + 20):
                continue
            state = self._state(loc)
            sel = self._vis and self._vis[self.cursor] == i
            if state == "locked":
                if m:
                    self.surface.blit(m["locked"], (x - 4, y - 4))
                continue
            if m:
                dot = m["visited"] if state == "visited" else m["new"]
                if state == "new" and not blink:
                    pass  # 红点闪烁: 半周期不画
                else:
                    self.surface.blit(dot, (x - 4, y - 4))
            if sel and blink and m:
                self.surface.blit(m["arrow0"], (x - 8, y - 26))
            if state == "visited" or sel:
                color = (255, 236, 130) if sel else (230, 226, 214)
                label = self.font.render(loc["name_s"], True, color)
                self.surface.blit(label, (x + 7, y - 10))
            if state == "new" and blink:
                tag = self.small.render("新", True, (255, 96, 84))
                self.surface.blit(tag, (x + 7, y - 9))

    def _draw_minimap(self, sw: int) -> None:
        if self._thumb is None:
            return
        mx, my = sw - 172, 44
        self.surface.blit(self._thumb, (mx, my))
        pygame.draw.rect(self.surface, (200, 196, 220), (mx - 1, my - 1, 162, 130), 1)
        kx, ky = 160 / 2000, 128 / 1600
        vx, vy = self._view
        sw_, sh_ = self.surface.get_size()
        pygame.draw.rect(self.surface, (255, 255, 255),
                         (mx + int(vx * kx), my + int(vy * ky),
                          int(sw_ * kx), int((sh_ - 34) * ky)), 1)
        for i, loc in enumerate(self._locs):
            state = self._state(loc)
            if state == "locked":
                continue
            c = (255, 236, 130) if (self._vis and self._vis[self.cursor] == i) \
                else ((240, 236, 226) if state == "visited" else (255, 96, 84))
            self.surface.fill(c, (mx + int(loc["x"] * kx) - 1,
                                  my + int(loc["y"] * ky) - 1, 2, 2))

    def _draw_infobar(self, sw: int, sh: int) -> None:
        bar = pygame.Surface((sw, 34), pygame.SRCALPHA)
        bar.fill((0, 0, 0, 176))
        self.surface.blit(bar, (0, sh - 34))
        if not self._locs:
            self.surface.blit(self.font.render(
                "缺 assets/worldmap_locations.json (先跑 tools.extract_worldmap)",
                True, (230, 226, 240)), (12, sh - 28))
            return
        if not self._vis:
            self.surface.blit(self.font.render("(尚无可去的地点)", True, (200, 196, 214)),
                              (12, sh - 28))
            return
        loc = self._locs[self._vis[self.cursor]]
        state = self._state(loc)
        tag = {"visited": "去过", "new": "新地点"}.get(state, "")
        self.surface.blit(self.font.render(
            f"▶ {loc['name_s']} ({loc['name']})   {tag}   Enter 进入",
            True, (255, 236, 130)), (12, sh - 28))


# 兼容旧探针脚本 (_verify.py / _shot_atlas.py): (简体名, base, x, y, unlock)
LOCATIONS = [(l["name_s"], l["base"], l["x"], l["y"], None) for l in load_locations()]
