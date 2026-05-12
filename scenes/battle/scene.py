"""战棋战斗场景 — 协调器.

把战斗发生在世界地图上 (不切场景). 渲染的具体活儿派给 scenes.battle.units / .hud.

操作:
  方向键   走 1 格 + 转面向 (走不了就只转身); 走过的格子计入本回合可达范围
  Enter    攻击当前面向格子上的敌人 (近战范围内). 没敌人则无动作.
  ESC      调出行动菜单 (上=攻击 / 右=技能 / 下=结束 / 左=道具)
           菜单内方向键直接选项, ESC 关闭
  X        撤销移动, 把角色拉回本回合起点
  朝向格高亮: 浅白 = 空格, 浅红 = 上面有敌人 (可 Enter 攻击)
  胜负后任意键返回地图.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from core.audio_manager import AudioManager
from core.battle import BattleUnit, Phase, TacticsBattle
from core.movement_input import DirectionalHold
from core.sprites import TILE_W, TILE_H, load_shadow
from scenes.base import Scene
from scenes.menu import load_chinese_font
from scenes.battle import hud as hud_mod
from scenes.battle import units as units_mod
from scenes.battle.float_text import FloatText

if TYPE_CHECKING:
    from scenes.world_map import WorldMapScene


class BattleScene(Scene):
    # ---- 视觉常量 ----
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
    HP_NUM_COLOR = (140, 240, 140)         # 绿色, 健康
    HP_WEAKENED_COLOR = (255, 220, 80)     # 黄色, HP < 40% (虚弱)
    HP_CRITICAL_COLOR = (240, 80, 80)      # 红色, 待挖具体触发条件 (毒/濒死?)
    MP_NUM_COLOR = (130, 170, 255)         # 蓝色
    MOVE_NUM_COLOR = (140, 200, 255)
    SHADOW = (0, 0, 0, 110)

    # ---- 时序常量 ----
    ENEMY_TURN_DELAY_MS = 350     # 走完 + 攻击命中后再停顿这么久
    CAMERA_LERP = 0.18            # 镜头平滑系数 (0=不移, 1=瞬移)
    UNIT_TILES_PER_SEC = 8.0      # 单位走动速度 (格/秒, 与世界地图节奏一致)
    WALK_FRAME_PERIOD_MS = 80     # 行走帧切换间隔
    IDLE_FRAME_PERIOD_MS = 400    # 待机呼吸帧切换间隔 (慢一点更自然)
    WALK_HOLD_DELAY_MS = 80       # 按住方向键超过此时长才自动连走 (tap 只转向)
    # 受击表现: 原版是硬切, 不做位移/混合插值. 只靠 reaction 帧本身的姿态 + 停留时长 +
    # 浮动伤害数字制造冲击感. 加位移插值反而违和.
    ANIM_EPSILON = 0.05           # render 与逻辑差小于此值视为已到位
    HUD_TOP_BUFFER = 96           # 镜头顶部预留 (px), 让 HUD 不挡角色
    LOG_BOTTOM_BUFFER = 116       # 镜头底部预留 (px), 让日志不挡角色

    # 死亡动画时长 (ms). exe FUN_004399c5/9b42 等 +0x124=0x14 = 20 ticks/帧 = 800ms.
    # 只 2 帧: row 4 col 0 (倒下中) + col 1 (躺平 corpse). col 2 atlas 空白.
    DEATH_FRAME_MS = 800
    DEATH_FALL_TOTAL_MS = DEATH_FRAME_MS * 2            # 2 帧 = 1600ms 完整 fall
    ENEMY_DEATH_FLASH_MS = 1000
    ENEMY_DEATH_FLASH_PERIOD_MS = 80
    ENEMY_DEATH_TOTAL_MS = DEATH_FALL_TOTAL_MS + ENEMY_DEATH_FLASH_MS

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
        # anim_engine tick 累积器 (40ms/tick); update() 每帧累加 dt_ms
        self._eng_acc_ms: int = 0
        # FM op 触发时记录其总 ticks (用于 sub-frame 插值: cols > n 的 atlas)
        self.battle.engine.on('frame_change', self._on_engine_frame_change)
        # MOVE op 触发时记录其自己的 ticks + 起点 (ticks=0 = 瞬移不 lerp; ticks>0 = lerp 那段时长)
        self.battle.engine.on('move', self._on_engine_move)
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

        # 镜头 (px): 初始位置沿用世界地图最后一帧的 camera, 进战斗瞬间不跳; 之后由 update lerp.
        wm_cam = world_map._camera_offset()
        self._cam_x = float(wm_cam[0])
        self._cam_y = float(wm_cam[1])

        # 缓存
        self._move_tint = self._make_tint(self.MOVE_TINT)
        self._atk_tint = self._make_tint(self.ATK_TINT)
        self._face_empty_tint = self._make_tint(self.FACE_EMPTY_TINT)
        self._face_enemy_tint = self._make_tint(self.FACE_ENEMY_TINT)
        self._shadow_surf = self._make_shadow()

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
                else:
                    # 路径跑完: 还原 AI 设的攻击朝向 (否则 facing 留在最后一段移动方向)
                    if unit.post_move_facing is not None:
                        unit.facing = unit.post_move_facing
                        unit.post_move_facing = None
            # 行走帧时间 / 待机帧时间互补累加 (静止 = 走帧重置, 移动 = 待机帧重置)
            unit.anim.tick(dt_ms, moving=moving)

        # 当前玩家长按方向键 → 连续移动
        self._poll_player_hold(dt_ms)

        # 把 battle 的伤害事件转飘字, 立即 spawn (跟攻击动画 IMPACT 同步).
        # 多段攻击: 每次 IMPACT 都 spawn, 但同位置先前的标记为非 final → 立即消失,
        # 让最后一发占位 (= 最后一发才走完整 rise + hold + flash 生命周期).
        for ev in self.battle.damage_events:
            wx = ev.x * TILE_W + TILE_W // 2
            wy = ev.y * TILE_H + TILE_H // 2 - 10
            # 同位置先前的 float 全部 demote (instant remove), 只留新一发
            self._floats = [f for f in self._floats
                            if abs(f.world_x - wx) > 4 or abs(f.world_y - wy) > 4]
            self._floats.append(FloatText(ev.damage, ev.remaining_hp, wx, wy, now, miss=ev.miss))
        self.battle.damage_events.clear()
        self._floats = [f for f in self._floats if f.alive(now)]

        # 推进 reaction 序列 (受击 / 闪避). 结束后还原朝向 (阵亡保持面向攻击者)
        for unit in self.battle.all_units:
            if unit.reaction_seq is not None:
                self._advance_reaction(unit, dt_ms)
        # 死亡动画计时: HP=0 + reaction 已结束 + 该 unit 的最近一发伤害数字进入 flash 阶段
        # → 启动死亡 tick. 跟原版"死亡动画在数字闪烁时触发"对齐.
        for unit in self.battle.all_units:
            if unit.hp > 0 or unit.reaction_seq is not None:
                continue
            if unit.death_anim_time_ms < 0:
                # 找该 unit 的最近一发伤害数字, 看是否进 flash
                ready = False
                for f in self._floats:
                    if (abs(f.world_x - (unit.x * TILE_W + TILE_W // 2)) <= TILE_W
                            and f.flash_started_at(now)):
                        ready = True; break
                if ready or not self._floats:    # 没数字也立即开 (配置缺失兜底)
                    unit.death_anim_time_ms = 0
            else:
                unit.death_anim_time_ms += dt_ms
        # 推进 anim_engine: 累积 ms, 每满 ATTACK_TICK_MS (40ms) 调一次 engine.tick().
        from core.attack_seq import ATTACK_TICK_MS
        self._eng_acc_ms += dt_ms
        while self._eng_acc_ms >= ATTACK_TICK_MS:
            self._eng_acc_ms -= ATTACK_TICK_MS
            self.battle.engine.tick()

        # 攻击 SIGNAL -110 后切回合: 等所有动画 (伤害数字 + 死亡动画) 跑完才推进
        if not self._units_animating():
            self.battle.advance_turn_when_ready()

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
              and not self._battle_over_signaled
              and not self._death_animations_pending()):
            self._battle_over_signaled = True
            wav = "Victory.wav" if self.battle.phase == Phase.VICTORY else "Gameover.wav"
            try:
                self.audio.play_bgm(wav, loops=0)
            except FileNotFoundError:
                pass

    def _death_animations_pending(self) -> bool:
        """有任何死单位还在跑死亡动画 (= 拖延 victory banner 的判据)."""
        for u in self.battle.all_units:
            if u.alive:
                continue
            t = u.death_anim_time_ms
            if t < 0:
                return True
            if not u.is_player and t < self.ENEMY_DEATH_TOTAL_MS:
                return True
            if u.is_player and t < self.DEATH_FALL_TOTAL_MS:
                return True
        return False

    # ------- 输入 -------
    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.QUIT:
            return False
        if event.type != pygame.KEYDOWN:
            return True
        if self.battle.phase in (Phase.VICTORY, Phase.DEFEAT):
            if self._death_animations_pending():
                return True   # 死亡动画跑完再接 banner 的输入
            self._advance_end_screen()
            return True
        if self.battle.phase == Phase.ENEMY_TURN:
            return True
        # 攻击 / 受击 / 飘字 / 死亡动画 任一在播放 → 都不接键
        if self._units_animating():
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
            self._menu_open = False
            if not self.battle.player_attack_facing():
                self.battle._log(f"{self.battle.current.name} 朝向无敌人, 无法攻击")
        elif key in (pygame.K_RIGHT, pygame.K_d):
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
        # 攻击 / 受击 / 任何动画 (包含飘字 / 死亡) 期间禁止新输入.
        if self._units_animating():
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
            # 朝向不一致: 边沿时转身 (即生效, 不插过渡帧), 不前进
            if edge:
                u.facing = new_dir
            return

        # 朝向已对齐: 是否走一步
        if not self._hold.should_walk(edge, self.WALK_HOLD_DELAY_MS):
            return
        if self.battle.player_step(dx, dy) and (u.x, u.y) != (int(round(u.render_x)), int(round(u.render_y))):
            if u.anim.anim_time_ms <= 0:
                u.anim.anim_time_ms = 1
            u.anim.idle_time_ms = 0

    # ------- 渲染管线 -------
    def draw(self) -> None:
        self.surface.fill((0, 0, 0))
        cam_x, cam_y = int(self._cam_x), int(self._cam_y)

        # 1) 复用世界地图的地形
        self.world_map.draw_terrain(self.surface, cam_x, cam_y)
        # 2) 移动 / 攻击高亮
        self._draw_overlays(cam_x, cam_y)
        # 3) 单位 (含影子, HP 数字)
        units_mod.draw_units(self, cam_x, cam_y)
        # 4) 行动菜单 (ESC 弹出)
        hud_mod.draw_action_menu(self, cam_x, cam_y)
        # 5) 浮动伤害
        hud_mod.draw_floats(self, cam_x, cam_y)
        # 6) HUD (不滚动)
        hud_mod.draw_hud(self)
        # 7) 日志
        hud_mod.draw_log(self)
        # 8) 胜负 (等死亡动画跑完再出 banner, 否则技能秒杀最后一个敌人会跳过死亡演出)
        if (self.battle.phase in (Phase.VICTORY, Phase.DEFEAT)
                and not self._death_animations_pending()):
            hud_mod.draw_end_banner(self)

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

    # ------- 几何工具 -------
    def _tile_rect(self, x: int, y: int, cam_x: int, cam_y: int) -> pygame.Rect:
        return pygame.Rect(x * TILE_W - cam_x, y * TILE_H - cam_y, TILE_W, TILE_H)

    def _tile_center(self, x: int, y: int, cam_x: int, cam_y: int) -> tuple[int, int]:
        r = self._tile_rect(x, y, cam_x, cam_y)
        return r.centerx, r.centery

    def _unit_rect(self, u, cam_x: int, cam_y: int) -> pygame.Rect:
        """用 render_x/y (浮点 tile) 算单位的渲染像素 rect."""
        px = int(round(u.render_x * TILE_W)) - cam_x
        py = int(round(u.render_y * TILE_H)) - cam_y
        return pygame.Rect(px, py, TILE_W, TILE_H)

    def _compute_camera_offset(self, focus_x: int, focus_y: int) -> tuple[int, int]:
        """像 world_map.camera_offset_for, 但顶/底各留出 HUD/log 高度,
        让 HUD 不挡角色 sprite. 露出的屏幕空间显示底色 (黑/深紫)."""
        sw, sh = self.surface.get_size()
        cx = focus_x * TILE_W + TILE_W // 2 - sw // 2
        cy = focus_y * TILE_H + TILE_H // 2 - sh // 2
        # X 轴: 标准夹紧
        map_w_px = self.battle.map.w * TILE_W
        cx = max(0, min(cx, max(0, map_w_px - sw)))
        # Y 轴: 顶部允许 cam 到 -HUD_TOP_BUFFER, 底部允许 cam 走到 +LOG_BOTTOM_BUFFER
        map_h_px = self.battle.map.h * TILE_H
        min_cy = -self.HUD_TOP_BUFFER
        max_cy = max(min_cy, map_h_px - sh + self.LOG_BOTTOM_BUFFER)
        cy = max(min_cy, min(cy, max_cy))
        return cx, cy

    def _units_animating(self) -> bool:
        """是否有任何单位还在播放动画. 用于回合切换 + 玩家输入门控.
        伤害数字: 只要 flash 开始就算"动画完成" (= 当前角色回合可结束); 没死的目标 flash
        阶段允许下家行动. 死亡动画: 完整跑完才放行 (= 死亡时序晚于 flash 时, 等死亡完).
        """
        now = pygame.time.get_ticks()
        # 飘字 gating: 任何一个还没进 flash 阶段 = 还在动
        for f in self._floats:
            if not f.flash_started_at(now):
                return True
        for u in self.battle.all_units:
            if u.hp <= 0:
                # 死亡动画跑完才放行
                if u.death_anim_time_ms < 0:
                    return True
                if not u.is_player and u.death_anim_time_ms < self.ENEMY_DEATH_TOTAL_MS:
                    return True
                if u.is_player and u.death_anim_time_ms < self.DEATH_FALL_TOTAL_MS:
                    return True
                continue
            if (abs(u.render_x - u.x) > self.ANIM_EPSILON
                    or abs(u.render_y - u.y) > self.ANIM_EPSILON):
                return True
            if u.is_attacking or u.reaction_seq is not None:
                return True
        return False

    # ------- 缓存 surface 创建 -------
    def _make_tint(self, rgba: tuple) -> pygame.Surface:
        s = pygame.Surface((TILE_W, TILE_H), pygame.SRCALPHA)
        s.fill(rgba)
        return s

    def _make_shadow(self) -> pygame.Surface:
        # 用原版 SHADOW.png 的 band 4 (29×11, 普通体型). boss 可改 SHADOW_BOSS=6.
        return load_shadow()

    # ------- anim_engine 回调 -------
    def _on_engine_frame_change(self, ent, atlas_slot: int, frame_idx: int) -> None:
        """FM/IDLE/SET_FRAME op 触发瞬间记录 total_ticks, render 用来算 sub-frame 插值."""
        ent.user_data['_fm_total_ticks'] = ent.ticks if ent.ticks > 0 else 1
        # 新 FM 起来 = 旧 MOVE 插值期结束
        ent.user_data['_move_total_ticks'] = 0

    def _on_engine_move(self, ent, dx: int, dy: int, dz: int, ticks: int) -> None:
        """MOVE op 触发瞬间记录: ticks=0 不 lerp, ticks>0 用自己的 ticks lerp.
        必须在事件里捕获 ticks, 因为 MOVE 后 engine 同 tick 内可能跑 FM, e.ticks 会被覆盖."""
        if ticks > 0:
            # MOVE 后 e.x 已经是终点, 起点 = 终点 - delta
            ent.user_data['_move_start_x'] = ent.x - (dx << 16)
            ent.user_data['_move_start_y'] = ent.y - (dy << 16)
            ent.user_data['_move_total_ticks'] = ticks
        else:
            # 瞬移: 不 lerp, 直接显示 entity.x
            ent.user_data['_move_total_ticks'] = 0

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
