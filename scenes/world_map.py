"""世界地图场景: 30x30 占位 tile, WASD/方向键移动, 镜头跟随玩家."""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

import pygame

from core.audio_manager import AudioManager
from core.battle import BattleMap, BattleUnit, TacticsBattle, make_enemy, unit_from_character
from core.character import CHARACTER_NAMES, PLAYABLE_SLOTS
from core.character_sprites import sprite_resource
from core.movement_input import DirectionalHold
from core.save_manager import SaveData
from core.sprites import facing_to_direction, get_character_sprite
from scenes.base import Scene
from scenes.menu import load_chinese_font

TILE_SIZE = 48
MAP_W = 30
MAP_H = 30
WALK_SPEED_PX_PER_SEC = 480.0   # 10 tile/秒 (= TILE_SIZE * 10)
WALK_FRAME_PERIOD_MS = 80        # 行走动画切换间隔
TURN_FRAME_DURATION_MS = 40      # 90° 转向时显示过渡帧的时长
WALK_HOLD_DELAY_MS = 80          # 按住方向键超过这时间后才自动连走 (tap 只转向)
RANDOM_BATTLE_EVERY = 3
RANDOM_BATTLE_CHANCE = 0.00
PARTY_SIZE = 4


class TerrainType(Enum):
    GRASS = "grass"
    WATER = "water"
    MOUNTAIN = "mountain"
    TOWN = "town"
    DUNGEON = "dungeon"


@dataclass(frozen=True)
class Tile:
    terrain: TerrainType
    color: tuple[int, int, int]
    passable: bool


TILES: dict[TerrainType, Tile] = {
    TerrainType.GRASS:    Tile(TerrainType.GRASS,    (76, 160, 80),   True),
    TerrainType.WATER:    Tile(TerrainType.WATER,    (50, 100, 200),  False),
    TerrainType.MOUNTAIN: Tile(TerrainType.MOUNTAIN, (130, 130, 130), False),
    TerrainType.TOWN:     Tile(TerrainType.TOWN,     (220, 200, 80),  True),
    TerrainType.DUNGEON:  Tile(TerrainType.DUNGEON,  (180, 60, 60),   True),
}


def _build_test_map() -> list[list[TerrainType]]:
    """30x30 测试地图: 边缘水, 中部山脉带, 散布城镇/地牢."""
    G, W, M, T, D = (
        TerrainType.GRASS, TerrainType.WATER, TerrainType.MOUNTAIN,
        TerrainType.TOWN, TerrainType.DUNGEON,
    )
    grid = [[G for _ in range(MAP_W)] for _ in range(MAP_H)]

    # 边缘一圈水
    for x in range(MAP_W):
        grid[0][x] = grid[MAP_H - 1][x] = W
    for y in range(MAP_H):
        grid[y][0] = grid[y][MAP_W - 1] = W

    # 中部一条山脉带 (留缺口)
    for x in range(3, MAP_W - 3):
        if x in (10, 11, 18, 19):
            continue  # 通行缺口
        grid[14][x] = M
        grid[15][x] = M

    # 几个城镇
    for (x, y) in [(5, 5), (24, 6), (8, 22), (22, 24)]:
        grid[y][x] = T

    # 两个地牢
    for (x, y) in [(15, 8), (5, 18)]:
        grid[y][x] = D

    return grid


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
        self.grid = _build_test_map()
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
        self._anim_time_ms = 0    # 行走动画时间 (移动中累加, 静止归零)
        # 90° 转向过渡帧状态
        self._turn_remaining_ms = 0
        self._turn_from_facing: tuple[int, int] | None = None
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
        self._anim_time_ms = 0
        self._turn_remaining_ms = 0
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
        if self._turn_remaining_ms > 0:
            self._turn_remaining_ms = max(0, self._turn_remaining_ms - dt_ms)
        if self.moving_dir != (0, 0):
            self._advance_movement(dt_ms)
        # 战斗触发: 跳过本帧后续的输入轮询, 避免按键续写出残留 moving 状态被冻结
        if self.next_scene is not None:
            return
        # 到位 (或本来静止) 后, 检查输入是否要开始下一格移动.
        if self.moving_dir == (0, 0):
            self._poll_input_for_next_step(dt_ms)

    def _advance_movement(self, dt_ms: int) -> None:
        """像素级推进 subpx/subpy 朝 (0,0). 到位后落地到目标 tile 并触发战斗判定."""
        step = WALK_SPEED_PX_PER_SEC * (dt_ms / 1000.0)
        # subpx/y 符号与 moving_dir 相反 (从前一格滑入), 朝 0 收敛
        if self.subpx != 0:
            if abs(self.subpx) <= step:
                self.subpx = 0.0
            else:
                self.subpx += step if self.subpx < 0 else -step
        if self.subpy != 0:
            if abs(self.subpy) <= step:
                self.subpy = 0.0
            else:
                self.subpy += step if self.subpy < 0 else -step
        self._anim_time_ms += dt_ms
        if self.subpx == 0 and self.subpy == 0:
            self.moving_dir = (0, 0)
            self.steps += 1
            self._maybe_trigger_battle()

    def _poll_input_for_next_step(self, dt_ms: int) -> None:
        """复刻原版语义: 引擎里 <DIR> 与 <WALK> 是独立 primitive.
        tap 仅转向; 持续按住超 WALK_HOLD_DELAY_MS 才自动连走.
        见 core.movement_input.DirectionalHold.
        """
        if self._input_gated:
            self._hold.reset()
            self._anim_time_ms = 0
            return
        keys = pygame.key.get_pressed()
        dx = (keys[pygame.K_RIGHT] or keys[pygame.K_d]) - (keys[pygame.K_LEFT] or keys[pygame.K_a])
        dy = (keys[pygame.K_DOWN]  or keys[pygame.K_s]) - (keys[pygame.K_UP]   or keys[pygame.K_w])
        if dx == 0 and dy == 0:
            self._hold.reset()
            self._anim_time_ms = 0
            return
        if dx != 0:  # 优先水平, 避免对角斜跳
            dy = 0
        new_dir = (dx, dy)
        edge = self._hold.tick(new_dir, dt_ms)

        if new_dir != self.facing:
            # 朝向不一致: 边沿时转身 (含过渡帧), 不前进
            if edge:
                old_facing = self.facing
                self.facing = new_dir
                if self._leader_sprite.turn_frame(
                    facing_to_direction(old_facing), facing_to_direction(new_dir)
                ) is not None:
                    self._turn_from_facing = old_facing
                    self._turn_remaining_ms = TURN_FRAME_DURATION_MS
            self._anim_time_ms = 0
            return

        # 朝向已对齐: 是否走一步
        if not self._hold.should_walk(edge, WALK_HOLD_DELAY_MS):
            self._anim_time_ms = 0
            return
        nx, ny = self.player_x + dx, self.player_y + dy
        if 0 <= nx < MAP_W and 0 <= ny < MAP_H and TILES[self.grid[ny][nx]].passable:
            self.player_x, self.player_y = nx, ny
            self.subpx = -dx * TILE_SIZE
            self.subpy = -dy * TILE_SIZE
            self.moving_dir = (dx, dy)
        else:
            # 撞墙: 原地踏步动画, 帧继续切换
            self._anim_time_ms += dt_ms

    # ------- 渲染 -------
    def camera_offset_for(self, focus_x: int, focus_y: int) -> tuple[int, int]:
        """让 (focus_x, focus_y) 这格在屏幕中心, 边缘夹紧."""
        sw, sh = self.surface.get_size()
        cx = focus_x * TILE_SIZE + TILE_SIZE // 2 - sw // 2
        cy = focus_y * TILE_SIZE + TILE_SIZE // 2 - sh // 2
        max_cx = MAP_W * TILE_SIZE - sw
        max_cy = MAP_H * TILE_SIZE - sh
        cx = max(0, min(cx, max(0, max_cx)))
        cy = max(0, min(cy, max(0, max_cy)))
        return cx, cy

    def _camera_offset(self) -> tuple[int, int]:
        # 用像素位置 (含 subpx/y) 让相机跟随平滑
        sw, sh = self.surface.get_size()
        focus_px = self.player_x * TILE_SIZE + self.subpx + TILE_SIZE / 2
        focus_py = self.player_y * TILE_SIZE + self.subpy + TILE_SIZE / 2
        cx = int(focus_px - sw / 2)
        cy = int(focus_py - sh / 2)
        max_cx = MAP_W * TILE_SIZE - sw
        max_cy = MAP_H * TILE_SIZE - sh
        cx = max(0, min(cx, max(0, max_cx)))
        cy = max(0, min(cy, max(0, max_cy)))
        return cx, cy

    def draw_terrain(self, surface: pygame.Surface, cam_x: int, cam_y: int) -> None:
        """只画地形格子 (BattleScene 战斗时复用)."""
        sw, sh = surface.get_size()
        x_start = max(0, cam_x // TILE_SIZE)
        y_start = max(0, cam_y // TILE_SIZE)
        x_end = min(MAP_W, (cam_x + sw) // TILE_SIZE + 1)
        y_end = min(MAP_H, (cam_y + sh) // TILE_SIZE + 1)
        for y in range(y_start, y_end):
            for x in range(x_start, x_end):
                tile = TILES[self.grid[y][x]]
                rect = pygame.Rect(
                    x * TILE_SIZE - cam_x, y * TILE_SIZE - cam_y,
                    TILE_SIZE, TILE_SIZE,
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

        # 玩家 sprite (脚点 anchor 同方向共用, 防止迈步时 sprite 左右晃)
        if self._turn_remaining_ms > 0 and self._turn_from_facing is not None:
            frame = self._leader_sprite.turn_frame(
                facing_to_direction(self._turn_from_facing),
                facing_to_direction(self.facing),
            )
            assert frame is not None
        else:
            anim_idx = int(self._anim_time_ms // WALK_FRAME_PERIOD_MS) % self._leader_sprite.walk_frames
            frame = self._leader_sprite.frame_for_facing(self.facing, anim_idx)
        feet_x, feet_y = self._leader_sprite.feet_for_facing(self.facing)
        px = self.player_x * TILE_SIZE + self.subpx
        py = self.player_y * TILE_SIZE + self.subpy
        # 脚点对齐 tile 中心 (而非 tile 底边), 角色上半身自然伸出 tile 上方
        blit_x = int(px - cx + TILE_SIZE / 2 - feet_x)
        blit_y = int(py - cy + TILE_SIZE / 2 - feet_y)
        self.surface.blit(frame, (blit_x, blit_y))

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

    # ------- 战斗触发 -------
    def _build_party(self) -> list[BattleUnit]:
        if self.save is not None:
            chars: list[BattleUnit] = []
            for slot in PLAYABLE_SLOTS:
                ch = self.save.characters.get(slot)
                if ch is None or ch.MaxHP <= 0:
                    continue
                chars.append(unit_from_character(CHARACTER_NAMES[slot], ch))
                if len(chars) >= PARTY_SIZE:
                    break
            if chars:
                return chars
        # 无存档时的默认队伍
        return [
            BattleUnit(name="美娜",   level=1, max_hp=60, hp=60, max_mp=20, mp=20, sg=15,
                       attack=18, defence=10, agile=30, move=3, is_player=True,
                       color=(120, 200, 230),
                       sprite_key=sprite_resource("美娜")),
            BattleUnit(name="孙悟空", level=1, max_hp=80, hp=80, max_mp=10, mp=10, sg=20,
                       attack=22, defence=12, agile=50, move=4, is_player=True,
                       color=(120, 200, 230),
                       sprite_key=sprite_resource("孙悟空")),
        ]

    def _maybe_trigger_battle(self) -> None:
        # 走到地牢: BOSS 战 (黄色怪)
        if TILES[self.grid[self.player_y][self.player_x]].terrain == TerrainType.DUNGEON:
            self._start_battle([make_enemy("黄色怪"), make_enemy("骷髅")])
            return
        # 每 N 步骰: 随机战斗
        if self.steps % RANDOM_BATTLE_EVERY == 0 and self.rng.random() < RANDOM_BATTLE_CHANCE:
            template = self.rng.choice(["骷髅", "乌鸦怪"])
            count = self.rng.randint(1, 2)
            enemies = [make_enemy(template) for _ in range(count)]
            self._start_battle(enemies)

    def _make_battle_map_from_world(self) -> BattleMap:
        """把整张世界地图当战场: 不可通行 (水/山) → 障碍物."""
        bm = BattleMap(MAP_W, MAP_H)
        for y in range(MAP_H):
            for x in range(MAP_W):
                if not TILES[self.grid[y][x]].passable:
                    bm.obstacles.add((x, y))
        return bm

    def _scatter_positions(
        self, center: tuple[int, int], count: int, ring_min: int, ring_max: int,
        avoid: set[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        """在 center 周围 ring_min..ring_max 步范围内挑 count 个空格."""
        cx, cy = center
        cands = []
        for r in range(ring_min, ring_max + 1):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if abs(dx) + abs(dy) != r:
                        continue
                    p = (cx + dx, cy + dy)
                    if not (0 <= p[0] < MAP_W and 0 <= p[1] < MAP_H):
                        continue
                    if not TILES[self.grid[p[1]][p[0]]].passable:
                        continue
                    if p in avoid:
                        continue
                    cands.append(p)
        self.rng.shuffle(cands)
        out: list[tuple[int, int]] = []
        for p in cands:
            if p in out:
                continue
            out.append(p)
            if len(out) >= count:
                break
        return out

    def _start_battle(self, enemies: list[BattleUnit]) -> None:
        from scenes.battle_scene import BattleScene
        party = self._build_party()
        battle_map = self._make_battle_map_from_world()
        center = (self.player_x, self.player_y)

        # 玩家方在中心 + 周围 1-2 圈
        used: set[tuple[int, int]] = set()
        player_positions: list[tuple[int, int]] = [center]
        used.add(center)
        if len(party) > 1:
            extras = self._scatter_positions(center, len(party) - 1, 1, 2, used)
            for p in extras:
                used.add(p)
                player_positions.append(p)
            # 不够就硬塞 center (重叠); 一般 4 人队伍在 1-2 圈足够
            while len(player_positions) < len(party):
                player_positions.append(center)

        # 敌人在外圈 4-7 步
        enemy_positions = self._scatter_positions(center, len(enemies), 4, 7, used)
        # 不够就再放宽
        if len(enemy_positions) < len(enemies):
            more = self._scatter_positions(center, len(enemies), 8, 12, used | set(enemy_positions))
            enemy_positions.extend(more)
        while len(enemy_positions) < len(enemies):
            # 兜底: 找任意空格
            for y in range(MAP_H):
                for x in range(MAP_W):
                    if (x, y) not in used and TILES[self.grid[y][x]].passable:
                        enemy_positions.append((x, y))
                        used.add((x, y))
                        if len(enemy_positions) >= len(enemies):
                            break
                if len(enemy_positions) >= len(enemies):
                    break
            break  # 防止死循环

        battle = TacticsBattle(
            party, enemies,
            battle_map=battle_map,
            rng=self.rng,
            player_positions=player_positions,
            enemy_positions=enemy_positions,
        )
        self.next_scene = BattleScene(
            self.surface, self.audio, battle,
            world_map=self, return_scene=self,
        )
