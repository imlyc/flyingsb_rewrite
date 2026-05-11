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
    SBTLFONT_DAMAGE_BASE_FRAME,
    SBTLFONT_DIGIT_BASE_FRAME,
    SBTLFONT_MISS_FRAMES,
    facing_to_direction,
    get_character_sprite,
    get_idle_sprite,
    idle_key_from_walk_key,
    is_flying_sprite,
)
from scenes.unit_render import blit_shadow, blit_unit, pick_locomotion_frame
from scenes.base import Scene
from scenes.menu import load_chinese_font

if TYPE_CHECKING:
    from scenes.world_map import WorldMapScene

from core.sprites import TILE_SIZE as TILE  # 单一权威源

# HUD
HUD_X = 12
HUD_Y = 12
HUD_W_CUR = 280
HUD_W_NEXT = 220

# 底部日志
LOG_H = 100


class FloatText:
    """伤害数字 (per-digit drip + rise + hold + flash) — 仿原版 FUN_004d05d8/04d0488/04d0330.
    时序 (40ms/tick):
      drip:  spawn 一位 / 80ms (奇 tick 触发, 跟 exe FUN_004d0488 +0x144 & 1 同节奏)
      rise:  spawn 后 ~5 ticks (200ms) 弧线上升到峰值
      hold:  32 ticks (1280ms) 静止悬停
      flash: 32 ticks (1280ms) 每 2 ticks (80ms) 翻可见性
      done:  消失
    每位用 fm_SBTLFONT atlas frames 13..22 (= digit 0..9), MISS 用 frames 23/24/25/25.
    """
    TICK_MS = 40
    DRIP_PERIOD_TICKS = 2          # 1 位 / 2 ticks (= 80ms/digit)
    RISE_TICKS = 10                 # 400ms 完整跳跃 (起跳 → 峰 → 落回原点)
    HOLD_TICKS = 32                 # 1280ms 静止 (落回原点后)
    FLASH_TICKS = 32                # 1280ms 闪烁
    FLASH_TOGGLE_TICKS = 2          # 80ms 闪烁周期
    DIGIT_STRIDE_PX = 10            # 位间距 (跟 exe `local_14 * 0xa0000` = 10px 一致)
    RISE_PEAK_PX = 36               # 跳跃峰值高度

    def __init__(self, damage: int, remaining_hp: int,
                 world_x: int, world_y: int, started_at: int,
                 miss: bool = False) -> None:
        self.damage = damage
        self.remaining_hp = remaining_hp   # 兼容字段, 不在 float 里渲染 (持久 HP 标签另渲)
        self.world_x = world_x
        self.world_y = world_y
        self.started_at = started_at
        self.miss = miss
        # 单行 frame 序列: MISS 红色字母 / 普通黄色 damage 数字
        if miss:
            self._frames = list(SBTLFONT_MISS_FRAMES)
        else:
            self._frames = [SBTLFONT_DAMAGE_BASE_FRAME + int(c)
                            for c in str(max(0, damage))]
        self._n = len(self._frames)

    def _digit_state(self, digit_idx: int, now_ms: int) -> tuple[int, str, int]:
        """返回 (life_ticks, phase, sub_phase_ticks). phase ∈ 'pre','rise','hold','flash','done'."""
        spawn_offset_ms = digit_idx * self.DRIP_PERIOD_TICKS * self.TICK_MS
        elapsed = now_ms - self.started_at - spawn_offset_ms
        if elapsed < 0:
            return -1, 'pre', 0
        ticks = elapsed // self.TICK_MS
        if ticks < self.RISE_TICKS:
            return ticks, 'rise', ticks
        ticks -= self.RISE_TICKS
        if ticks < self.HOLD_TICKS:
            return ticks, 'hold', ticks
        ticks -= self.HOLD_TICKS
        if ticks < self.FLASH_TICKS:
            return ticks, 'flash', ticks
        return ticks, 'done', ticks

    def alive(self, now_ms: int) -> bool:
        # 全部 digit 都 done 才算结束
        last_idx = self._n - 1
        _, phase, _ = self._digit_state(last_idx, now_ms)
        return phase != 'done'

    @property
    def flash_started(self) -> bool:
        """是否任何一位进了 flash 阶段 (= 死亡动画触发点)."""
        return False   # 用 flash_started_at(now) 取代; 留 stub 兼容

    def flash_started_at(self, now_ms: int) -> bool:
        # 第一位最早进 flash, 用它当判据
        _, phase, _ = self._digit_state(0, now_ms)
        return phase in ('flash', 'done')

    def draw(self, surface: pygame.Surface,
             big_font: pygame.font.Font, small_font: pygame.font.Font,
             cam_x: int, cam_y: int, now_ms: int) -> None:
        from core.sprites import sbtlfont_frame
        total_w = (self._n - 1) * self.DIGIT_STRIDE_PX + 10
        base_x = self.world_x - cam_x - total_w // 2
        base_y = self.world_y - cam_y
        for i, frame_idx in enumerate(self._frames):
            _, phase, sub = self._digit_state(i, now_ms)
            if phase in ('pre', 'done'):
                continue
            if phase == 'flash' and (sub // self.FLASH_TOGGLE_TICKS) % 2 == 1:
                continue
            if phase == 'rise':
                t = sub / self.RISE_TICKS
                arc = 4.0 * t * (1.0 - t)
                dy = int(self.RISE_PEAK_PX * arc)
            else:
                dy = 0
            try:
                surf, ax, ay = sbtlfont_frame(frame_idx)
            except (FileNotFoundError, IndexError):
                continue
            x = base_x + i * self.DIGIT_STRIDE_PX
            y = base_y - dy
            surface.blit(surf, (x, y - surf.get_height()))


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
    HP_NUM_COLOR = (140, 240, 140)         # 绿色, 健康
    HP_WEAKENED_COLOR = (255, 220, 80)     # 黄色, HP < 40% (虚弱)
    HP_CRITICAL_COLOR = (240, 80, 80)      # 红色, 待挖具体触发条件 (毒/濒死?)
    MP_NUM_COLOR = (130, 170, 255)         # 蓝色
    MOVE_NUM_COLOR = (140, 200, 255)
    SHADOW = (0, 0, 0, 110)

    ENEMY_TURN_DELAY_MS = 350     # 走完 + 攻击命中后再停顿这么久
    CAMERA_LERP = 0.18            # 镜头平滑系数 (0=不移, 1=瞬移)
    UNIT_TILES_PER_SEC = 8.0      # 单位走动速度 (格/秒, 与世界地图节奏一致)
    WALK_FRAME_PERIOD_MS = 80     # 行走帧切换间隔
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
        # 攻击 / 受击 / 任何动画 (包含飘字 / 死亡) 期间禁止新输入.
        # 用 _units_animating 统一判定 — 跟回合切换 gating 一致.
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
            wx = ev.x * TILE + TILE // 2
            wy = ev.y * TILE + TILE // 2 - 10
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
                    if (abs(f.world_x - (unit.x * TILE + TILE // 2)) <= TILE
                            and f.flash_started_at(now)):
                        ready = True; break
                if ready or not self._floats:    # 没数字也立即开 (配置缺失兜底)
                    unit.death_anim_time_ms = 0
            else:
                unit.death_anim_time_ms += dt_ms
        # 推进 anim_engine: 累积 ms, 每满 ATTACK_TICK_MS (40ms) 调一次 engine.tick().
        # tick 内部会跑所有 attacking entity 的 seq, 触发 SIGNAL/move/frame_change 事件.
        # MOVE 起点+总 ticks 由 _on_engine_move 在 op 触发瞬间记录 (避免被后续 op 覆盖丢失).
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
        # 8) 胜负 (等死亡动画跑完再出 banner, 否则技能秒杀最后一个敌人会跳过死亡演出)
        if (self.battle.phase in (Phase.VICTORY, Phase.DEFEAT)
                and not self._death_animations_pending()):
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

    # 死亡动画时长 (ms). exe FUN_004399c5/9b42 等 +0x124=0x14 = 20 ticks/帧 = 800ms.
    # 只 2 帧: row 4 col 0 (倒下中) + col 1 (躺平 corpse). col 2 atlas 空白.
    DEATH_FRAME_MS = 800
    DEATH_FALL_TOTAL_MS = DEATH_FRAME_MS * 2            # 2 帧 = 1600ms 完整 fall
    # 敌人 fall 完成尸体后闪烁多次再消失. 150ms 半周期 = 300ms/cycle = 清晰可见.
    ENEMY_DEATH_FLASH_MS = 1000
    ENEMY_DEATH_FLASH_PERIOD_MS = 80
    ENEMY_DEATH_TOTAL_MS = DEATH_FALL_TOTAL_MS + ENEMY_DEATH_FLASH_MS

    def _draw_units(self, cam_x: int, cam_y: int) -> None:
        # Y-排序: render_y 大的 (屏幕下方) 后画 → 在前. 同 y 时把当前行动单位放最后, 防被遮.
        # 死单位: 玩家永远显示 (尸体可被复活), 敌人完成闪烁后跳过 (= 视觉消失但仍在 list).
        def _should_render(u):
            if u.alive: return True
            if u.is_player: return True   # 留尸
            return u.death_anim_time_ms < self.ENEMY_DEATH_TOTAL_MS
        units = sorted(
            (u for u in self.battle.all_units if _should_render(u)),
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
            # 死亡分支:
            #   reaction 完 + 数字 flash → death_anim_time_ms >= 0 → fall + corpse
            #   reaction 完 + 数字未 flash (空窗 ~900ms) → 显示虚弱姿势, 不画影子 (= 跟原版一致, 不"站起来再倒下")
            if not u.alive:
                if u.death_anim_time_ms >= 0:
                    self._draw_dead_unit(u, cx, cy)
                else:
                    self._draw_dying_pose(u, cx, cy)
                continue
            # 影子: 以 tile 中心为中心 (= feet 位置), 脚踩阴影正中
            blit_shadow(self.surface, self._shadow_surf, cx, cy)
            # 主体: 有 sprite_key 的用真实 atlas, 否则保留色块
            r = rect.inflate(-8, -8)
            if u.sprite_key:
                cs = get_character_sprite(u.sprite_key)
                react_off = (0, 0)
                anchor: tuple[int, int] | None = None    # (feet_x, feet_y) within frame; None=用默认 bottom-center
                # reaction 序列优先级最高: 用脚本指定的 atlas-06 帧 + 像素位移
                if u.reaction_seq is not None and u.reaction_frame is not None:
                    try:
                        idle = get_idle_sprite(idle_key_from_walk_key(u.sprite_key))
                        col = u.reaction_frame % 4
                        row = u.reaction_frame // 4
                        frame = idle.sheet.frame(col, row)
                        anchor = idle.feet_for_facing(u.facing)
                        ox, oy = u.reaction_offset
                        react_off = (int(round(ox)), int(round(oy)))
                    except FileNotFoundError:
                        frame = cs.frame_for_facing(u.facing, 0)
                # 攻击中: 用 fm 逐帧 BBox + anchor (从 fm_frames.py 逆向得到).
                # 状态全部从 anim_engine.Entity 读: atlas_slot, frame_idx, x/y (16.16 fixed → px).
                # 两条 render 路径:
                #   (a) Player ATK_A/B/C (atlas_slot 抽象 0/1/5): 走 per-character attack_fm_atlas() lookup
                #       + phase-based sub-frame 插值 (cols > n 的角色用)
                #   (b) Enemy ENEMY_* (atlas_slot 是全局 idx, e.g. 192=ccrow_g0): 走 atlas_resource() 反查,
                #       frame_idx 直接当 atlas 内索引 (敌方 seq 不需要 phase 数学)
                elif u.is_attacking:
                    from core.character_sprites import attack_fm_atlas, attack_total_frames
                    from core.attack_seq import frames_per_dir, ATTACK_TICK_MS
                    from core.sprites import get_fm_surface
                    from core.fm_frames import FM_FRAMES, cols_in_atlas
                    from core.raw_attack_seqs import atlas_resource
                    fm_data = None
                    fm_name = None
                    ent = u.entity
                    slot_lo = ent.atlas_slot & 0xffff
                    fm_frame_idx = ent.frame_idx if slot_lo != 0 or ent.frame_idx != 0 else None
                    # 路径选择: slot >= 8 = 全局 atlas idx (mode 0, enemy), 否则 per-character (player)
                    is_global_atlas = slot_lo >= 8
                    if is_global_atlas and fm_frame_idx is not None:
                        atlas_key = atlas_resource(slot_lo)
                        if atlas_key:
                            fm_name = "fm_" + atlas_key.upper()
                            atlas_frames = FM_FRAMES.get(atlas_key)
                            if atlas_frames and 0 <= fm_frame_idx < len(atlas_frames):
                                fm_data = atlas_frames[fm_frame_idx]
                    elif fm_frame_idx is not None:
                        # per-character 路径
                        fm_name = attack_fm_atlas(u.name)
                        if fm_name:
                            atlas_key = fm_name.lower().removeprefix("fm_")
                            atlas_frames = FM_FRAMES.get(atlas_key)
                            if atlas_frames:
                                n = frames_per_dir(u.name)
                                cols = cols_in_atlas(atlas_key)
                                override = attack_total_frames(u.name)
                                total = override if override is not None else (cols // n) * n
                                phase = fm_frame_idx % n
                                base = total // n
                                remainder = total - base * n
                                phase_size = max(1, base + (1 if phase < remainder else 0))
                                phase_start = base * phase + min(phase, remainder)
                                sub_frame = 0
                                if phase_size > 1:
                                    fm_total = ent.user_data.get('_fm_total_ticks', 0)
                                    if fm_total > 0:
                                        sub_t = self._eng_acc_ms / ATTACK_TICK_MS
                                        elapsed = (fm_total - ent.ticks) + sub_t
                                        progress = max(0.0, min(0.999, elapsed / fm_total))
                                        sub_frame = int(progress * phase_size)
                                list_idx = (fm_frame_idx // n) * cols + phase_start + sub_frame
                                if 0 <= list_idx < len(atlas_frames):
                                    fm_data = atlas_frames[list_idx]
                    if fm_data is not None:
                        try:
                            fx, fy, fw, fh, anc_x, anc_y = fm_data
                            surf = get_fm_surface(fm_name)
                            frame = surf.subsurface(pygame.Rect(fx, fy, fw, fh))
                            anchor = (anc_x, anc_y)
                        except (FileNotFoundError, ValueError):
                            frame = cs.frame_for_facing(u.facing, 0)
                    else:
                        # fallback: ps_*06 row 2 (出招前倾姿态)
                        try:
                            idle = get_idle_sprite(idle_key_from_walk_key(u.sprite_key))
                            col = DEFAULT_IDLE_DIRECTION_COLS[facing_to_direction(u.facing)]
                            frame = idle.sheet.frame(col, 2)
                            anchor = idle.feet_for_facing(u.facing)
                        except (FileNotFoundError, IndexError):
                            frame = cs.frame_for_facing(u.facing, 0)
                else:
                    # 通用 locomotion: 走路 / 待机 / (HP<40%) 虚弱, 用共享 picker
                    flying = is_flying_sprite(u.sprite_key)
                    try:
                        idle_sprite = get_idle_sprite(idle_key_from_walk_key(u.sprite_key))
                    except FileNotFoundError:
                        idle_sprite = None
                    weakened_sprite = None
                    if u.is_weakened:
                        from core.sprites import get_weakened_sprite, weakened_key_from_walk_key
                        try:
                            weakened_sprite = get_weakened_sprite(weakened_key_from_walk_key(u.sprite_key))
                        except FileNotFoundError:
                            pass    # 该角色无 ps_*04 atlas, 退回普通 walk/idle
                    frame, anchor = pick_locomotion_frame(
                        cs, idle_sprite, u.facing, u.anim,
                        walk_period_ms=self.WALK_FRAME_PERIOD_MS,
                        idle_period_ms=self.IDLE_FRAME_PERIOD_MS,
                        flying=flying,
                        weakened_sprite=weakened_sprite,
                    )
                # 攻击中不要变半透明 (会让玩家误以为已结束行动)
                alpha = 140 if (u.has_acted and not u.is_attacking) else None
                # 攻击位移: entity.x/y 是 16.16 fixed point → 右移 16 拿像素.
                # 若当前在 MOVE 等待期 (move_total_ticks > 0), 从 move_start_x lerp 到 entity.x,
                # 进度 = (move_total - ticks_remaining + sub_t) / move_total, 平滑滑动.
                if u.is_attacking:
                    ent = u.entity
                    move_total = ent.user_data.get('_move_total_ticks', 0)
                    if move_total > 0 and ent.ticks > 0:
                        from core.attack_seq import ATTACK_TICK_MS as _ATM
                        sub_t = self._eng_acc_ms / _ATM
                        progress = max(0.0, min(1.0, (move_total - ent.ticks + sub_t) / move_total))
                        sx = ent.user_data.get('_move_start_x', ent.x)
                        sy = ent.user_data.get('_move_start_y', ent.y)
                        ax = int(sx + (ent.x - sx) * progress) >> 16
                        ay = int(sy + (ent.y - sy) * progress) >> 16
                    else:
                        ax = ent.x >> 16
                        ay = ent.y >> 16
                else:
                    ax, ay = 0, 0
                if anchor is None:
                    # 兜底: bottom-center 当 anchor (frame 底中心)
                    fw, fh = frame.get_size()
                    anchor = (fw // 2, fh)
                sprite_top_y = blit_unit(
                    self.surface, frame, anchor,
                    tile_center_x=cx, tile_center_y=cy,
                    offset_x=react_off[0] + int(round(ax)),
                    offset_y=react_off[1] + int(round(ay)),
                    alpha=alpha,
                )
            else:
                color = u.color if not u.has_acted else tuple(c // 2 for c in u.color)
                pygame.draw.rect(self.surface, color, r)
                pygame.draw.rect(self.surface, (0, 0, 0), r, 2)
            if u is self.battle.current:
                pygame.draw.rect(self.surface, self.HIGHLIGHT, rect.inflate(-2, -2), 2)
                # 朝向小三角 (黄)
                self._draw_facing_arrow(u, rect)
            # HP / MP 持久标签: 仅敌人显示 (己方状态后续移到屏幕顶部 HUD).
            # 字号 ≈ float text (sbtlfont 14px); 用普通像素字 self.small (13).
            # 布局 (按截图): 居中堆叠在角色头顶, 从上到下 HP → MP → float text.
            # 颜色: HP 绿(健康) / 黄(虚弱 < 40%) / 红(??? TODO 触发条件待挖); MP 蓝.
            if not u.is_player:
                # float text 顶边 ≈ cy - 24 (baseline=cy-10, height=14).
                # MP 紧贴 float text 上方, HP 紧贴 MP 上方, 各 ~14px.
                hp_color = self.HP_WEAKENED_COLOR if u.is_weakened else self.HP_NUM_COLOR
                label_cx = cx + 8        # 中间偏右
                mp = self.small.render(str(u.mp), True, self.MP_NUM_COLOR)
                mp_rect = mp.get_rect(midbottom=(label_cx, cy - 25))
                self.surface.blit(mp, mp_rect)
                hp = self.small.render(str(u.hp), True, hp_color)
                self.surface.blit(hp, hp.get_rect(midbottom=(label_cx, mp_rect.top - 1)))
            # 当前单位 + 移动阶段: 蓝色 M{move} (放 tile 底部)
            if u is self.battle.current and self.battle.phase == Phase.PLAYER_MOVE:
                mv = self.tiny.render(f"M{u.move}", True, self.MOVE_NUM_COLOR)
                self.surface.blit(mv, mv.get_rect(midtop=(cx, rect.bottom + 1)))

    def _draw_dying_pose(self, u, cx: int, cy: int) -> None:
        """濒死过渡: HP=0 + reaction 已结束 + 死亡动画未启动 (= 等数字 flash) 时显示虚弱半蹲.
        防止从站立姿势直接进死亡动画 (= 不"站起来再倒下"). anchor 复用 walk feet."""
        if not u.sprite_key:
            return
        from core.sprites import (
            get_character_sprite, get_weakened_sprite, weakened_key_from_walk_key,
        )
        try:
            weak = get_weakened_sprite(weakened_key_from_walk_key(u.sprite_key))
            walk = get_character_sprite(u.sprite_key)
        except FileNotFoundError:
            return
        frame = weak.frame_for_facing(u.facing, 0)   # col 1 半蹲 (跟正常 weakened 同首帧, 不 ping-pong)
        anchor = walk.feet_for_facing(u.facing)
        blit_unit(self.surface, frame, anchor,
                  tile_center_x=cx, tile_center_y=cy)

    def _draw_dead_unit(self, u, cx: int, cy: int) -> None:
        """死亡渲染: ps_*04 row 4 三帧 fall (800ms/帧 = 0x14 ticks 来自 exe), 玩家永久躺尸,
        敌人 hold 后闪烁消失. anchor 复用 walk sprite (站立姿势脚点)."""
        if not u.sprite_key:
            return
        from core.sprites import (
            get_character_sprite, get_weakened_sprite, weakened_key_from_walk_key,
        )
        try:
            weak = get_weakened_sprite(weakened_key_from_walk_key(u.sprite_key))
        except FileNotFoundError:
            return
        t = max(0, u.death_anim_time_ms)
        # fall: 0/1 两帧, 每帧 800ms; 之后永久 hold frame 1 (= 躺平 corpse)
        if t < self.DEATH_FALL_TOTAL_MS:
            frame_idx = t // self.DEATH_FRAME_MS
        else:
            frame_idx = 1
        # 敌人闪烁: fall 结束直接闪 → 消失. (帧停在 frame 2 = 躺平 pose)
        if not u.is_player:
            t_post_fall = t - self.DEATH_FALL_TOTAL_MS
            if t_post_fall >= 0:
                if (t_post_fall // self.ENEMY_DEATH_FLASH_PERIOD_MS) % 2 == 1:
                    return
        frame = weak.death_frame(int(frame_idx))
        # 用 corpse 的 body 中心当 anchor (= 让躺尸居中填 tile, 不再贴 tile 中线上半部)
        anchor = weak.death_anchor(int(frame_idx))
        blit_unit(self.surface, frame, anchor,
                  tile_center_x=cx, tile_center_y=cy)

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
