"""世界地图场景: 30x30 占位 tile, WASD/方向键移动, 镜头跟随玩家.

战斗触发逻辑在 battle_launch.py, 地形数据在 terrain.py.
"""

from __future__ import annotations

import random
from pathlib import Path

import pygame

from core.exe_rng import ExeRng
from core import real_map as realm
from core import world_graph
from core import chests as chests_mod
from core import event_npcs
from core.anim_state import AnimationState
from core.audio_manager import AudioManager
from core.character_sprites import sprite_resource
from core.movement_input import DirectionalHold
from core.save_manager import SaveData
from core.script_text import to_messages
from core.story import Director
from core.sprites.atlas_classes import idle_key_from_walk_key
from core.sprites.base import TILE_W, TILE_H
from core.sprites.loaders import get_character_sprite, get_idle_sprite
from scenes.base import Scene
from scenes.menu import load_chinese_font
from scenes.unit_render import blit_unit, pick_locomotion_frame
from scenes.world_map import battle_launch
from scenes.world_map.npcs import NpcLayer
from scenes.world_map.terrain import (
    MAP_H,
    MAP_W,
    TILES,
    TerrainType,
    build_test_map,
)


WALK_SPEED_TILES_PER_SEC = 13.0   # 大地图 tile/秒, 各轴像素速度 = 该轴 tile 尺寸 * 这里. 10 → 13 全局加速
WALK_FRAME_PERIOD_MS = 60        # 行走动画切换间隔 (80 → 60)
WALK_HOLD_DELAY_MS = 80          # 按住方向键超过这时间后才自动连走 (tap 只转向)

# 步行走到这些"世界地图枢纽"传送口 = 出村, 改为打开"选地点"大地图 (M 同款), 而非进入步行大地图
WORLD_SELECT_HUBS = {"T_LOC0_P"}

# 覆盖层(网格B)渲染开关: 现在默认**开** —— 逐行交错绘制后它画在该行实体之后,
# 屋顶/雨棚/墙沿/室内木地板都能正确遮挡 (2026-09-29 用户实测反馈后开启)。
# 跨页回退图集 (ts_name 与 base 不同页) 会自动跳过, 避免花斑 (见 RealMap.draw_overlay)。
ENABLE_OVERLAY = True

# HUD: 固定三行 (①状态 ②剧情 ③按键提示), 避免右对齐内容与长文本叠字
HUD_H = 84
HUD_KEYS = ("[空格] 对话·开店    [M] 地图    [I] 背包    [ESC] 菜单    "
            "F1 枢纽    F2 世界    T 剧本")

# ---- 原版交互音效 (全局 sound_id, 见 core.sound_table / assets/audio_extracted) ----
# id 0..167 = se_event (事件/语音), 168..360 = 战斗音效 ef_E*.wav
SFX_TALK = (10, 11, 12, 13, 14, 15, 16)     # se__TALK1..7 七种说话声
SFX_ITEM_GET = 4                             # se__ITEMGET0 获得道具
SFX_BOX_OPEN = 23                            # se_OPENBOX00 开箱
SFX_DOOR = 19                                # se_DOOR00 过门/传送
SFX_FLAG_ON = 3                              # se__FLAG_ON 剧情节点推进

_CHEST_FRAMES: dict[str, pygame.Surface] | None = None


def _chest_sprite(opened: bool = False) -> pygame.Surface | None:
    """原版宝箱精灵 fm_BOX__SPR (128x192 = 2列x3行, 64x64/帧, 品红底).

    帧 0 (左上) = **关盖**; 帧 1 (右上) = **开盖** (同款箱子, 上半是黑洞洞的箱内)。
    品红 (255,0,255) = PCX 色键, 用 colorkey 抠掉。加载失败返回 None (调用方退回圆点)。
    """
    global _CHEST_FRAMES
    if _CHEST_FRAMES is None:
        _CHEST_FRAMES = {}
        try:
            p = Path(__file__).resolve().parents[2] / "assets" / "sprites" / "fm_BOX__SPR.png"
            img = pygame.image.load(str(p)).convert_alpha()
            # 色键取**角点像素**: fm_BOX__SPR 的底色是绿 (0,175,0), 不是品红 ——
            # 硬编码品红抠不掉, 游戏里宝箱周围就是一个绿框 (2026-09-29 用户截图)。
            img.set_colorkey(tuple(img.get_at((0, 0)))[:3])
            _CHEST_FRAMES = {
                "closed": img.subsurface(pygame.Rect(0, 0, 64, 64)).copy(),
                "open": img.subsurface(pygame.Rect(64, 0, 64, 64)).copy(),
            }
        except Exception:
            pass
    return _CHEST_FRAMES.get("open" if opened else "closed")


class WorldMapScene(Scene):
    """玩家在 30x30 网格上走动. ESC 返回主菜单."""

    HUD_BG = (0, 0, 0, 180)
    HUD_TEXT = (255, 255, 255)
    PLAYER_COLOR = (255, 50, 200)

    def __init__(
        self,
        surface: pygame.Surface,
        audio: AudioManager,
        save: SaveData | None = None,
    ) -> None:
        super().__init__(surface)
        self.audio = audio
        self.save = save
        self.grid = build_test_map()
        # 玩家 tile 坐标 (静止时); 移动时已经更新为目标 tile, 用 subpx/py 做插值.
        self.real_map = self._try_real_map()
        self.player_x, self.player_y = self._start_pos()
        self.player_z = (self.real_map.layer_at(self.player_x, self.player_y)
                         if self.real_map is not None else 0)   # 原版的层号 (海拔区域)
        self.location_base = realm.DEFAULT_WORLD_MAP
        self._transitions = world_graph.transitions(self.location_base)
        self.npc_layer = NpcLayer(self.location_base, doors=set(self._transitions),
                                  real_map=self.real_map)
        self._hint_tile: tuple[int, int] | None = None
        self.chests = chests_mod.chests_for(self.location_base)
        self._chest_hint: tuple[int, int] | None = None
        self.story = Director(save=save)      # 主线流程导演 (B) + 队伍
        # NpcLayer 需要剧情 flag 引用与事件角色表, 故在 story 就绪后回填
        self.npc_layer.set_flags(self.story.state.flags)
        self.npc_layer.set_events(event_npcs.EVENT_NPCS.get(self.location_base, ()))
        self._post_battle_beat: "object | None" = None  # 剧情战斗胜利后待结算的节点
        # 队长精灵: 原版主角是美娜 (永远站 C 位), 即便后期悟空/蒙面人入队也不换
        p = self.story.party
        self.party_leader = "美娜" if "美娜" in p else (p[0] if p else "美娜")
        self._dbg_edge = False
        self._dbg_tile = False        # F3: 瓦片/属性 调试叠加 (定位"能站到墙上"这类问题)
        self._dbg_tile_edge = False
        self._no_hud = False          # 抓背景图时置真 (对白浮在场景上, 不带 HUD)
        self._story_toast: str | None = None
        self._story_toast_t = 0
        # 当前像素相对目标 tile 的偏移 (从前一格滑入时为负), 静止时 (0, 0).
        self.subpx = 0.0
        self.subpy = 0.0
        self.moving_dir: tuple[int, int] = (0, 0)
        self.font = load_chinese_font(20)
        self.small = load_chinese_font(16)      # HUD 按键提示用小字
        self.steps = 0
        self.rng = ExeRng()
        # 队长角色 sprite (已在上方按队伍设为美娜, 此处保留 facing 初始化)
        self.facing: tuple[int, int] = (0, 1)  # 初始朝下
        self._anim = AnimationState()
        # 输入门: 进/回到地图时, 必须松开方向键再按才接受 (防止战斗结束瞬间自动续走)
        self._input_gated = True
        # 方向键长按检测器 (tap 只转向 / 持续按住超阈值才连走)
        self._hold = DirectionalHold()
        try:
            self._leader_sprite = get_character_sprite(sprite_resource(self.party_leader))
        except Exception:
            self._leader_sprite = None

    def _try_real_map(self):
        if realm.maps_available():
            try:
                return realm.load(realm.DEFAULT_WORLD_MAP)
            except Exception:
                return None
        return None

    def _map_w(self):
        return self.real_map.w if self.real_map is not None else MAP_W

    def _map_h(self):
        return self.real_map.h if self.real_map is not None else MAP_H

    def _start_pos(self):
        if self.real_map is not None:
            return self.real_map.start_pos()
        return (3, 3)

    # ------- 位置切换 (地图关联, 见 core/world_graph) -------
    def enter_location(self, base: str, spawn=None, auto_beat: bool = True) -> bool:
        """切到另一张地图; 出生点优先用 spawn / 位置表, 否则地图中心."""
        if not realm.is_available(base):
            return False
        try:
            self.real_map = realm.load(base)
        except Exception as e:
            print("enter_location failed:", e)
            return False
        self.location_base = base
        self._transitions = world_graph.transitions(base)
        pos = spawn or world_graph.spawn(base) or self.real_map.start_pos()
        # 门格常画在墙上 (严格不可走), 但作为传送点必须允许站立; 否则会退回 map 默认出生点
        if not (self.real_map.passable(pos[0], pos[1], self.real_map.layer_at(*pos))
                or (pos[0], pos[1]) in self._transitions):
            pos = self.real_map.start_pos()
        self.player_x, self.player_y = pos
        self.player_z = self.real_map.layer_at(*pos)
        self.subpx = self.subpy = 0.0
        self.moving_dir = (0, 0)
        self._anim.reset()
        # 去过的地点记到存档 (M 键世界地图显示"去过"标记)
        info = world_graph.info(base)
        wid = info.get("id") if info else None
        if wid is not None:
            visited = getattr(self.save, "world_visited", None)
            if visited is None:
                visited = []
                self.save.world_visited = visited
            if wid not in visited:
                visited.append(wid)
        self.npc_layer = NpcLayer(
            base, active_flags=self.story.state.flags,
            events=event_npcs.EVENT_NPCS.get(base, ()),
            doors=set(self._transitions), real_map=self.real_map)
        self.chests = chests_mod.chests_for(base)
        self._hint_tile = None
        self._chest_hint = None
        # 仅"无地点约束"节点 (序章等开篇演出) 进图时自动播;
        # 地点剧情改由「面对 NPC 按空格」(见 _talk_to) 触发 —— 去掉 G 键与走到即弹对白。
        if auto_beat:
            cur = self.story.current()
            if cur is not None and not cur.enter:
                self._launch_beat(cur)
        return True

    def _world_id(self, base: str) -> int | None:
        info = world_graph.info(base)
        return info.get("id") if info else None

    def _entry_spawn(self, dest_base: str, src_id: int | None):
        """进入 dest_base 时的落点 = **通向来源图的那扇门**的门口.

        原版从屋里出来应站在**该屋门前**, 而不是城镇的默认出生点 (村口大门)。
        子图的门本身可走 (门垫) 就直接站门上; 城镇的房门画在墙上 (不可走),
        则站到门前方那格 (这些门唯一可走的邻居就是门下方 / 门前)。
        找不到反向门 (如世界地图/剧情传送) 返回 None → 用默认落点。
        """
        if src_id is None:
            return None
        tr = world_graph.transitions(dest_base)
        try:
            m = realm.load(dest_base)
        except Exception:
            return None
        for (x, y), t in tr.items():
            if t != src_id:
                continue
            if m.passable(x, y):
                return (x, y)                     # 屋内门垫
            for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                nx, ny = x + dx, y + dy
                if (0 <= nx < m.w and 0 <= ny < m.h and m.passable(nx, ny)
                        and (nx, ny) not in tr):
                    return (nx, ny)               # 门前那格
            return (x, y)
        return None

    def _check_transition(self) -> None:
        tgt = self._transitions.get((self.player_x, self.player_y))
        if tgt is None:
            return
        # 步行传送的剧情门控 (与 M 键世界地图 unlock 一致): 缺 flag 则挡住并提示
        gate = world_graph.gate_for(self.location_base, self.player_x, self.player_y)
        if gate is not None and gate not in self.story.state.flags:
            self._story_toast = "（剧情未到，暂无法前往）"
            self._story_toast_t = 1800
            return
        base = world_graph.base_for(tgt)
        if base is None:
            print(f"[位置] 目标 {tgt} 未解析 (命名/世界地图空间)")
            return
        # 出村: 走到世界地图枢纽 (T_LOC0_P) 的传送口 → 打开"选地点"大地图, 而非步行进大地图
        if base in WORLD_SELECT_HUBS:
            from scenes.world_map.atlas import WorldAtlasScene
            self.next_scene = WorldAtlasScene(self.surface, self, self.audio)
            return
        # 落点 = 「回到来源图那扇门」的门口: 从屋里出来站在**屋子门口**, 不是村口大门
        spawn = self._entry_spawn(base, self._world_id(self.location_base))
        if self.enter_location(base, spawn=spawn):
            self._sfx(SFX_DOOR)           # 过门/传送声
            print(f"[位置] -> {base} (ID {tgt}) spawn={spawn}")

    # ------- 生命周期 -------
    def on_enter(self) -> None:
        # 战斗回到地图时也走这: 重置移动残留状态, 重新锁住输入门
        self._input_gated = True
        self.moving_dir = (0, 0)
        self.subpx = 0.0
        self.subpy = 0.0
        self._anim.reset()
        self._hold.reset()
        try:
            self.audio.play_bgm("world1.wav")
        except Exception as e:
            print(f"world BGM 缺失: {e}")

    # ------- 输入 -------
    DIR_KEYS = (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN,
                pygame.K_a, pygame.K_d, pygame.K_w, pygame.K_s)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            # ESC → 暂停菜单 (继续/保存/读取/返回标题), 不再直接弹回标题
            from scenes.pause import PauseScene
            self.next_scene = PauseScene(self.surface, self, self.audio)
            return True
        if event.type == pygame.KEYDOWN and event.key == pygame.K_m:
            from scenes.world_map.atlas import WorldAtlasScene
            self.next_scene = WorldAtlasScene(self.surface, self, self.audio)
            return True
        if event.type == pygame.KEYDOWN and event.key == pygame.K_e:
            from scenes.team_info import open_from_world      # 原版 隊伍情報 (装备/道具/特殊能力)
            self.next_scene = open_from_world(self)
            return True
        if event.type == pygame.KEYDOWN and event.key == pygame.K_i:
            from scenes.inventory import InventoryScene       # 道具 (消耗品使用)
            self.next_scene = InventoryScene(self.surface, self, self.audio, self.save)
            return True
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_SPACE, pygame.K_RETURN):
            self._interact()
            return True
        # 输入门只能由"全新按下"的方向键事件解开 (避免战斗返回时长按状态自动续走)
        if event.type == pygame.KEYDOWN and event.key in self.DIR_KEYS and self._input_gated:
            self._input_gated = False
        return True

    # ------- 更新 -------
    def update(self, dt_ms: int) -> None:
        self.npc_layer.set_player_tile(self.player_x, self.player_y)
        self.npc_layer.tick(dt_ms, self.passable_at)
        self._update_npc_hint()
        self._update_chest_hint()
        if self._story_toast_t > 0:
            self._story_toast_t -= dt_ms
            if self._story_toast_t <= 0:
                self._story_toast = None
        if self.moving_dir != (0, 0):
            self._advance_movement(dt_ms)
        # 战斗触发: 跳过本帧后续的输入轮询, 避免按键续写出残留 moving 状态被冻结
        if self.next_scene is not None:
            return
        # 到位 (或本来静止) 后, 检查输入是否要开始下一格移动.
        if self.moving_dir == (0, 0):
            self._poll_input_for_next_step(dt_ms)

    def _advance_movement(self, dt_ms: int) -> None:
        """像素级推进 subpx/subpy 朝 (0,0). 到位后落地到目标 tile 并触发战斗判定.
        各轴用各自 tile 尺寸 * 速度: 保证横纵向都是 10 tile/秒 (= 同样时间过 1 tile)."""
        sec = dt_ms / 1000.0
        step_x = WALK_SPEED_TILES_PER_SEC * TILE_W * sec
        step_y = WALK_SPEED_TILES_PER_SEC * TILE_H * sec
        # subpx/y 符号与 moving_dir 相反 (从前一格滑入), 朝 0 收敛
        if self.subpx != 0:
            if abs(self.subpx) <= step_x:
                self.subpx = 0.0
            else:
                self.subpx += step_x if self.subpx < 0 else -step_x
        if self.subpy != 0:
            if abs(self.subpy) <= step_y:
                self.subpy = 0.0
            else:
                self.subpy += step_y if self.subpy < 0 else -step_y
        self._anim.tick(dt_ms, moving=True)
        if self.subpx == 0 and self.subpy == 0:
            self.moving_dir = (0, 0)
            self.steps += 1
            battle_launch.maybe_trigger_battle(self)

    def _poll_input_for_next_step(self, dt_ms: int) -> None:
        """复刻原版语义: 引擎里 <DIR> 与 <WALK> 是独立 primitive.
        tap 仅转向; 持续按住超 WALK_HOLD_DELAY_MS 才自动连走.
        见 core.movement_input.DirectionalHold.
        """
        if self._input_gated:
            self._hold.reset()
            self._anim.reset()
            return
        keys = pygame.key.get_pressed()
        # 调试: F1 = 跳到枢纽位置 348 / F2 = 返回世界地图
        if keys[pygame.K_F1] and not self._dbg_edge:
            self._dbg_edge = True
            self.enter_location(world_graph.base_for(348) or "TAL0___P")
            return
        if keys[pygame.K_F2] and not self._dbg_edge:
            self._dbg_edge = True
            self.enter_location(realm.DEFAULT_WORLD_MAP)
            return
        if keys[pygame.K_t] and not self._dbg_edge:
            self._dbg_edge = True
            from scenes.dialogue import DialogueScene
            self.next_scene = DialogueScene(self.surface, return_scene=self)
            return
        # F3 = 瓦片/属性 调试叠加开关 (报告"能站到墙上"时按 F3 读坐标/tile/flag)
        if keys[pygame.K_F3] and not self._dbg_tile_edge:
            self._dbg_tile_edge = True
            self._dbg_tile = not self._dbg_tile
        if not keys[pygame.K_F3]:
            self._dbg_tile_edge = False
        if not (keys[pygame.K_F1] or keys[pygame.K_F2] or keys[pygame.K_t]):
            self._dbg_edge = False
        dx = (keys[pygame.K_RIGHT] or keys[pygame.K_d]) - (keys[pygame.K_LEFT] or keys[pygame.K_a])
        dy = (keys[pygame.K_DOWN]  or keys[pygame.K_s]) - (keys[pygame.K_UP]   or keys[pygame.K_w])
        if dx == 0 and dy == 0:
            self._hold.reset()
            self._anim.reset()
            return
        if dx != 0:  # 优先水平, 避免对角斜跳
            dy = 0
        new_dir = (dx, dy)
        edge = self._hold.tick(new_dir, dt_ms)

        if new_dir != self.facing:
            if edge:
                self.facing = new_dir   # 转向即生效, 不插过渡帧
            self._anim.reset()
            return

        # 朝向已对齐: 是否走一步
        if not self._hold.should_walk(edge, WALK_HOLD_DELAY_MS):
            self._anim.reset()
            return
        nx, ny = self.player_x + dx, self.player_y + dy
        npc = self.npc_layer.at(nx, ny)
        if npc is not None and self.npc_layer.blocks(nx, ny):
            # 地图角色挡路: 站着面向它即可, 交谈改用空格触发 (见 _interact)
            self.facing = new_dir
            self._anim.reset()
            self._update_npc_hint()
            return
        dest = self._step_to(dx, dy)
        if dest is not None:
            nx, ny = dest
            self.subpx = -(nx - self.player_x) * TILE_W
            self.subpy = -(ny - self.player_y) * TILE_H
            self.player_x, self.player_y = nx, ny
            self.moving_dir = (dx, dy)
            self._check_transition()
        else:
            # 撞墙: 原地踏步动画, 帧继续切换
            self._anim.tick(dt_ms, moving=True)

    # ------- 渲染 -------
    def camera_offset_for(self, focus_x: int, focus_y: int) -> tuple[int, int]:
        """让 (focus_x, focus_y) 这格在屏幕中心, 边缘夹紧."""
        sw, sh = self.surface.get_size()
        cx = focus_x * TILE_W + TILE_W // 2 - sw // 2
        cy = focus_y * TILE_H + TILE_H // 2 - sh // 2
        max_cx = self._map_w() * TILE_W - sw
        max_cy = self._map_h() * TILE_H - sh
        cx = max(0, min(cx, max(0, max_cx)))
        cy = max(0, min(cy, max(0, max_cy)))
        return cx, cy

    def _camera_offset(self) -> tuple[int, int]:
        # 用像素位置 (含 subpx/y) 让相机跟随平滑
        sw, sh = self.surface.get_size()
        focus_px = self.player_x * TILE_W + self.subpx + TILE_W / 2
        focus_py = self.player_y * TILE_H + self.subpy + TILE_H / 2
        cx = int(focus_px - sw / 2)
        cy = int(focus_py - sh / 2)
        max_cx = self._map_w() * TILE_W - sw
        max_cy = self._map_h() * TILE_H - sh
        cx = max(0, min(cx, max(0, max_cx)))
        cy = max(0, min(cy, max(0, max_cy)))
        return cx, cy

    def draw_terrain(self, surface: pygame.Surface, cam_x: int, cam_y: int,
                     rows: tuple[int, int] | None = None) -> None:
        """只画地形格子 (BattleScene 战斗时复用). `rows=(y0,y1)` 只画这些行 (2.5D 按行交错用)."""
        if self.real_map is not None:
            self.real_map.draw_terrain(surface, cam_x, cam_y, rows)
            return
        sw, sh = surface.get_size()
        x_start = max(0, cam_x // TILE_W)
        y_start = max(0, cam_y // TILE_H)
        x_end = min(MAP_W, (cam_x + sw) // TILE_W + 1)
        y_end = min(MAP_H, (cam_y + sh) // TILE_H + 1)
        if rows is not None:
            y_start, y_end = max(y_start, rows[0]), min(y_end, rows[1])
        for y in range(y_start, y_end):
            for x in range(x_start, x_end):
                tile = TILES[self.grid[y][x]]
                rect = pygame.Rect(
                    x * TILE_W - cam_x, y * TILE_H - cam_y,
                    TILE_W, TILE_H,
                )
                pygame.draw.rect(surface, tile.color, rect)
                if tile.terrain in (TerrainType.TOWN, TerrainType.DUNGEON):
                    pygame.draw.rect(surface, (0, 0, 0), rect, 2)

    def _step_to(self, dx: int, dy: int) -> tuple[int, int] | None:
        """玩家朝 (dx,dy) 走一步的落点 (原版规则: 实心/出边/坡口切层/崖梯跨格/斜梯), 不能走 → None.
        传送点格一律可踩 (触发传送); NPC/宝箱挡路由 passable_at 管."""
        nx, ny = self.player_x + dx, self.player_y + dy
        if self.real_map is None:
            return (nx, ny) if self.passable_at(nx, ny) else None
        if (nx, ny) in self._transitions:
            return (nx, ny) if self.passable_at(nx, ny) else None
        ok, z, mx, my = self.real_map.move(self.player_x, self.player_y, dx, dy, self.player_z)
        if not ok or not self.passable_at(mx, my, z):
            return None
        self.player_z = z
        return (mx, my)

    def passable_at(self, x: int, y: int, layer: int | None = None) -> bool:
        if (x, y) in self._transitions:         # 出入口(门/台阶): 可踩上以触发传送/进出
            return True
        if chests_mod.chest_at(self.location_base, x, y) is not None:
            return False                        # 宝箱是实物: 挡路, 面对它开 (2026-09-29 用户反馈)
        if self.npc_layer.blocks(x, y):         # 可交谈角色挡路 (面前空格 = 触发对白)
            return False
        if self.real_map is not None:
            return self.real_map.passable(
                x, y, layer if layer is not None else getattr(self, "player_z", None))
        if not (0 <= x < MAP_W and 0 <= y < MAP_H):
            return False
        return TILES[self.grid[y][x]].passable

    # ------- 地图角色 (A 接入: 原版 .mfo pcpos/jmp) -------
    def _update_npc_hint(self) -> None:
        """玩家面前那格有可交谈角色 → 底部显示其台词首句."""
        fx = self.player_x + self.facing[0]
        fy = self.player_y + self.facing[1]
        if (fx, fy) == self._hint_tile:
            return
        self._hint_tile = (fx, fy)
        npc = self.npc_layer.at(fx, fy)
        talk = npc is not None and self.npc_layer.blocks(fx, fy)
        if talk:
            # 转身面向玩家 (朝向 d: 0下 1右 2上 3左)
            npc["d"] = {(0, 1): 0, (1, 0): 1, (0, -1): 2, (-1, 0): 3}.get(
                (-self.facing[0], -self.facing[1]), npc.get("d", 0))
        self.npc_layer.set_hint(npc if talk else None)

    def _play_beat_bgm(self, msgs) -> None:
        """按过场剧本里的 <BGMnn> 切到该段剧情的原版曲子."""
        for m in msgs or ():
            n = m.get("bgm")
            if n is None:
                continue
            from core.bgm_table import bgm_file
            wav = bgm_file(n)
            if wav:
                try:
                    self.audio.play_bgm(wav)
                except Exception:
                    pass
            return

    def _restore_map_bgm(self) -> None:
        """过场播完回到地图: 还原地图曲."""
        try:
            self.audio.play_bgm("world1.wav")
        except Exception:
            pass

    def _sfx(self, sound_id: int) -> None:
        """播原版音效; 缺文件由 AudioManager 静默忽略, 绝不阻断游戏."""
        try:
            self.audio.play_sfx_id(sound_id)
        except Exception:
            pass

    def _finish_beat(self, beat) -> None:
        """结算剧情节点: 置进度/入队 + 原版 flag 音效."""
        self.story.apply_postbattle(beat, self.save)
        self._sfx(SFX_FLAG_ON)

    def _chain_next_beat(self) -> None:
        """一段开篇剧情演完后, 自动接续下一个"无地点约束"节点 (序章 → 第1章 等).

        地点剧情不再自动接续 —— 改为面对 NPC 按空格触发 (见 _talk_to)。
        """
        if self.next_scene is not None:
            return                       # 已有待切场景 (战斗/过场/店铺) → 不抢
        cur = self.story.current()
        if cur is not None and not cur.enter:
            print(f"[剧情] 自动接续 → {cur.title}")
            self._launch_beat(cur)

    def _after_beat(self, beat) -> None:
        """一段剧情 (对白/过场) 结束: 结算 + 还原地图曲 + 自动接续下一段."""
        self._finish_beat(beat)
        self._restore_map_bgm()
        self._chain_next_beat()

    def _facing_npc(self) -> dict | None:
        """面前那格的可交谈角色 (面朝判定, 不用走上去)."""
        fx = self.player_x + self.facing[0]
        fy = self.player_y + self.facing[1]
        n = self.npc_layer.at(fx, fy)
        return n if n is not None and self.npc_layer.blocks(fx, fy) else None

    def _interact(self) -> None:
        """空格交互: 优先与面前角色交谈, 否则开面前的/脚下的宝箱."""
        npc = self._facing_npc()
        if npc is not None:
            self._talk_to(npc)
            return
        self._try_open_chest()

    def _is_cutscene(self, msgs) -> bool:
        """带原版立绘的过场 → 全屏演出; 纯文字对白 → 底部对话框."""
        return any(m.get("portraits") for m in msgs or ())

    def _capture_backdrop(self):
        """抓当前地图画面作过场背景 (原版过场就在场景里播, 用真实资源不造图)."""
        try:
            snap = pygame.Surface(self.surface.get_size())
            old, self.surface = self.surface, snap
            self._no_hud = True                 # 对白背景: 只留地图+角色, 不画 HUD
            try:
                self.draw()
            finally:
                self.surface = old
                self._no_hud = False
            return snap
        except Exception:
            return None

    def _story_scene(self, msgs, title, on_close):
        """剧情演出统一入口: 带立绘 → 全屏过场, 否则底部对话框."""
        if self._is_cutscene(msgs):
            from scenes.cutscene import CutsceneScene
            return CutsceneScene(self.surface, return_scene=self, messages=msgs,
                                 title=title, on_close=on_close,
                                 backdrop=self._capture_backdrop(), audio=self.audio)
        from scenes.dialogue import DialogueScene
        return DialogueScene(self.surface, return_scene=self, messages=msgs,
                             title=title, on_close=on_close,
                             backdrop=self._capture_backdrop())

    def _launch_beat(self, beat) -> None:
        """按导演计划演出一个剧情节点 (B): 对白 → (剧情战斗) → 置进度/入队/结局.

        同时供手动 G 与世界地图自动触发复用。
        """
        # 序章: 有 exe 提取的序章数据 (tools.extract_prologue / extract_event_scenes) 就按原版分场景演出
        if beat.id == "intro":
            from scenes import prologue as prologue_scene
            if prologue_scene.available():
                self.story.apply_presave(beat, self.save)
                self.next_scene = prologue_scene.PrologueScene(
                    self.surface, return_scene=self, audio=self.audio,
                    on_close=lambda: self._after_beat(beat))
                print(f"[剧情] {beat.title} — 原版序章演出 (事件脚本)")
                return
        plan = self.story.plan(beat, self.save)
        if not plan["affordable"]:
            print(f"[剧情] 金钱不足 ({beat.cost}G): {beat.title}")
            self._story_toast = f"需要 {beat.cost}G：{beat.hint}"
            self._story_toast_t = 2600
            return
        # 前置结算: 扣花费 (flag 在 mark_done 后才置, 战斗失败不会解锁后续)
        self.story.apply_presave(beat, self.save)
        msgs = plan["messages"]
        # 原版过场曲: 全屏过场由场景自管 BGM (逐句切, 见 CutsceneScene);
        # 底部对话框这条路径由这里统一播一次首曲, 播完 on_close 还原地图曲
        if not self._is_cutscene(msgs):
            self._play_beat_bgm(msgs)

        if beat.ending:
            if msgs:
                self.next_scene = self._story_scene(
                    msgs, beat.title, lambda: self._enter_ending())
            else:
                self._enter_ending()
            return

        if plan["battle"]:
            if msgs:
                self.next_scene = self._story_scene(
                    msgs, beat.title, lambda: self._start_story_battle(beat))
            else:
                self._start_story_battle(beat)
            self._story_toast = f"⚔ {beat.title}"
            self._story_toast_t = 2600
            print(f"[剧情] {beat.title} — 战斗节点")
            return

        # 纯对白节点: 播完即完成 + 入队 (结束自动接续同图下一个节点)
        if msgs:
            self.next_scene = self._story_scene(
                msgs, beat.title, lambda: self._after_beat(beat))
            self._story_toast = f"▶ {beat.title}"
            self._story_toast_t = 2600
            print(f"[剧情] {beat.title} — {len(msgs)} 条对白")
            return

        # 无对白无战斗: 直接完成
        self._finish_beat(beat)
        self._story_toast = f"▶ {beat.title}"
        self._story_toast_t = 2600

    def _start_story_battle(self, beat) -> None:
        """按节点配置的敌人开一场剧情战斗; 胜利后由 _on_story_battle_end 结算入队."""
        from scenes.world_map.battle_launch import start_battle, make_story_enemy
        spec = beat.battle or {}
        enemies = [make_story_enemy(n) for n in spec.get("enemies", [])]
        if not enemies:
            enemies = [make_story_enemy("妖怪"), make_story_enemy("妖怪")]
        self._post_battle_beat = beat
        start_battle(self, enemies)

    def _on_story_battle_end(self, won: bool) -> None:
        """战斗结束回调 (由 BattleScene 在返回地图前调用). 胜利才结算该节点。"""
        beat = self._post_battle_beat
        self._post_battle_beat = None
        if beat is None:
            return
        if not won:
            self._story_toast = "战斗失败，重试即可"
            self._story_toast_t = 2200
            return
        self._finish_beat(beat)
        join = beat.join
        joined = ""
        if join:
            names = list(join) if isinstance(join, (tuple, list)) else [join]
            joined = "，" + "、".join(names) + " 加入队伍！"
        self._story_toast = f"✔ {beat.title}{joined}"
        self._story_toast_t = 2800
        print(f"[剧情] 战斗胜利，完成节点 {beat.id}{joined}")
        self._chain_next_beat()          # 战斗胜利后自动接续同图下一个节点

    def _enter_ending(self) -> None:
        from scenes.ending import EndingScene
        self.next_scene = EndingScene(self.surface, self.audio,
                                     self.story.ending_text(), return_scene=self)

    def _advance_story(self) -> None:
        """手动推进主线剧情 (B): 播放当前可推进节点的演出 (G 键).

        优先当前地图关联的节点 (与自动触发一致); 无则回退到无地点约束节点 (序章等),
        免得在 A 地图把 B 地图的剧情提前演掉。
        """
        beat = self.story.beat_for_location(self.location_base)
        if beat is None:
            cur = self.story.current()
            beat = cur if (cur is not None and not cur.enter) else None
        if beat is None:
            if self.story.is_complete():
                self._story_toast = "★ 已通关 · 主线全通"
            else:
                self._story_toast = "当前无可推进的剧情"
            self._story_toast_t = 2200
            return
        self._launch_beat(beat)

    def _talk_to(self, npc: dict) -> None:
        """面对 NPC 按空格: 店老板开店 / 本图有可推进剧情则演剧情 / 否则播该角色对白."""
        # 说话声: 原版按角色固定一种语音 (se__TALK1..7), 这里按 key 稳定分配
        key = npc.get("script")
        if key is None:                    # 事件角色/手工NPC 无 script, 用名字求 key
            key = sum(ord(c) for c in str(npc.get("name") or ""))
        self._sfx(SFX_TALK[abs(int(key)) % len(SFX_TALK)])
        # 1) 店老板: 面对面按空格 → 开店
        if npc.get("shop"):
            from scenes.shop import ShopScene
            self.next_scene = ShopScene(self.surface, self, self.location_base, self.save)
            return
        # 2) 关键剧情对话: 本图若有可推进节点 → 演出剧情 (读完即推进后续)
        beat = self.story.beat_for_location(self.location_base)
        if beat is not None:
            self._launch_beat(beat)
            return
        # 3) 手工 NPC (村民/居民): 播自身台词
        if npc.get("_authored"):
            lines = npc.get("lines") or []
            if lines:
                from scenes.dialogue import DialogueScene
                self.next_scene = DialogueScene(
                    self.surface, return_scene=self,
                    messages=[{"scene": f"npc:{npc.get('name')}",
                               "speaker": npc.get("name"), "face": npc.get("sprite"),
                               "text": t, "tags": [], "cmds": []} for t in lines],
                    title=npc.get("name") or "对话",
                    backdrop=self._capture_backdrop())
            return
        # 剧情事件角色 (五行山人物): 播自身台词
        if npc.get("_evt"):
            line = npc.get("line")
            if not line:
                return
            from scenes.dialogue import DialogueScene
            self.next_scene = DialogueScene(
                self.surface, return_scene=self,
                messages=[{"scene": f"event:{npc.get('name')}",
                           "speaker": npc.get("name"), "face": npc.get("name"),
                           "text": line, "tags": [], "cmds": []}],
                title=npc.get("name") or "角色",
                backdrop=self._capture_backdrop())
            return
        script_id = npc.get("script")
        msgs = to_messages(script_id) if script_id is not None else []
        if not msgs:
            print(f"[NPC] script={script_id} 无对白数据")
            return
        from scenes.dialogue import DialogueScene
        self.next_scene = DialogueScene(
            self.surface, return_scene=self, messages=msgs,
            title=f"{self.location_base} · 角色 {script_id}")

    # ------- 宝箱 (B: 数据驱动, 位置来自 .map 对象层, 内容待 exe/攻略校准) -------
    def _chest_target(self) -> tuple[int, int] | None:
        """面前那格 / 当前所站格的宝箱坐标 (优先面前)."""
        fx, fy = self.player_x + self.facing[0], self.player_y + self.facing[1]
        if chests_mod.chest_at(self.location_base, fx, fy) is not None:
            return fx, fy
        if chests_mod.chest_at(self.location_base, self.player_x, self.player_y) is not None:
            return self.player_x, self.player_y
        return None

    def _update_chest_hint(self) -> None:
        t = self._chest_target()
        if t is None:
            self._chest_hint = None
            return
        c = chests_mod.chest_at(self.location_base, t[0], t[1])
        if c is not None and chests_mod.is_opened(self.save, self.location_base, t[0], t[1]):
            self._chest_hint = None
        else:
            self._chest_hint = t

    def _try_open_chest(self) -> None:
        t = self._chest_target()
        if t is None:
            return
        c = chests_mod.chest_at(self.location_base, t[0], t[1])
        if c is None:
            return
        if chests_mod.is_opened(self.save, self.location_base, t[0], t[1]):
            self._story_toast = "（已经空了）"
            self._story_toast_t = 1600
            return
        c = dict(c)
        c["map"] = self.location_base
        msg = chests_mod.open_chest(self.save, c)
        print(f"[宝箱] {self.location_base} ({t[0]},{t[1]}): {msg}")
        self._story_toast = f"✦ {msg}"
        self._story_toast_t = 2600
        self._chest_hint = None
        # 原版开箱: 开箱声 + (有东西时) 获得道具声
        self._sfx(SFX_BOX_OPEN)
        if msg.startswith("获得"):
            self._sfx(SFX_ITEM_GET)
        # 背包有变化 → 尝试落盘 (原版尾部 trailer; 不影响原版读取)
        if self.save is not None:
            try:
                from core.save_manager import save_save
                import os
                path = getattr(self.save, "_path", None)
                if path and os.path.exists(path):
                    save_save(self.save, path)
            except Exception:
                pass

    def _draw_player(self, cx: int, cy: int) -> None:
        """画玩家队长 (由 draw() 在其所在行调用, 保证 2.5D 遮挡顺序)."""
        px = self.player_x * TILE_W + self.subpx
        py = self.player_y * TILE_H + self.subpy
        if self._leader_sprite is None:
            # 兜底: 精灵缺失时用纯色块代表玩家, 保证不崩
            pygame.draw.rect(
                self.surface, self.PLAYER_COLOR,
                pygame.Rect(int(px - cx + TILE_W // 4), int(py - cy + TILE_H // 4),
                           TILE_W // 2, TILE_H // 2),
            )
            return
        frame, anchor = pick_locomotion_frame(
            self._leader_sprite, None, self.facing, self._anim,
            walk_period_ms=WALK_FRAME_PERIOD_MS,
        )
        # 脚点对齐 tile 中心
        blit_unit(
            self.surface, frame, anchor,
            tile_center_x=int(px - cx + TILE_W // 2),
            tile_center_y=int(py - cy + TILE_H // 2),
        )

    def _draw_chests(self, surface: pygame.Surface, cx: int, cy: int,
                     rows: tuple[int, int] | None = None) -> None:
        """宝箱画**原版精灵** (assets/sprites/fm_BOX__SPR.png, 64x64/帧, 品红底).

        未开 = 关盖帧; **已开 = 开盖帧** (2026-09-29 用户反馈: 开完不该消失,
        应留在原地变成打开状态, 且不能再开 —— 不能再开由 chests.is_opened 挡住)。
        `rows` = 只画这些行 (逐行交错用, 让南侧地形能遮挡宝箱)。
        """
        spr_closed = _chest_sprite(False)
        spr_open = _chest_sprite(True)
        for c in self.chests:
            if rows is not None and not (rows[0] <= c["y"] < rows[1]):
                continue
            opened = chests_mod.is_opened(self.save, self.location_base, c["x"], c["y"])
            tx = c["x"] * TILE_W - cx
            ty = c["y"] * TILE_H - cy
            if not (-TILE_W * 2 <= tx <= surface.get_width() and -TILE_H * 2 <= ty <= surface.get_height()):
                continue
            spr = spr_open if opened else spr_closed
            if spr is None:                      # 精灵缺失时退回圆点 (仅未开的画), 保证不崩
                if not opened:
                    pygame.draw.circle(surface, (255, 220, 40), (tx + TILE_W // 2, ty + 6), 5)
                continue
            # 底边对齐格子底边、水平居中 (64x64 帧, 箱体在帧中下部)
            surface.blit(spr, (tx + TILE_W // 2 - spr.get_width() // 2,
                               ty + TILE_H - spr.get_height()))

    def draw(self) -> None:
        """2.5D 逐行交错绘制 (painter 顺序).

        每个可见行按 "地图行 → 该行实体(NPC / 玩家 / 宝箱) → 该行覆盖层" 依次画，
        于是**南侧**的桥板 / 墙沿 / 树冠会正确遮住角色与北侧物体
        (2026-09-29 用户实测: 站在桥上应被桥板挡住; 站墙沿应半身藏在墙后)。
        整张图一次性画完做不到这点 —— 角色会永远压在墙/桥上面。
        """
        self.surface.fill((0, 0, 0))
        cx, cy = self._camera_offset()
        sh = self.surface.get_height()
        m = self.real_map
        y0 = max(0, cy // TILE_H)
        y1 = (cy + sh) // TILE_H + 1
        if m is not None:
            y1 = min(y1, m.h)
        for y in range(y0, y1):
            self.draw_terrain(self.surface, cx, cy, rows=(y, y + 1))
            self.npc_layer.draw(self.surface, cx, cy, self.font, y_from=y, y_to=y)
            if y == self.player_y:
                self._draw_player(cx, cy)
            self._draw_chests(self.surface, cx, cy, rows=(y, y + 1))
            if m is not None:
                # 高物件 (墙/屋顶/树/桥) 按基线行盖在该行实体之上 (原版 FUN_004b8aa9)
                m.draw_tall(self.surface, cx, cy, y, self.player_z)
                # 高处层里标"画在角色上"的瓦片
                if ENABLE_OVERLAY:
                    m.draw_overlay(self.surface, cx, cy, rows=(y, y + 1))

        if not self._no_hud:
            self._draw_hud()
            if self._dbg_tile:
                self._draw_tile_debug()

    def _draw_tile_debug(self) -> None:
        """F3 调试叠加: 本格与四邻的 tile(网格A) / flag(网格B高16) / 覆盖层(低16) / 可走判定。

        用户报"能站到墙上/走不进去"时, 站到那一格按 F3, 把面板内容发出来即可精确定位。
        """
        if self.real_map is None:
            return
        m, px, py = self.real_map, self.player_x, self.player_y

        def cell(x: int, y: int) -> str:
            if not m.in_bounds(x, y):
                return "出界"
            i = y * m.w + x
            verdict = "可走" if self.passable_at(x, y) else "不可走"
            return (f"tile={m.grid[i]:3d} flag={m.flag(x, y):2d} "
                    f"ov={m.attr[i] & 0xFFFF:3d} {verdict}")

        lines = [f"[F3] {self.location_base} 玩家格({px},{py})  {cell(px, py)}"]
        for name, (dx, dy) in (("上", (0, -1)), ("下", (0, 1)), ("左", (-1, 0)), ("右", (1, 0))):
            lines.append(f"    {name}({px + dx},{py + dy}) {cell(px + dx, py + dy)}")
        sw, sh = self.surface.get_size()
        pad, lh = 8, self.small.get_height() + 2
        panel = pygame.Surface((sw, pad * 2 + lh * len(lines)), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 205))
        self.surface.blit(panel, (0, sh - panel.get_height()))
        for k, t in enumerate(lines):
            self.surface.blit(self.small.render(t, True, (130, 255, 160)),
                              (pad, sh - panel.get_height() + pad + k * lh))

    def _draw_hud(self) -> None:
        sw, sh = self.surface.get_size()
        # 三行: ①地点/金钱/地图/角色/位置/步数 + 队伍(右对齐) ②剧情 ③按键提示(右对齐, 小字)
        # ⚠ 别再把长按键提示和右对齐的"队伍"挤同一行 —— 两者会叠字, 看着像乱码
        hud = pygame.Surface((sw, HUD_H), pygame.SRCALPHA)
        hud.fill(self.HUD_BG)
        self.surface.blit(hud, (0, 0))
        loc = self.save.location if self.save else "未读取存档"
        money = self.save.money if self.save else 0
        npc = (f"角色 {self.npc_layer.dialogue_count}/{self.npc_layer.count}"
               if self.npc_layer.count else "无角色")
        info = (f"地点: {loc}    金钱: {money}    地图: {self.location_base}    {npc}    "
                f"位置: ({self.player_x},{self.player_y})    步数: {self.steps}")
        self.surface.blit(self.font.render(info, True, self.HUD_TEXT), (10, 6))
        party = self.font.render(f"队伍: {self.story.party_text()}", True, (200, 230, 255))
        self.surface.blit(party, (sw - party.get_width() - 12, 6))
        self.surface.blit(
            self.font.render(f"剧情: {self.story.progress_text()}", True, (255, 236, 130)),
            (10, 32))
        keys = self.small.render(HUD_KEYS, True, (188, 188, 210))
        self.surface.blit(keys, (sw - keys.get_width() - 12, HUD_H - 24))

        # 面前角色的台词预告 (撞上去就播这段原版对白)
        hint = self.npc_layer.hint()
        if hint is not None:
            line, _pos = hint
            bar = pygame.Surface((sw, 34), pygame.SRCALPHA)
            bar.fill((0, 0, 0, 176))
            self.surface.blit(bar, (0, sh - 34))
            self.surface.blit(self.font.render(f"▶ {line}", True, (255, 236, 130)),
                              (12, sh - 29))
            tip = self.font.render("走上去交谈", True, (176, 170, 200))
            self.surface.blit(tip, (sw - tip.get_width() - 12, sh - 29))

        # 面前宝箱提示
        if self._chest_hint is not None:
            bar = pygame.Surface((sw, 34), pygame.SRCALPHA)
            bar.fill((0, 40, 60, 190))
            self.surface.blit(bar, (0, sh - 34))
            self.surface.blit(self.font.render("▣ 宝箱", True, (120, 230, 255)),
                              (12, sh - 29))
            tip = self.font.render("[空格] 开启", True, (120, 230, 255))
            self.surface.blit(tip, (sw - tip.get_width() - 12, sh - 29))
        elif self._facing_npc() is not None:
            # 面前有可交谈角色 → 提示用空格说话
            bar = pygame.Surface((sw, 34), pygame.SRCALPHA)
            bar.fill((40, 25, 10, 190))
            self.surface.blit(bar, (0, sh - 34))
            who = self._facing_npc().get("name") or "人"
            self.surface.blit(self.font.render(f"▣ {who}", True, (255, 226, 160)),
                              (12, sh - 29))
            tip = self.font.render("[空格] 交谈", True, (255, 226, 160))
            self.surface.blit(tip, (sw - tip.get_width() - 12, sh - 29))

        # 剧情触发提示 (自动触发 / 手动 G 时闪一下)
        if self._story_toast:
            bar = pygame.Surface((sw, 38), pygame.SRCALPHA)
            bar.fill((40, 20, 60, 200))
            self.surface.blit(bar, (0, sh - 38 - 34))
            self.surface.blit(
                self.font.render(self._story_toast, True, (255, 226, 160)),
                (14, sh - 33 - 34))
