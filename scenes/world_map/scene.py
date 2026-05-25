"""世界地图场景: 30x30 占位 tile, WASD/方向键移动, 镜头跟随玩家.

战斗触发逻辑在 battle_launch.py, 地形数据在 terrain.py.
"""

from __future__ import annotations

import random

import pygame

from core.anim_state import AnimationState
from core.audio_manager import AudioManager
from core.character_sprites import sprite_resource
from core.movement_input import DirectionalHold
from core.save_manager import SaveData
from core.sprites.atlas_classes import idle_key_from_walk_key
from core.sprites.base import TILE_W, TILE_H
from core.sprites.loaders import get_character_sprite, get_idle_sprite
from scenes.base import Scene
from scenes.menu import load_chinese_font
from scenes.unit_render import blit_unit, pick_locomotion_frame
from scenes.world_map import battle_launch
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
        self.player_x = 3
        self.player_y = 3
        # 当前像素相对目标 tile 的偏移 (从前一格滑入时为负), 静止时 (0, 0).
        self.subpx = 0.0
        self.subpy = 0.0
        self.moving_dir: tuple[int, int] = (0, 0)
        self.font = load_chinese_font(20)
        self.steps = 0
        self.rng = random.Random()
        # 队长角色 sprite
        self.party_leader = "孙悟空"
        self.facing: tuple[int, int] = (0, 1)  # 初始朝下
        self._anim = AnimationState()
        # 输入门: 进/回到地图时, 必须松开方向键再按才接受 (防止战斗结束瞬间自动续走)
        self._input_gated = True
        # 方向键长按检测器 (tap 只转向 / 持续按住超阈值才连走)
        self._hold = DirectionalHold()
        self._leader_sprite = get_character_sprite(sprite_resource(self.party_leader))

    # ------- 生命周期 -------
    def on_enter(self) -> None:
        # 战斗回到地图时也走这: 重置所有移动残留状态, 重新锁住输入门
        self._input_gated = True
        self.moving_dir = (0, 0)
        self.subpx = 0.0
        self.subpy = 0.0
        self._anim.reset()
        self._hold.reset()
        try:
            self.audio.play_bgm("world1.wav")
        except FileNotFoundError as e:
            print(f"world BGM 缺失: {e}")

    # ------- 输入 -------
    DIR_KEYS = (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN,
                pygame.K_a, pygame.K_d, pygame.K_w, pygame.K_s)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            from scenes.menu import TitleScene
            self.next_scene = TitleScene(self.surface, self.audio)
            return True
        # 输入门只能由"全新按下"的方向键事件解开 (避免战斗返回时长按状态自动续走)
        if event.type == pygame.KEYDOWN and event.key in self.DIR_KEYS and self._input_gated:
            self._input_gated = False
        return True

    # ------- 更新 -------
    def update(self, dt_ms: int) -> None:
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
        if 0 <= nx < MAP_W and 0 <= ny < MAP_H and TILES[self.grid[ny][nx]].passable:
            self.player_x, self.player_y = nx, ny
            self.subpx = -dx * TILE_W
            self.subpy = -dy * TILE_H
            self.moving_dir = (dx, dy)
        else:
            # 撞墙: 原地踏步动画, 帧继续切换
            self._anim.tick(dt_ms, moving=True)

    # ------- 渲染 -------
    def camera_offset_for(self, focus_x: int, focus_y: int) -> tuple[int, int]:
        """让 (focus_x, focus_y) 这格在屏幕中心, 边缘夹紧."""
        sw, sh = self.surface.get_size()
        cx = focus_x * TILE_W + TILE_W // 2 - sw // 2
        cy = focus_y * TILE_H + TILE_H // 2 - sh // 2
        max_cx = MAP_W * TILE_W - sw
        max_cy = MAP_H * TILE_H - sh
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
        max_cx = MAP_W * TILE_W - sw
        max_cy = MAP_H * TILE_H - sh
        cx = max(0, min(cx, max(0, max_cx)))
        cy = max(0, min(cy, max(0, max_cy)))
        return cx, cy

    def draw_terrain(self, surface: pygame.Surface, cam_x: int, cam_y: int) -> None:
        """只画地形格子 (BattleScene 战斗时复用)."""
        sw, sh = surface.get_size()
        x_start = max(0, cam_x // TILE_W)
        y_start = max(0, cam_y // TILE_H)
        x_end = min(MAP_W, (cam_x + sw) // TILE_W + 1)
        y_end = min(MAP_H, (cam_y + sh) // TILE_H + 1)
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

    def passable_at(self, x: int, y: int) -> bool:
        if not (0 <= x < MAP_W and 0 <= y < MAP_H):
            return False
        return TILES[self.grid[y][x]].passable

    def draw(self) -> None:
        self.surface.fill((0, 0, 0))
        cx, cy = self._camera_offset()
        self.draw_terrain(self.surface, cx, cy)

        # 玩家 sprite — locomotion 状态机统一在 scenes.unit_render
        try:
            idle_sprite = get_idle_sprite(idle_key_from_walk_key(sprite_resource(self.party_leader)))
        except FileNotFoundError:
            idle_sprite = None
        # 世界地图静止用 walk col 0 (不接 06 idle 呼吸), 故 idle_sprite=None
        frame, anchor = pick_locomotion_frame(
            self._leader_sprite, None, self.facing, self._anim,
            walk_period_ms=WALK_FRAME_PERIOD_MS,
        )
        px = self.player_x * TILE_W + self.subpx
        py = self.player_y * TILE_H + self.subpy
        # 脚点对齐 tile 中心
        blit_unit(
            self.surface, frame, anchor,
            tile_center_x=int(px - cx + TILE_W // 2),
            tile_center_y=int(py - cy + TILE_H // 2),
        )

        self._draw_hud()

    def _draw_hud(self) -> None:
        # 半透明黑底
        hud = pygame.Surface((self.surface.get_width(), 36), pygame.SRCALPHA)
        hud.fill(self.HUD_BG)
        self.surface.blit(hud, (0, 0))
        loc = self.save.location if self.save else "未读取存档"
        money = self.save.money if self.save else 0
        text = self.font.render(
            f"地点: {loc}    金钱: {money}    位置: ({self.player_x},{self.player_y})    步数: {self.steps}    [ESC] 返回菜单",
            True, self.HUD_TEXT,
        )
        self.surface.blit(text, (10, 8))
