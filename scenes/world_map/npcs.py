"""世界地图 NPC 图层 (A 接入): 渲染地图角色 + 撞上去播放原版对白.

数据来自 `core.map_npcs`（原版 .mfo 的 pcpos/jmp）。
原版行为: 角色格子不可走上去, 走"撞"过去即触发该角色的剧本。

精灵: `core.npc_sprites` 用原版角色表 (exe 0x1b01a9 / 0x1bd9c9, 416B/条) 把
`.mfo jmp` 的全局帧号 `c0` 解析成 `ps_*` 图集 + (行=朝向, 列=帧) 的真精灵.

**原版渲染事实 (已实证)**:
  · 每个 pcpos 落点所在的**地图可视瓦片都是稀有瓦片** (整张图只在各 pcpos 处各出现 1 次),
    且 `地图瓦片号 == jmp.c0 + 20` (TAS0: 312/352/392 ↔ c0 292/332/372; TFI0: 69 ↔ 49) ——
    即原版把角色/门的图形**烘焙进地图瓦片层**, pcpos 本身多是隐形交互点;
  · 只有 `jmp.c0 >= 0` 的角色才**额外**叠一张 FC 精灵 (1087 条里仅 27 条)。
  故: 无 `c0` 的条目**不再画程序占位小人** (避免与原图叠出两个小人/多画假人),
  改为只依赖地图本身的美术; 有 `c0` 的照旧画真精灵。
"""

from __future__ import annotations

import pygame

from core import map_npcs, npc_sprites
from core.anim_state import AnimationState
from core.script_text import first_line, has_dialogue
from core.sprites.base import TILE_W, TILE_H
from scenes.unit_render import blit_unit, pick_locomotion_frame

# 朝向 d (0下 1右 2上 3左) → 面向向量
_DIR_VEC = {0: (0, 1), 1: (1, 0), 2: (0, -1), 3: (-1, 0)}

# 占位小人的配色（按 script id 取模，保持稳定）
_PALETTE = [
    ((196, 84, 72), (232, 196, 160)),     # 红衫
    ((70, 120, 176), (232, 196, 160)),    # 蓝衫
    ((96, 148, 96), (232, 196, 160)),     # 绿衫
    ((168, 132, 72), (232, 196, 160)),    # 褐衫
    ((140, 104, 168), (232, 196, 160)),   # 紫衫
    ((196, 168, 80), (232, 196, 160)),    # 黄衫
]
_HAIR = (48, 38, 34)
_SHADOW = (0, 0, 0, 90)


class NpcLayer:
    """一张地图上的所有角色. 负责绘制与"撞人"判定."""

    def __init__(self, base: str | None, active_flags: set | None = None,
                 events: list[dict] | None = None, doors: set | None = None,
                 real_map=None) -> None:
        self.base = base or ""
        self.doors = set(doors or ())
        self.npcs: list[dict] = map_npcs.npcs_for(self.base) if self.base else []
        for n in self.npcs:
            c0 = (n.get("sprite") or [None])[0]
            # .mfo 的 pcpos 实为"门/出入口"标记; 落在传送门坐标上的条目 = 门, 不挡路、不画人.
            # 注: 其中 jmp.c0>=0 的 27 条看着"像角色", 但实测 c0 是**门美术的图集帧号**
            # (c0+20 == 该门在地图瓦片层的编号), 原版该处显示的仍是门(见攻略截图: 门口无人),
            # 故不把它们当 NPC 画 —— 只在"室内/街道"另配手工 NPC(见 core.authored_npcs).
            n["_door"] = (n["x"], n["y"]) in self.doors
            n["_drawn"] = (not n["_door"]) and isinstance(c0, int) and c0 >= 0
            n["_talk"] = (not n["_door"]) and has_dialogue(n.get("script", -1))
            n["_home"] = (n["x"], n["y"])          # 原版站位 (走动会离开)
        self._at = {(n["x"], n["y"]): n for n in self.npcs}
        self.occupied = set(self._at)
        # 剧情事件角色 (五行山 蒙面人/孙悟空/精灵, 见 core.event_npcs):
        # 不在 .mfo 的 pcpos 里, 由剧情 flag 决定显隐; 持有集合引用以保证剧情推进后即时刷新.
        self.active_flags = active_flags if active_flags is not None else set()
        self._events: list[dict] = []
        self.set_events(events)
        # 手工 NPC (原版数据里没有 NPC 实体; 店铺老板/村民/居民由 core.authored_npcs 编排)
        self._extra: list[dict] = []
        self._build_authored(real_map)
        self._t = 0
        self._clock = 0
        self._hint: str | None = None
        self._hint_pos: tuple[int, int] | None = None

    # ---- 手工 NPC ----
    def _build_authored(self, real_map) -> None:
        """并入手工 NPC: 店老板 / 若干村民 / 室内居民. 位置自动放在中心附近可走的非门格."""
        from core import authored_npcs as A
        specs: list[dict] = []
        info = map_npcs.map_info(self.base)
        mname = info.get("name") or ""
        shop = A.shop_for(self.base)
        if shop is not None:
            specs.append({"name": f"{shop[0]}老板", "shop": True, "sprite": A.SHOPKEEPER_SPRITE,
                          "lines": [f"欢迎光临 {shop[0]}!", "想看点什么, 尽管挑。"]})
        else:
            specs.extend(A.npcs_for(self.base))
            if A.is_interior(mname):
                specs.append({"name": "居民", "sprite": A.resident_sprite(self.base),
                              "lines": A.resident_lines()})
        taken = set(self._at)
        for sp in specs:
            pos = self._auto_pos(real_map, taken)
            if pos is None:
                break
            taken.add(pos)
            d = dict(sp)
            d["x"], d["y"] = pos
            d["_talk"] = True
            d["_drawn"] = True
            d["_home"] = pos
            d["_authored"] = True
            d["_anim"] = AnimationState()      # 走路帧计时 (配合方向 d)
            self._extra.append(d)

    def _auto_pos(self, real_map, taken: set) -> tuple[int, int] | None:
        """在可走的非门格中选一个: 尽量靠地图中心, 但与已放 NPC 至少隔 3 格 (避免叠人).

        ⚠ 只挑**开阔格** (上下左右 ≥3 格可走): 1 格宽的过道/门口绝不能站人 ——
          否则会把唯一的通道堵死 (2026-09-28 用户实测: 屋内自动居民站在过道里, 门过不去)。
        """
        if real_map is None:
            return None
        cx, cy = real_map.w // 2, real_map.h // 2
        cands: list[tuple[int, int]] = []
        for y in range(real_map.h):
            for x in range(real_map.w):
                if (x, y) in self.doors or (x, y) in taken:
                    continue
                if not real_map.passable(x, y):
                    continue
                nb = sum(1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                         if real_map.passable(x + dx, y + dy))
                if nb >= 3:
                    cands.append((x, y))
        if not cands:
            # 没有开阔格 (极小的图) → 退回旧逻辑
            for y in range(real_map.h):
                for x in range(real_map.w):
                    if (x, y) not in self.doors and (x, y) not in taken \
                            and real_map.passable(x, y):
                        cands.append((x, y))
        if not cands:
            return None
        near = [p for p in cands
                if all(abs(p[0] - t[0]) + abs(p[1] - t[1]) >= 3 for t in taken)]
        pool = near or cands
        # 有"隔开"的候选就取最靠地图中心的; 否则取离已放点最远的
        if near:
            return min(pool, key=lambda p: abs(p[0] - cx) + abs(p[1] - cy))
        return max(pool, key=lambda p: min(abs(p[0] - t[0]) + abs(p[1] - t[1]) for t in taken))

    def set_events(self, events: list[dict] | None) -> None:
        """替换剧情事件角色列表 (也用于 story 就绪后回填)."""
        self._events = []
        for e in (events or []):
            d = dict(e)
            d["_evt"] = True
            d["_talk"] = True                      # 可撞上去说话
            d["_home"] = (d["x"], d["y"])
            self._events.append(d)

    def set_flags(self, flags: set | None) -> None:
        """持有剧情 flag 集合的引用 (事件角色显隐据此动态变化)."""
        self.active_flags = flags if flags is not None else set()

    # ---- 查询 ----
    def evt_visible(self, e: dict) -> bool:
        """事件角色当前是否应显示: requires 满足 且 未触发 hide_when."""
        if not e.get("_evt"):
            return False
        if e.get("requires") and e["requires"] not in self.active_flags:
            return False
        if e.get("hide_when") and e["hide_when"] in self.active_flags:
            return False
        return True

    def evt_at(self, x: int, y: int) -> dict | None:
        for e in self._events:
            if self.evt_visible(e) and e["x"] == x and e["y"] == y:
                return e
        return None

    def _extra_at(self, x: int, y: int) -> dict | None:
        for n in self._extra:
            if n["x"] == x and n["y"] == y:
                return n
        return None

    def at(self, x: int, y: int) -> dict | None:
        n = self._at.get((x, y))
        if n is not None:
            return n
        n = self._extra_at(x, y)                    # 手工 NPC (老板/村民/居民)
        if n is not None:
            return n
        return self.evt_at(x, y)                   # 事件角色也能被撞到/对话

    def blocks(self, x: int, y: int) -> bool:
        """有对白的角色挡路（面前按空格触发）; 无对白的当装饰可穿过; 门格永不挡路."""
        if (x, y) in self.doors:
            return False                            # 门/出入口: 可踩上以触发传送
        n = self._extra_at(x, y)
        if n is not None:
            return bool(n.get("_talk"))
        n = self._at.get((x, y))
        if n is not None:
            return bool(n["_talk"])
        return self.evt_at(x, y) is not None       # 事件角色一律挡路

    @property
    def count(self) -> int:
        return len(self.npcs) + len(self._extra)

    @property
    def dialogue_count(self) -> int:
        return sum(1 for n in self.npcs if n["_talk"]) + len(self._extra)

    def hint(self) -> tuple[str, tuple[int, int]] | None:
        """当前贴在玩家旁的对白预览 (没有则 None)."""
        if self._hint is None or self._hint_pos is None:
            return None
        return self._hint, self._hint_pos

    def set_hint(self, npc: dict | None) -> None:
        if npc is None:
            self._hint = None
            self._hint_pos = None
            return
        self._hint = self._bubble_text(npc)
        self._hint_pos = (npc["x"], npc["y"])

    # ---- 动画 / 走动 ----
    def tick(self, dt_ms: int, passable=None) -> None:
        self._t = (self._t + dt_ms) % 2000
        self._wander(dt_ms, passable)          # 原版 c0 角色 (~0.9s 一跳)
        self._wander_extra(dt_ms, passable)    # 手工 NPC (逐帧, 带停顿/回窝)

    def _wander_extra(self, dt_ms: int, passable=None) -> None:
        """手工 NPC 踱步: 在被放下的位置附近(±3 格)走动, 每步之间随机停顿, 不踩门/不重叠.

        (以 _home 为"窝", 走得离窝太远就不往那个方向去 —— 免得村民飘出村口/卡进角落.)
        """
        import random
        if not self._extra:
            return
        for n in self._extra:
            moved = False
            n["_pause"] = n.get("_pause", 0) - dt_ms
            if n["_pause"] <= 0:
                hx, hy = n.get("_home", (n["x"], n["y"]))
                dirs = [(0, 1), (1, 0), (0, -1), (-1, 0)]
                random.shuffle(dirs)
                for d in dirs:
                    nx, ny = n["x"] + d[0], n["y"] + d[1]
                    if abs(nx - hx) + abs(ny - hy) > 3:
                        continue                                   # 离窝太远 → 不去
                    if (nx, ny) in self.doors or (nx, ny) == self._player_tile:
                        continue
                    if (nx, ny) in self._at \
                            or any((m["x"], m["y"]) == (nx, ny) for m in self._extra):
                        continue
                    if passable is not None and not passable(nx, ny):
                        continue
                    n["d"] = {(0, 1): 0, (1, 0): 1, (0, -1): 2, (-1, 0): 3}[d]
                    n["x"], n["y"] = nx, ny
                    moved = True
                    break
                n["_pause"] = random.randint(800, 2600)            # 走/停交替, 像在干活
            anim = n.get("_anim")
            if anim is not None:
                anim.tick(dt_ms, moving=moved)

    def _wander(self, dt_ms: int, passable=None) -> None:
        """原版 NPC 会走动: 每 ~0.9s 随机走一格 (不走出可通行区, 不叠人)."""
        import random
        self._clock += dt_ms
        if self._clock < 900:
            return
        self._clock = 0
        for n in self.npcs:
            if not n.get("_drawn"):              # 无 FC 精灵的条目 (图形烘焙在地图里) 不动
                continue
            if random.random() < 0.55:           # 一半角色原地不动
                continue
            dx, dy = random.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
            nx, ny = n["x"] + dx, n["y"] + dy
            if (nx, ny) in self.occupied or (nx, ny) == self._player_tile:
                continue
            if passable is not None and not passable(nx, ny):
                continue
            self._at.pop((n["x"], n["y"]), None)
            n["x"], n["y"] = nx, ny
            self._at[(nx, ny)] = n
            self.occupied = set(self._at)

    _player_tile: tuple[int, int] | None = None

    def set_player_tile(self, x: int, y: int) -> None:
        self._player_tile = (x, y)

    # ---- 渲染 ----
    def draw(self, surface: pygame.Surface, cam_x: int, cam_y: int,
             font: pygame.font.Font | None = None,
             y_from: int | None = None, y_to: int | None = None) -> None:
        """画角色. y_from/y_to 用于按行分段 (让玩家能插在中间做 Y 排序)."""
        if not self.npcs:
            return
        sw, sh = surface.get_size()
        bob = 1 if self._t < 1000 else 0          # 呼吸/踏步给个 2 帧感
        for n in self.npcs:
            if y_from is not None and n["y"] < y_from:
                continue
            if y_to is not None and n["y"] > y_to:
                continue
            px = n["x"] * TILE_W - cam_x
            py = n["y"] * TILE_H - cam_y
            if px < -TILE_W or py < -TILE_H or px > sw or py > sh:
                continue
            self._draw_one(surface, px, py, n, bob, font)
        # 手工 NPC (老板/村民/居民): 一律画占位小人 (无 FC 精灵)
        for n in self._extra:
            if y_from is not None and n["y"] < y_from:
                continue
            if y_to is not None and n["y"] > y_to:
                continue
            px = n["x"] * TILE_W - cam_x
            py = n["y"] * TILE_H - cam_y
            if px < -TILE_W or py < -TILE_H or px > sw or py > sh:
                continue
            self._draw_authored(surface, px, py, n, bob, font)
        # 剧情事件角色 (按 flag 显隐), 同样参与 Y 排序
        for e in self._events:
            if not self.evt_visible(e):
                continue
            if y_from is not None and e["y"] < y_from:
                continue
            if y_to is not None and e["y"] > y_to:
                continue
            px = e["x"] * TILE_W - cam_x
            py = e["y"] * TILE_H - cam_y
            if px < -TILE_W or py < -TILE_H or px > sw or py > sh:
                continue
            self._draw_event(surface, px, py, e, bob, font)

    def _near(self, n: dict) -> bool:
        return self._hint_pos == (n["x"], n["y"])

    def _draw_one(self, surface: pygame.Surface, px: int, py: int,
                  npc: dict, bob: int, font: pygame.font.Font | None) -> None:
        """真精灵优先 (64x96, 与玩家单位同一锚点).

        无 `c0` 的条目原版不额外画精灵 (图形已烘焙进地图, 见 docstring), 只画交互气泡.
        """
        FW, FH = npc_sprites.FRAME_W, npc_sprites.FRAME_H
        spr = None
        if npc.get("_drawn"):
            c0 = npc.get("sprite", [None])[0]
            if isinstance(c0, int) and c0 >= 0:
                anim = npc.get("_anim")
                af = (anim.anim_time_ms // 140) % 6 if anim is not None and anim.anim_time_ms > 0 else 0
                spr = npc_sprites.surface_for(c0, direction=npc.get("d") or 0, anim=int(af))
        top = py
        if spr is not None:
            # 与 scenes.unit_render 的脚点锚一致: frame_h - TILE_H/2 + 12
            anchor_y = FH - TILE_H // 2 + 12
            surface.blit(spr, (px + TILE_W // 2 - FW // 2,
                               py + TILE_H // 2 - anchor_y + bob))
            top = py + TILE_H // 2 - anchor_y
        elif npc.get("_drawn"):
            # 有 c0 但图集加载失败 → 兜底画占位小人
            self._draw_figure(surface, px, py, npc, bob)
        if font is not None and npc["_talk"] and self._near(npc):
            self._draw_bubble(surface, px, top, npc, bob, font)

    def _draw_event(self, surface: pygame.Surface, px: int, py: int,
                    npc: dict, bob: int, font: pygame.font.Font | None) -> None:
        """画剧情事件角色: 优先原版角色精灵 (ps_*), 取不到则用占位小人."""
        spr = None
        try:
            from core.sprites.loaders import get_character_sprite
            spr = get_character_sprite(npc.get("name") or "")
        except Exception:
            spr = None
        top = py
        if spr is not None and spr.get_size()[0] > 0:
            FW, FH = spr.get_size()
            anchor_y = FH - TILE_H // 2 + 12
            surface.blit(spr, (px + TILE_W // 2 - FW // 2,
                               py + TILE_H // 2 - anchor_y + bob))
            top = py + TILE_H // 2 - anchor_y
        else:
            self._draw_figure(surface, px, py, npc, bob)
            top = py + TILE_H - 8 - 56 + bob
        if font is not None and self._near(npc):
            self._draw_bubble(surface, px, top, npc, bob, font)

    def _bubble_text(self, npc: dict) -> str:
        """气泡预览字: 手工 NPC 用自身台词, 事件角色用自身台词, 地图角色用原版剧本首行."""
        if npc.get("_authored"):
            lines = npc.get("lines") or []
            return (lines[0] if lines else npc.get("name")) or "..."
        if npc.get("_evt"):
            t = (npc.get("line") or "").strip().strip("（）")
            return t or npc.get("name") or "..."
        return first_line(npc.get("script", -1)) or "..."

    def _draw_authored(self, surface: pygame.Surface, px: int, py: int,
                       npc: dict, bob: int, font: pygame.font.Font | None) -> None:
        """手工 NPC: 优先原版真精灵 (含朝向+走路帧), 取不到才画占位小人."""
        spr = None
        name = npc.get("sprite")
        if name:
            try:
                from core.sprites.loaders import get_character_sprite
                spr = get_character_sprite(name)
            except Exception:
                spr = None
        if spr is not None:
            facing = _DIR_VEC.get(npc.get("d") or 0, (0, 1))
            anim = npc.get("_anim") or AnimationState()
            frame, anchor = pick_locomotion_frame(spr, None, facing, anim,
                                                  walk_period_ms=140, idle_period_ms=500)
            cx, cy = px + TILE_W // 2, py + TILE_H // 2
            blit_unit(surface, frame, anchor, tile_center_x=cx, tile_center_y=cy)
            top = cy - anchor[1]
        else:
            self._draw_figure(surface, px, py, npc, bob)
            top = py + TILE_H - 8 - 56 + bob
        if font is not None and self._near(npc):
            self._draw_bubble(surface, px, top, npc, bob, font)

    def _draw_bubble(self, surface: pygame.Surface, px: int, top: int,
                     npc: dict, bob: int, font: pygame.font.Font) -> None:
        text = self._bubble_text(npc)
        if len(text) > 12:
            text = text[:11] + "…"
        txt_s = font.render(text, True, (20, 20, 20))
        pad = 5
        bw = txt_s.get_width() + pad * 2
        bh = txt_s.get_height() + pad * 2
        bx = px + TILE_W // 2 - bw // 2
        by = top - bh - 10 - bob
        if by < 0:
            by = 0
        # 气泡本体 + 细边
        pygame.draw.rect(surface, (255, 250, 235), (bx, by, bw, bh), border_radius=8)
        pygame.draw.rect(surface, (80, 70, 90), (bx, by, bw, bh), 2, border_radius=8)
        # 小尾巴指向 NPC 头顶
        tri = [(px + TILE_W // 2, top - 4 - bob),
               (bx + bw // 2 - 5, by + bh - 2),
               (bx + bw // 2 + 5, by + bh - 2)]
        pygame.draw.polygon(surface, (255, 250, 235), tri)
        pygame.draw.polygon(surface, (80, 70, 90), tri, 2)
        surface.blit(txt_s, (bx + pad, by + pad))

    def _draw_figure(self, surface: pygame.Surface, px: int, py: int,
                     npc: dict, bob: int) -> None:
        cx = px + TILE_W // 2
        base_y = py + TILE_H - 8 + bob
        key = npc.get("script")
        if key is None:                        # 事件角色无 script, 用名字取色
            key = sum(ord(c) for c in str(npc.get("name") or ""))
        body, skin = _PALETTE[key % len(_PALETTE)]
        talk = bool(npc.get("_talk"))
        if not talk:                      # 无对白的装饰角色画淡一点
            body = tuple(min(255, c + 60) for c in body)
        dark = tuple(max(0, c - 60) for c in body)
        outline = (28, 22, 26)
        # 影子
        shadow = pygame.Surface((36, 12), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, _SHADOW, shadow.get_rect())
        surface.blit(shadow, (cx - 18, base_y - 5))
        # 身体 + 下摆 (描边保证在杂乱地图上也能看清)
        torso = pygame.Rect(cx - 11, base_y - 36, 22, 32)
        hem = pygame.Rect(cx - 13, base_y - 10, 26, 10)
        for r, col in ((torso, body), (hem, dark)):
            pygame.draw.rect(surface, outline, r.inflate(4, 4), border_radius=5)
            pygame.draw.rect(surface, col, r, border_radius=4)
        # 头
        head = (cx, base_y - 45)
        pygame.draw.circle(surface, outline, head, 12)
        pygame.draw.circle(surface, skin, head, 10)
        # 眼睛 (按朝向 d: 0下 1右 2上 3左; 背对时不画)
        d = npc.get("d") or 0
        if d != 2:
            ex = {0: 0, 1: 3, 2: 0, 3: -3}.get(d, 0)
            pygame.draw.circle(surface, (30, 26, 30), (cx - 3 + ex, base_y - 45), 1)
            pygame.draw.circle(surface, (30, 26, 30), (cx + 3 + ex, base_y - 45), 1)
        # 头发 / 头巾
        cap = pygame.Rect(cx - 10, base_y - 56, 20, 8)
        pygame.draw.rect(surface, outline, cap.inflate(4, 4), border_radius=4)
        pygame.draw.rect(surface, _HAIR, cap, border_radius=3)
