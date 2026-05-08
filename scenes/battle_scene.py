"""战棋战斗场景 (战斗发生在世界地图上, 不切场景).

操作:
  方向键   走 1 格 + 转面向 (走不了就只转身); 走过的格子计入本回合可达范围
  Enter    攻击当前面向格子上的敌人 (近战范围内). 没敌人则无动作.
  ESC      调出行动菜单 (上=攻击 / 右=技能 / 下=结束 / 左=道具)
           菜单内方向键直接选项, ESC 关闭
  X        撤销移动, 把角色拉回本回合起点
  朝向格高亮: 浅白 = 空格, 浅红 = 上面有敌人 (可 Enter 攻击)
  胜负后任意键返回地图.

视觉:
  - 复用 WorldMapScene 的地形渲染 (相同的世界格子)
  - 镜头跟随当前行动单位
  - 蓝色半透明: 可移动; 红色: 可攻击的敌人格
  - 头顶: 绿色 HP 数字, 下方蓝色 M{move}
  - 脚下椭圆阴影; 浮动伤害数字 (橙色 1 秒)
  - 左上 HUD: 当前 + 下一行动卡片
  - 底部: 战斗日志
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from core.audio_manager import AudioManager
from core.battle import BattleUnit, DamageEvent, LevelUpReport, Phase, TacticsBattle
from core.character import UNSET
from core.movement_input import DirectionalHold
from core.sprites import (
    DEFAULT_IDLE_DIRECTION_COLS,
    facing_to_direction,
    get_character_sprite,
    get_idle_sprite,
    idle_key_from_walk_key,
)
from scenes.base import Scene
from scenes.menu import load_chinese_font

if TYPE_CHECKING:
    from scenes.world_map import WorldMapScene

TILE = 48  # 世界 tile 大小, 与 world_map.TILE_SIZE 同步

# HUD
HUD_X = 12
HUD_Y = 12
HUD_W_CUR = 280
HUD_W_NEXT = 220

# 底部日志
LOG_H = 100


class FloatText:
    """浮动伤害数字: 绿色大伤害 + 蓝色小剩余 HP, 1.2 秒上升淡出 (对照原版 d090/f120)."""
    DURATION_MS = 1200
    RISE_PX = 32
    DAMAGE_COLOR = (90, 230, 110)    # 绿色
    HP_COLOR = (90, 170, 255)        # 蓝色

    MISS_COLOR = (220, 220, 220)     # 白色 MISS

    def __init__(self, damage: int, remaining_hp: int,
                 world_x: int, world_y: int, started_at: int,
                 miss: bool = False) -> None:
        self.damage = damage
        self.remaining_hp = remaining_hp
        self.world_x = world_x
        self.world_y = world_y
        self.started_at = started_at
        self.miss = miss

    def alive(self, now_ms: int) -> bool:
        return now_ms - self.started_at < self.DURATION_MS

    def draw(self, surface: pygame.Surface,
             big_font: pygame.font.Font, small_font: pygame.font.Font,
             cam_x: int, cam_y: int, now_ms: int) -> None:
        t = (now_ms - self.started_at) / self.DURATION_MS
        if t >= 1.0:
            return
        # 前 70% 不透明, 后 30% 淡出
        alpha = int(255 * (1.0 if t < 0.7 else (1.0 - (t - 0.7) / 0.3)))
        dy = int(self.RISE_PX * t)
        cx, cy = self.world_x - cam_x, self.world_y - cam_y - dy
        if self.miss:
            big = big_font.render("MISS", True, self.MISS_COLOR)
            big.set_alpha(alpha)
            surface.blit(big, big.get_rect(midbottom=(cx, cy)))
            return
        # 绿色伤害 (上)
        big = big_font.render(str(self.damage), True, self.DAMAGE_COLOR)
        big.set_alpha(alpha)
        big_rect = big.get_rect(midbottom=(cx, cy))
        surface.blit(big, big_rect)
        # 蓝色剩余 HP (紧贴下方)
        small = small_font.render(str(self.remaining_hp), True, self.HP_COLOR)
        small.set_alpha(alpha)
        small_rect = small.get_rect(midtop=(cx, big_rect.bottom - 2))
        surface.blit(small, small_rect)


class BattleScene(Scene):
    PANEL_BG = (28, 22, 40)
    PANEL_BORDER = (200, 180, 100)
    TEXT = (240, 240, 240)
    DIM = (160, 160, 160)
    HIGHLIGHT = (255, 240, 120)
    MOVE_TINT = (130, 100, 220, 110)   # 紫色, 对照原版 d055/d080
    ATK_TINT = (220, 60, 60, 110)
    FACE_EMPTY_TINT = (255, 255, 255, 110)   # 朝向空格 = 浅白
    FACE_ENEMY_TINT = (255, 120, 120, 140)   # 朝向敌人 = 浅红
    CURSOR_COLOR = (255, 240, 120)
    HP_NUM_COLOR = (140, 240, 140)
    MOVE_NUM_COLOR = (140, 200, 255)
    SHADOW = (0, 0, 0, 110)

    ENEMY_TURN_DELAY_MS = 350     # 走完 + 攻击命中后再停顿这么久
    CAMERA_LERP = 0.18            # 镜头平滑系数 (0=不移, 1=瞬移)
    UNIT_TILES_PER_SEC = 8.0      # 单位走动速度 (格/秒, 与世界地图节奏一致)
    WALK_FRAME_PERIOD_MS = 80     # 行走帧切换间隔
    TURN_FRAME_DURATION_MS = 40   # 90° 转向过渡帧时长
    IDLE_FRAME_PERIOD_MS = 400    # 待机呼吸帧切换间隔 (慢一点更自然)
    WALK_HOLD_DELAY_MS = 80       # 按住方向键超过此时长才自动连走 (tap 只转向)
    # 受击表现: 原版是硬切, 不做位移/混合插值. 只靠 reaction 帧本身的姿态 + 停留时长 +
    # 浮动伤害数字制造冲击感. 加位移插值反而违和 (角色保持躺姿却平移回原位).
    ANIM_EPSILON = 0.05           # render 与逻辑差小于此值视为已到位
    HUD_TOP_BUFFER = 96           # 镜头顶部预留 (px), 让 HUD 不挡角色
    LOG_BOTTOM_BUFFER = 116       # 镜头底部预留 (px), 让日志不挡角色

    def __init__(
        self,
        surface: pygame.Surface,
        audio: AudioManager,
        battle: TacticsBattle,
        world_map: "WorldMapScene",
        return_scene: Scene,
    ) -> None:
        super().__init__(surface)
        self.audio = audio
        self.battle = battle
        self.world_map = world_map
        self.return_scene = return_scene
        self.font = load_chinese_font(18)
        self.small = load_chinese_font(13)
        self.tiny = load_chinese_font(11)
        self.float_font = load_chinese_font(20)
        self.big = load_chinese_font(36)

        # 攻击目标光标已废弃: PLAYER_MOVE 阶段 Enter 攻击朝向格
        self._enemy_turn_started_at: int | None = None
        self._battle_over_signaled = False
        self._floats: list[FloatText] = []
        # 升级流程: VICTORY 后, 玩家按键先看完所有升级框, 才返回地图
        self._levelup_idx = 0           # 当前显示的升级报告下标 (-1 表已结束)
        self._victory_acknowledged = False   # 玩家已按过一次 (跳过胜利 banner)
        self._float_big = load_chinese_font(22)
        self._float_small = load_chinese_font(14)
        # 行动菜单: ESC 弹出十字 4 选项 (上=攻 / 右=技 / 下=终 / 左=道)
        self._menu_open = False
        self._menu_font = load_chinese_font(16)
        # 输入门: 进战斗 / 换单位 / 关菜单后, 要求方向键先松开才接受新移动
        self._input_gated = True
        self._last_current: BattleUnit | None = None
        # 方向键长按检测器 (tap 只转向 / 持续按住超阈值才连走)
        self._hold = DirectionalHold()

        # 镜头 (px): 初始位置沿用世界地图最后一帧的 camera, 进战斗瞬间不跳; 之后由 update lerp 漂到战斗专用偏移.
        wm_cam = world_map._camera_offset()
        self._cam_x = float(wm_cam[0])
        self._cam_y = float(wm_cam[1])

        # 缓存
        self._move_tint = self._make_tint(self.MOVE_TINT)
        self._atk_tint = self._make_tint(self.ATK_TINT)
        self._face_empty_tint = self._make_tint(self.FACE_EMPTY_TINT)
        self._face_enemy_tint = self._make_tint(self.FACE_ENEMY_TINT)
        self._shadow_surf = self._make_shadow()

    def _poll_player_hold(self, dt_ms: int) -> None:
        """PLAYER_MOVE 阶段方向键处理. 复刻原版语义:
        - 朝向不一致, 按键边沿: 仅转身, 不前进
        - 朝向一致, 按键边沿: 立即走一步
        - 持续按住同一方向 < WALK_HOLD_DELAY_MS: 不动 (tap 不会自动走)
        - 持续按住 ≥ WALK_HOLD_DELAY_MS: 开始连走
        """
        # 当前单位换了 (上一回合结束) → 锁输入门 + 清持有状态
        if self.battle.current is not self._last_current:
            self._last_current = self.battle.current
            self._input_gated = True
            self._hold.reset()
        if self.battle.phase != Phase.PLAYER_MOVE or self._menu_open:
            return
        u = self.battle.current
        if not u.is_player:
            return
        # 攻击/受击动画期间禁止新输入
        if u.attack_seq is not None or u.reaction_seq is not None:
            return
        # 还在向逻辑位置插值, 不接受新输入 (避免叠加多步领先渲染)
        if abs(u.render_x - u.x) > self.ANIM_EPSILON or abs(u.render_y - u.y) > self.ANIM_EPSILON:
            return
        if self._input_gated:
            return
        keys = pygame.key.get_pressed()
        dx = (keys[pygame.K_RIGHT] or keys[pygame.K_d]) - (keys[pygame.K_LEFT] or keys[pygame.K_a])
        dy = (keys[pygame.K_DOWN]  or keys[pygame.K_s]) - (keys[pygame.K_UP]   or keys[pygame.K_w])
        if dx == 0 and dy == 0:
            self._hold.reset()
            return
        if dx != 0:
            dy = 0
        new_dir = (dx, dy)
        edge = self._hold.tick(new_dir, dt_ms)

        if new_dir != u.facing:
            # 朝向不一致: 边沿时转身 (含过渡帧), 不前进
            if edge:
                old_facing = u.facing
                cs = get_character_sprite(u.sprite_key) if u.sprite_key else None
                if cs is not None and cs.turn_frame(
                    facing_to_direction(old_facing), facing_to_direction(new_dir)
                ) is not None:
                    u.turn_from_facing = old_facing
                    u.turn_remaining_ms = self.TURN_FRAME_DURATION_MS
                u.facing = new_dir
            return

        # 朝向已对齐: 是否走一步
        if not self._hold.should_walk(edge, self.WALK_HOLD_DELAY_MS):
            return
        if self.battle.player_step(dx, dy) and (u.x, u.y) != (int(round(u.render_x)), int(round(u.render_y))):
            if u.anim_time_ms <= 0:
                u.anim_time_ms = 1
            u.idle_time_ms = 0

    def _make_tint(self, rgba: tuple) -> pygame.Surface:
        s = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
        s.fill(rgba)
        return s

    def _make_shadow(self) -> pygame.Surface:
        s = pygame.Surface((TILE, TILE // 2), pygame.SRCALPHA)
        pygame.draw.ellipse(s, self.SHADOW, s.get_rect())
        return s

    # ------- 生命周期 -------
    def on_enter(self) -> None:
        try:
            self.audio.play_bgm("battle0.wav")
        except FileNotFoundError as e:
            print(f"battle BGM 缺失: {e}")

    # ------- 主循环 -------
    def update(self, dt_ms: int) -> None:
        now = pygame.time.get_ticks()

        # 单位渲染坐标按速度向当前路径节点插值 (玩家走动 + 敌方移动都靠这个).
        # 有 move_path 时, 沿格逐步走, 防止两轴并行 lerp 出 45° 飞行.
        step = self.UNIT_TILES_PER_SEC * dt_ms / 1000.0
        for unit in self.battle.all_units:
            if not unit.alive:
                continue
            # 当前 lerp 目标: 路径头节点 / 否则 unit 逻辑位置
            if unit.move_path:
                tgt_x, tgt_y = unit.move_path[0]
            else:
                tgt_x, tgt_y = unit.x, unit.y
            moving = False
            for axis_name, target in (("x", tgt_x), ("y", tgt_y)):
                rattr = f"render_{axis_name}"
                rval = getattr(unit, rattr)
                delta = target - rval
                if abs(delta) <= step:
                    if rval != float(target):
                        setattr(unit, rattr, float(target))
                else:
                    setattr(unit, rattr, rval + (step if delta > 0 else -step))
                    moving = True
            # 到达当前节点 → 弹出, 切换 facing 到下一段方向
            if (unit.move_path
                    and abs(unit.render_x - unit.move_path[0][0]) < self.ANIM_EPSILON
                    and abs(unit.render_y - unit.move_path[0][1]) < self.ANIM_EPSILON):
                arrived = unit.move_path.pop(0)
                if unit.move_path:
                    nxt = unit.move_path[0]
                    ddx = nxt[0] - arrived[0]
                    ddy = nxt[1] - arrived[1]
                    if abs(ddx) >= abs(ddy) and ddx != 0:
                        unit.facing = (1 if ddx > 0 else -1, 0)
                    elif ddy != 0:
                        unit.facing = (0, 1 if ddy > 0 else -1)
            # 行走帧时间 / 待机帧时间互补累加 (静止 = 走帧重置, 移动 = 待机帧重置)
            if moving:
                unit.anim_time_ms += dt_ms
                unit.idle_time_ms = 0
            else:
                unit.anim_time_ms = 0
                unit.idle_time_ms += dt_ms
            if unit.turn_remaining_ms > 0:
                unit.turn_remaining_ms = max(0, unit.turn_remaining_ms - dt_ms)

        # 当前玩家长按方向键 → 连续移动
        self._poll_player_hold(dt_ms)

        # 把 battle 的伤害事件转成浮动文字 (绿+蓝 双行 / MISS)
        for ev in self.battle.damage_events:
            wx = ev.x * TILE + TILE // 2
            wy = ev.y * TILE + 6
            self._floats.append(FloatText(ev.damage, ev.remaining_hp, wx, wy, now, miss=ev.miss))
        self.battle.damage_events.clear()
        self._floats = [f for f in self._floats if f.alive(now)]

        # 推进 reaction 序列 (受击 / 闪避). 结束后还原朝向 (阵亡保持面向攻击者)
        for unit in self.battle.all_units:
            if unit.reaction_seq is not None:
                self._advance_reaction(unit, dt_ms)
        # 推进 attack 序列 (攻击者动画). 'impact' 步触发受击者反应; 'end' 结束攻击者回合
        for unit in self.battle.all_units:
            if unit.attack_seq is not None:
                self._advance_attack(unit, dt_ms)

        # 镜头 lerp 跟随当前单位 (用 render 值, 让镜头也跟着平滑跑)
        u = self.battle.current
        target_x, target_y = self._compute_camera_offset(
            int(round(u.render_x)), int(round(u.render_y)))
        self._cam_x += (target_x - self._cam_x) * self.CAMERA_LERP
        self._cam_y += (target_y - self._cam_y) * self.CAMERA_LERP

        # 敌方回合: 等所有动画走完, 再短暂停顿, 再 post_enemy_turn (才会触发攻击 + 飘字)
        if self.battle.phase == Phase.ENEMY_TURN:
            if self._units_animating():
                self._enemy_turn_started_at = None  # 还在走, 重置计时
            else:
                if self._enemy_turn_started_at is None:
                    self._enemy_turn_started_at = now
                if now - self._enemy_turn_started_at >= self.ENEMY_TURN_DELAY_MS:
                    self._enemy_turn_started_at = None
                    self.battle.post_enemy_turn()
        elif (self.battle.phase in (Phase.VICTORY, Phase.DEFEAT)
              and not self._battle_over_signaled):
            self._battle_over_signaled = True
            wav = "Victory.wav" if self.battle.phase == Phase.VICTORY else "Gameover.wav"
            try:
                self.audio.play_bgm(wav, loops=0)
            except FileNotFoundError:
                pass

    # ------- 输入 -------
    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.QUIT:
            return False
        if event.type != pygame.KEYDOWN:
            return True
        if self.battle.phase in (Phase.VICTORY, Phase.DEFEAT):
            self._advance_end_screen()
            return True
        if self.battle.phase == Phase.ENEMY_TURN:
            return True
        # 攻击/受击动画期间不接键
        cur = self.battle.current
        if cur.attack_seq is not None:
            return True

        # 菜单打开时: 方向键直接选项, ESC 关闭, 其它忽略
        if self._menu_open:
            self._handle_menu_key(event.key)
            return True

        # 方向键不再走 KEYDOWN (改为 update 里轮询长按), 避免按一下就瞬移领先动画.
        # 但需要这一刻清掉输入门 — 否则战斗中换单位 / 返回地图时长按状态会被误读为"续按".
        if event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN,
                         pygame.K_a, pygame.K_d, pygame.K_w, pygame.K_s):
            if self._input_gated:
                self._input_gated = False
            return True

        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.battle.player_attack_facing()
        elif event.key == pygame.K_ESCAPE:
            self._menu_open = True
        elif event.key == pygame.K_x:
            self.battle.cancel_to_move()
        return True

    def _handle_menu_key(self, key: int) -> None:
        """十字菜单: 上=攻击, 右=技能, 下=结束, 左=道具. ESC 关闭."""
        if key in (pygame.K_ESCAPE, pygame.K_x):
            self._menu_open = False
            self._input_gated = True   # 关菜单后, 防止菜单时按下的方向键续走
            return
        if key in (pygame.K_UP, pygame.K_w):
            # 攻击 = 朝向格上的敌人 (与 Enter 等价, 提供菜单内冗余入口)
            self._menu_open = False
            if not self.battle.player_attack_facing():
                self.battle._log(f"{self.battle.current.name} 朝向无敌人, 无法攻击")
        elif key in (pygame.K_RIGHT, pygame.K_d):
            # 技能 (SG 必杀, AOE 邻接全敌)
            self._menu_open = False
            self.battle.player_use_skill()  # 失败原因已 log
        elif key in (pygame.K_DOWN, pygame.K_s):
            self._menu_open = False
            self.battle.player_end_turn()
        elif key in (pygame.K_LEFT, pygame.K_a):
            self._menu_open = False
            self.battle._log(f"{self.battle.current.name} 翻找道具袋... (尚未实现)")

    def _advance_end_screen(self) -> None:
        """胜利后逐个翻升级框, 然后返回地图. 失败时直接返回."""
        if self.battle.phase == Phase.DEFEAT:
            self.next_scene = self.return_scene
            return
        # 第一次按键: 跳过胜利 banner
        if not self._victory_acknowledged:
            self._victory_acknowledged = True
            self._levelup_idx = 0
            if not self.battle.level_ups:
                self.next_scene = self.return_scene
            return
        # 后续按键: 逐个翻升级框
        self._levelup_idx += 1
        if self._levelup_idx >= len(self.battle.level_ups):
            self.next_scene = self.return_scene

    # ------- 渲染 -------
    def draw(self) -> None:
        self.surface.fill((0, 0, 0))
        cam_x, cam_y = int(self._cam_x), int(self._cam_y)

        # 1) 复用世界地图的地形
        self.world_map.draw_terrain(self.surface, cam_x, cam_y)
        # 2) 移动 / 攻击高亮
        self._draw_overlays(cam_x, cam_y)
        # 3) 单位 (含影子, HP 数字)
        self._draw_units(cam_x, cam_y)
        # 4) 行动菜单 (ESC 弹出)
        self._draw_action_menu(cam_x, cam_y)
        # 5) 浮动伤害
        self._draw_floats(cam_x, cam_y)
        # 6) HUD (不滚动)
        self._draw_hud()
        # 7) 日志
        self._draw_log()
        # 8) 胜负
        if self.battle.phase in (Phase.VICTORY, Phase.DEFEAT):
            self._draw_end_banner()

    def _tile_rect(self, x: int, y: int, cam_x: int, cam_y: int) -> pygame.Rect:
        return pygame.Rect(x * TILE - cam_x, y * TILE - cam_y, TILE, TILE)

    def _tile_center(self, x: int, y: int, cam_x: int, cam_y: int) -> tuple[int, int]:
        r = self._tile_rect(x, y, cam_x, cam_y)
        return r.centerx, r.centery

    def _unit_rect(self, u, cam_x: int, cam_y: int) -> pygame.Rect:
        """用 render_x/y (浮点 tile) 算单位的渲染像素 rect."""
        px = int(round(u.render_x * TILE)) - cam_x
        py = int(round(u.render_y * TILE)) - cam_y
        return pygame.Rect(px, py, TILE, TILE)

    def _compute_camera_offset(self, focus_x: int, focus_y: int) -> tuple[int, int]:
        """像 world_map.camera_offset_for, 但顶/底各留出 HUD/log 高度,
        让 HUD 不挡角色 sprite. 露出的屏幕空间显示底色 (黑/深紫)."""
        sw, sh = self.surface.get_size()
        cx = focus_x * TILE + TILE // 2 - sw // 2
        cy = focus_y * TILE + TILE // 2 - sh // 2
        # X 轴: 标准夹紧
        map_w_px = self.battle.map.w * TILE
        cx = max(0, min(cx, max(0, map_w_px - sw)))
        # Y 轴: 顶部允许 cam 到 -HUD_TOP_BUFFER, 底部允许 cam 走到 +LOG_BOTTOM_BUFFER
        map_h_px = self.battle.map.h * TILE
        min_cy = -self.HUD_TOP_BUFFER
        max_cy = max(min_cy, map_h_px - sh + self.LOG_BOTTOM_BUFFER)
        cy = max(min_cy, min(cy, max_cy))
        return cx, cy

    def _units_animating(self) -> bool:
        for u in self.battle.all_units:
            if not u.alive:
                continue
            if (abs(u.render_x - u.x) > self.ANIM_EPSILON
                    or abs(u.render_y - u.y) > self.ANIM_EPSILON):
                return True
        return False

    def _draw_overlays(self, cam_x: int, cam_y: int) -> None:
        u = self.battle.current
        if not u.is_player or self.battle.phase != Phase.PLAYER_MOVE:
            return
        # 蓝紫色: 本回合可达范围
        for (x, y) in self.battle.turn_move_range:
            self.surface.blit(self._move_tint, self._tile_rect(x, y, cam_x, cam_y))
        # 朝向格: 只在角色静止 (render 已到位) 时才显示
        if (abs(u.render_x - u.x) > self.ANIM_EPSILON
                or abs(u.render_y - u.y) > self.ANIM_EPSILON):
            return
        fx, fy = u.x + u.facing[0], u.y + u.facing[1]
        if self.battle.map.in_bounds(fx, fy):
            occ = self.battle.occupant(fx, fy)
            tint = (self._face_enemy_tint
                    if (occ is not None and occ.is_player != u.is_player)
                    else self._face_empty_tint)
            self.surface.blit(tint, self._tile_rect(fx, fy, cam_x, cam_y))

    def _draw_units(self, cam_x: int, cam_y: int) -> None:
        # Y-排序: render_y 大的 (屏幕下方) 后画 → 在前. 同 y 时把当前行动单位放最后, 防被遮.
        units = sorted(
            (u for u in self.battle.all_units if u.alive),
            key=lambda u: (u.render_y, u is self.battle.current),
        )
        for u in units:
            rect = self._unit_rect(u, cam_x, cam_y)
            cx, cy = rect.centerx, rect.centery
            # 视椎裁剪 (大致)
            if rect.right < 0 or rect.left > self.surface.get_width():
                continue
            if rect.bottom < 0 or rect.top > self.surface.get_height():
                continue
            # 影子
            shadow_rect = self._shadow_surf.get_rect(midbottom=(cx, cy + TILE // 2 - 2))
            self.surface.blit(self._shadow_surf, shadow_rect)
            # 主体: 有 sprite_key 的用真实 atlas, 否则保留色块
            r = rect.inflate(-8, -8)
            if u.sprite_key:
                cs = get_character_sprite(u.sprite_key)
                react_off = (0, 0)
                # reaction 序列优先级最高: 用脚本指定的 atlas-06 帧 + 像素位移
                if u.reaction_seq is not None and u.reaction_frame is not None:
                    try:
                        idle = get_idle_sprite(idle_key_from_walk_key(u.sprite_key))
                        col = u.reaction_frame % 4
                        row = u.reaction_frame // 4
                        frame = idle.sheet.frame(col, row)
                        ox, oy = u.reaction_offset
                        react_off = (int(round(ox)), int(round(oy)))
                    except FileNotFoundError:
                        frame = cs.frame_for_facing(u.facing, 0)
                # 攻击中: 用 fm 逐帧 BBox + anchor (从 fm_frames.py 逆向得到)
                elif u.attack_seq is not None:
                    from core.character_sprites import attack_fm_atlas
                    from core.attack_seq import frames_per_dir
                    from core.sprites import get_fm_surface
                    from core.fm_frames import FM_FRAMES, cols_in_atlas
                    fm_name = attack_fm_atlas(u.name)
                    fm_data = None
                    if fm_name and u.attack_fm_frame is not None:
                        # 我们的资源文件名带 fm_ 前缀, 但 exe 元数据键不带
                        atlas_key = fm_name.lower().removeprefix("fm_")
                        atlas_frames = FM_FRAMES.get(atlas_key)
                        if atlas_frames:
                            n = frames_per_dir(u.name)
                            cols = cols_in_atlas(atlas_key)
                            list_idx = (u.attack_fm_frame // n) * cols + (u.attack_fm_frame % n)
                            if 0 <= list_idx < len(atlas_frames):
                                fm_data = atlas_frames[list_idx]
                    if fm_data is not None:
                        try:
                            fx, fy, fw, fh, anc_x, anc_y = fm_data
                            surf = get_fm_surface(fm_name)
                            frame = surf.subsurface(pygame.Rect(fx, fy, fw, fh))
                            # fm 帧用自己的 anchor, 不走默认 bottom-center
                            u._fm_anchor = (anc_x, anc_y)   # 标记给下面 blit 用
                        except (FileNotFoundError, ValueError):
                            frame = cs.frame_for_facing(u.facing, 0)
                    else:
                        # fallback: ps_*06 row 2 (出招前倾姿态)
                        try:
                            idle = get_idle_sprite(idle_key_from_walk_key(u.sprite_key))
                            col = DEFAULT_IDLE_DIRECTION_COLS[facing_to_direction(u.facing)]
                            frame = idle.sheet.frame(col, 2)
                        except (FileNotFoundError, IndexError):
                            frame = cs.frame_for_facing(u.facing, 0)
                elif u.turn_remaining_ms > 0 and u.turn_from_facing is not None:
                    frame = cs.turn_frame(
                        facing_to_direction(u.turn_from_facing),
                        facing_to_direction(u.facing),
                    ) or cs.frame_for_facing(u.facing, 0)
                elif u.anim_time_ms > 0:
                    # 移动中 → 走路帧
                    anim_idx = u.anim_time_ms // self.WALK_FRAME_PERIOD_MS
                    frame = cs.frame_for_facing(u.facing, int(anim_idx))
                else:
                    # 静止 → 待机呼吸帧
                    try:
                        idle = get_idle_sprite(idle_key_from_walk_key(u.sprite_key))
                        phase = u.idle_time_ms // self.IDLE_FRAME_PERIOD_MS
                        frame = idle.frame_for_facing(u.facing, int(phase))
                    except FileNotFoundError:
                        frame = cs.frame_for_facing(u.facing, 0)
                if u.has_acted and u.attack_seq is None:
                    # 攻击中不要变半透明 (会让玩家误以为已结束行动)
                    frame = frame.copy()
                    frame.set_alpha(140)
                fw, fh = frame.get_size()
                # 攻击位移 (类似受击位移, 二者互斥)
                ax, ay = u.attack_offset if u.attack_seq is not None else (0, 0)
                fm_anchor = getattr(u, "_fm_anchor", None)
                if u.attack_seq is not None and fm_anchor is not None:
                    # fm 帧: anchor (ax, ay) 是 sprite 内 feet 位置
                    # ps_*idle sprite 底部含 ~8px 阴影空白, feet 在 sprite 内 y≈88 (96-8)
                    # 为对齐 idle 的 feet, fm blit 也上移 SHADOW_PAD
                    SHADOW_PAD = 8
                    anc_x, anc_y = fm_anchor
                    self.surface.blit(frame,
                                      (cx - anc_x + int(round(ax)),
                                       cy + TILE // 2 - anc_y - SHADOW_PAD + int(round(ay))))
                    u._fm_anchor = None
                else:
                    # 默认: bottom-center anchor
                    self.surface.blit(frame,
                                      (cx - fw // 2 + react_off[0] + int(round(ax)),
                                       cy + TILE // 2 - fh + react_off[1] + int(round(ay))))
            else:
                color = u.color if not u.has_acted else tuple(c // 2 for c in u.color)
                pygame.draw.rect(self.surface, color, r)
                pygame.draw.rect(self.surface, (0, 0, 0), r, 2)
            if u is self.battle.current:
                pygame.draw.rect(self.surface, self.HIGHLIGHT, rect.inflate(-2, -2), 2)
                # 朝向小三角 (黄)
                self._draw_facing_arrow(u, rect)
            # 头顶 HP
            hp_top = (rect.top if u.sprite_key else r.top) - 1
            hp = self.tiny.render(str(u.hp), True, self.HP_NUM_COLOR)
            self.surface.blit(hp, hp.get_rect(midbottom=(cx, hp_top)))
            # 当前单位 + 移动阶段: 蓝色 M{move}
            if u is self.battle.current and self.battle.phase == Phase.PLAYER_MOVE:
                mv = self.tiny.render(f"M{u.move}", True, self.MOVE_NUM_COLOR)
                self.surface.blit(mv, mv.get_rect(midtop=(cx, r.bottom + 1)))

    def _advance_attack(self, u, dt_ms: int) -> None:
        """推进攻击者 attack_seq 一帧.
        指令: ('move', dx, dy, ticks) | ('fm', atlas, frame, ticks) |
              ('idle', ...) | ('impact',) | ('jump', state) | ('end',)
        """
        from core.attack_seq import ATTACK_TICK_MS
        seq = u.attack_seq
        u.attack_step_elapsed_ms += dt_ms
        while u.attack_step_idx < len(seq):
            step = seq[u.attack_step_idx]
            kind = step[0]
            if kind == 'move':
                _, dx, dy, ticks = step
                duration = ticks * ATTACK_TICK_MS
                sx, sy = u.attack_step_start_off
                if duration <= 0:
                    u.attack_offset = (sx + dx, sy + dy)
                    u.attack_step_idx += 1
                    u.attack_step_start_off = u.attack_offset
                    u.attack_step_elapsed_ms = 0
                    continue
                if u.attack_step_elapsed_ms >= duration:
                    u.attack_offset = (sx + dx, sy + dy)
                    u.attack_step_idx += 1
                    u.attack_step_start_off = u.attack_offset
                    u.attack_step_elapsed_ms -= duration
                    continue
                t = u.attack_step_elapsed_ms / duration
                u.attack_offset = (sx + dx * t, sy + dy * t)
                return
            if kind == 'fm':
                _, atlas, frame, ticks = step
                u.attack_fm_atlas = atlas
                u.attack_fm_frame = frame
                duration = ticks * ATTACK_TICK_MS
                if duration <= 0:
                    u.attack_step_idx += 1
                    u.attack_step_elapsed_ms = 0
                    continue
                if u.attack_step_elapsed_ms >= duration:
                    u.attack_step_idx += 1
                    u.attack_step_elapsed_ms -= duration
                    continue
                return
            if kind == 'idle':
                # 暂未使用 (idle 帧切换), 跳过
                u.attack_step_idx += 1
                u.attack_step_elapsed_ms = 0
                continue
            if kind == 'impact':
                self.battle._apply_pending_attack(u)
                u.attack_step_idx += 1
                u.attack_step_elapsed_ms = 0
                continue
            if kind == 'end':
                self.battle.post_attack_anim(u)
                return
            # 'jump' 等其它状态忽略
            u.attack_step_idx += 1
            u.attack_step_elapsed_ms = 0
        # 序列耗尽兜底
        self.battle.post_attack_anim(u)

    def _advance_reaction(self, u, dt_ms: int) -> None:
        """逐步执行 reaction_seq.py 里的脚本: SET_FRAME / MOVE / END."""
        from core.reaction_seq import REACTION_TICK_MS
        u.reaction_step_elapsed_ms += dt_ms
        seq = u.reaction_seq
        while u.reaction_step_idx < len(seq):
            step = seq[u.reaction_step_idx]
            if step[0] == 'frame':
                u.reaction_frame = step[1]
                u.reaction_step_idx += 1
                u.reaction_step_elapsed_ms = 0
                u.reaction_step_start_off = u.reaction_offset
                continue
            # ('move', dx, dy, ticks)
            _, dx, dy, ticks = step
            duration = ticks * REACTION_TICK_MS
            sx, sy = u.reaction_step_start_off
            if duration <= 0:
                # 瞬间位移 (例如最终归位)
                u.reaction_offset = (sx + dx, sy + dy)
                u.reaction_step_idx += 1
                u.reaction_step_start_off = u.reaction_offset
                u.reaction_step_elapsed_ms = 0
                continue
            if u.reaction_step_elapsed_ms >= duration:
                u.reaction_offset = (sx + dx, sy + dy)
                u.reaction_step_idx += 1
                u.reaction_step_start_off = u.reaction_offset
                u.reaction_step_elapsed_ms -= duration
                continue
            # 中段线性插值
            t = u.reaction_step_elapsed_ms / duration
            u.reaction_offset = (sx + dx * t, sy + dy * t)
            return
        # 序列完成
        u.reaction_seq = None
        u.reaction_frame = None
        u.reaction_offset = (0.0, 0.0)
        if u.alive and u.reaction_saved_facing is not None:
            u.facing = u.reaction_saved_facing
        u.reaction_saved_facing = None

    def _draw_facing_arrow(self, u, tile_rect: pygame.Rect) -> None:
        """在 tile 边框对应朝向的边上画一个小黄三角."""
        cx, cy = tile_rect.centerx, tile_rect.centery
        dx, dy = u.facing
        offset = TILE // 2 - 2
        tip = (cx + dx * offset, cy + dy * offset)
        # 三角的两个底角: 沿垂直方向各偏 4px
        if dx != 0:  # 左/右
            base1 = (tip[0] - dx * 6, tip[1] - 5)
            base2 = (tip[0] - dx * 6, tip[1] + 5)
        else:        # 上/下
            base1 = (tip[0] - 5, tip[1] - dy * 6)
            base2 = (tip[0] + 5, tip[1] - dy * 6)
        pygame.draw.polygon(self.surface, self.HIGHLIGHT, [tip, base1, base2])

    def _draw_action_menu(self, cam_x: int, cam_y: int) -> None:
        """十字 4 选项, 围在当前单位四周 (上=攻 / 右=技 / 下=终 / 左=道)."""
        if not self._menu_open:
            return
        u = self.battle.current
        ucx = u.x * TILE - cam_x + TILE // 2
        ucy = u.y * TILE - cam_y + TILE // 2
        box_w, box_h = 56, 36
        offset = 48  # 距单位中心
        # 4 个框的 (label, center_x, center_y, hint_key)
        boxes = [
            ("↑ 攻击", ucx, ucy - offset),
            ("→ 技能", ucx + offset + box_w // 2, ucy),
            ("↓ 结束", ucx, ucy + offset),
            ("← 道具", ucx - offset - box_w // 2, ucy),
        ]
        for label, x, y in boxes:
            rect = pygame.Rect(0, 0, box_w, box_h)
            rect.center = (x, y)
            # 半透明黑底 + 黄边
            bg = pygame.Surface(rect.size, pygame.SRCALPHA)
            bg.fill((0, 0, 0, 220))
            self.surface.blit(bg, rect)
            pygame.draw.rect(self.surface, self.HIGHLIGHT, rect, 2)
            txt = self._menu_font.render(label, True, self.HIGHLIGHT)
            self.surface.blit(txt, txt.get_rect(center=rect.center))

    def _draw_floats(self, cam_x: int, cam_y: int) -> None:
        now = pygame.time.get_ticks()
        for f in self._floats:
            f.draw(self.surface, self._float_big, self._float_small, cam_x, cam_y, now)

    # ---- HUD ----
    def _draw_hud(self) -> None:
        self._draw_actor_card(HUD_X, HUD_Y, HUD_W_CUR, 70, self.battle.current,
                              label="当前行动", highlight=True)
        nxt = self.battle.next_actor()
        if nxt is not None:
            self._draw_actor_card(HUD_X + HUD_W_CUR + 12, HUD_Y, HUD_W_NEXT, 70, nxt,
                                  label="下一行动", highlight=False)

    def _draw_actor_card(self, x: int, y: int, w: int, h: int, u: BattleUnit,
                         label: str, highlight: bool) -> None:
        rect = pygame.Rect(x, y, w, h)
        # 半透明底
        bg = pygame.Surface(rect.size, pygame.SRCALPHA)
        bg.fill((28, 22, 40, 220))
        self.surface.blit(bg, rect)
        pygame.draw.rect(self.surface,
                         self.HIGHLIGHT if highlight else self.PANEL_BORDER,
                         rect, 2 if highlight else 1)
        avatar = pygame.Rect(x + 6, y + 6, h - 12, h - 12)
        pygame.draw.rect(self.surface, u.color, avatar)
        pygame.draw.rect(self.surface, (0, 0, 0), avatar, 1)
        side = (u.name[0] if u.is_player else "敌")
        t = self.font.render(side, True, (0, 0, 0))
        self.surface.blit(t, t.get_rect(center=avatar.center))

        tx = avatar.right + 10
        ty = y + 4
        tag = self.tiny.render(label, True,
                               self.HIGHLIGHT if highlight else self.DIM)
        self.surface.blit(tag, (tx, ty)); ty += 14
        name_text = f"{u.name}  Lv{u.level}"
        t = self.font.render(name_text, True, self.TEXT)
        self.surface.blit(t, (tx, ty)); ty += 22
        line = f"HP {u.hp}/{u.max_hp}   MP {u.mp}/{u.max_mp}"
        t = self.small.render(line, True, self.TEXT)
        self.surface.blit(t, (tx, ty)); ty += 16
        self._draw_sg_icons(tx, ty, u.sg)
        agi_text = f"敏 {u.agile}  移 {u.move}"
        t = self.tiny.render(agi_text, True, self.DIM)
        self.surface.blit(t, (tx + 80, ty + 1))

    def _draw_sg_icons(self, x: int, y: int, sg: int, max_slots: int = 5) -> None:
        if sg == UNSET:
            t = self.small.render("SG ∞", True, self.HIGHLIGHT)
            self.surface.blit(t, (x, y - 1))
            return
        label = self.tiny.render("SG", True, self.DIM)
        self.surface.blit(label, (x, y))
        slot_w = 6; gap = 2; ox = x + 22
        slots = max(1, min(max_slots, max(1, sg // 5 if sg > 0 else 1)))
        filled = min(slots, max(0, sg // 2))
        for i in range(slots):
            r = pygame.Rect(ox + i * (slot_w + gap), y + 2, slot_w, 10)
            color = self.HIGHLIGHT if i < filled else self.DIM
            pygame.draw.rect(self.surface, color, r)

    def _draw_log(self) -> None:
        sw, sh = self.surface.get_size()
        rect = pygame.Rect(8, sh - LOG_H - 8, sw - 16, LOG_H)
        bg = pygame.Surface(rect.size, pygame.SRCALPHA)
        bg.fill((20, 14, 30, 210))
        self.surface.blit(bg, rect)
        pygame.draw.rect(self.surface, self.PANEL_BORDER, rect, 1)
        max_lines = max(1, (LOG_H - 12) // 18)
        msgs = self.battle.messages[-max_lines:]
        for i, m in enumerate(msgs):
            t = self.small.render(m, True, self.TEXT)
            self.surface.blit(t, (rect.x + 8, rect.y + 6 + i * 18))

    def _draw_end_banner(self) -> None:
        if self.battle.phase == Phase.DEFEAT:
            self._draw_simple_banner("战  败", (220, 90, 90), "游戏结束", "按任意键返回地图")
            return
        # VICTORY
        if not self._victory_acknowledged:
            sub = f"经验 +{self.battle.exp_gained}    金钱 +{self.battle.money_gained}"
            self._draw_simple_banner("胜  利", (90, 220, 100), sub, "按任意键继续")
            return
        # 翻升级对话框
        if 0 <= self._levelup_idx < len(self.battle.level_ups):
            self._draw_levelup_dialog(self.battle.level_ups[self._levelup_idx])

    def _draw_simple_banner(self, title: str, color: tuple, sub: str, hint: str) -> None:
        sw, sh = self.surface.get_size()
        big = self.big.render(title, True, color)
        rect = big.get_rect(center=(sw // 2, sh // 2 - 30))
        bg = rect.inflate(80, 40)
        pygame.draw.rect(self.surface, (0, 0, 0), bg)
        pygame.draw.rect(self.surface, color, bg, 3)
        self.surface.blit(big, rect)
        sub_t = self.font.render(sub, True, self.TEXT)
        self.surface.blit(sub_t, sub_t.get_rect(center=(sw // 2, rect.bottom + 20)))
        hint_t = self.small.render(hint, True, self.DIM)
        self.surface.blit(hint_t, hint_t.get_rect(center=(sw // 2, rect.bottom + 46)))

    def _draw_levelup_dialog(self, rep: "LevelUpReport") -> None:
        """模仿原版 f144: 「<名字> 等级 up!」+ 「提升了 HP/攻击/防御 N」."""
        sw, sh = self.surface.get_size()
        lines = [f"{rep.name}  等级 up!  → Lv{rep.new_level}"]
        if rep.hp_inc:  lines.append(f"  提升了 HP   +{rep.hp_inc}")
        if rep.mp_inc:  lines.append(f"  提升了 MP   +{rep.mp_inc}")
        if rep.atk_inc: lines.append(f"  提升了 攻击 +{rep.atk_inc}")
        if rep.def_inc: lines.append(f"  提升了 防御 +{rep.def_inc}")

        # 估算尺寸
        title_surf = self.font.render(lines[0], True, self.HIGHLIGHT)
        body_surfs = [self.font.render(l, True, self.TEXT) for l in lines[1:]]
        line_h = 28
        w = max(title_surf.get_width(), *(s.get_width() for s in body_surfs)) + 60
        h = 24 + line_h * len(lines) + 28  # title + body + hint
        box = pygame.Rect(0, 0, w, h)
        box.center = (sw // 2, sh // 2)

        # 半透明黑底 + 黄边
        bg = pygame.Surface(box.size, pygame.SRCALPHA)
        bg.fill((0, 0, 0, 230))
        self.surface.blit(bg, box)
        pygame.draw.rect(self.surface, self.HIGHLIGHT, box, 2)

        y = box.y + 14
        self.surface.blit(title_surf, title_surf.get_rect(midtop=(box.centerx, y)))
        y += line_h + 4
        for s in body_surfs:
            self.surface.blit(s, (box.x + 30, y))
            y += line_h
        # 翻页提示
        idx = self._levelup_idx + 1
        total = len(self.battle.level_ups)
        hint = self.small.render(f"按任意键继续 ({idx}/{total})", True, self.DIM)
        self.surface.blit(hint, hint.get_rect(midbottom=(box.centerx, box.bottom - 6)))
