"""战棋战斗场景 — 协调器.

战斗发生在世界地图上, 不切场景. 拆分:
  update.py   每帧 tick (位置/动画/伤害/引擎/相机/回合切换)
  input.py    handle_event + 玩家长按 polling
  units.py    单位渲染 (live/dying/dead/blink/facing)
  hud.py      HUD/菜单/banner/日志/升级框
  float_text  浮动伤害数字 widget

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
from core.battle.data import BattleUnit, Phase
from core.battle.tactics import TacticsBattle
from core.movement_input import DirectionalHold
from core.sprites.base import TILE_W, TILE_H, load_shadow
from scenes.base import Scene
from scenes.menu import load_chinese_font
from scenes.battle import hud as hud_mod
from scenes.battle import input as input_mod
from scenes.battle import units as units_mod
from scenes.battle import update as update_mod
from scenes.battle.float_text import FloatText
from scenes.battle.hit_effect import draw_hit_effects

if TYPE_CHECKING:
    from scenes.world_map.scene import WorldMapScene


class BattleScene(Scene):
    # ---- 视觉常量 ----
    PANEL_BG = (28, 22, 40)
    PANEL_BORDER = (200, 180, 100)
    TEXT = (240, 240, 240)
    DIM = (160, 160, 160)
    HIGHLIGHT = (255, 240, 120)
    # 颜色从原版截图反向 + 分层假设: 基底 (蓝=移动范围 / 红=攻击范围) + 白色焦点 overlay.
    # target.png 那块"浅红"实际是 ATK 深红 + 白叠加, 不是单层 salmon. 改回深色饱和红.
    MOVE_TINT = (65, 70, 220, 128)            # 蓝 = 移动范围
    DAMAGE_TINT = (180, 55, 50, 200)          # 红 = 伤害范围
    ATTACK_RANGE_TINT = (255, 255, 255, 128)  # 白 = 攻击范围 (= cursor 可游走范围)
    FOCUS_TINT = (255, 255, 255, 80)          # 浅白 = cursor 焦点 overlay
    CURSOR_COLOR = (255, 240, 120)
    HP_NUM_COLOR = (140, 240, 140)         # 绿色, 健康
    HP_WEAKENED_COLOR = (255, 220, 80)     # 黄色, HP < 40% (虚弱)
    HP_CRITICAL_COLOR = (240, 80, 80)      # 红色, 待挖具体触发条件 (毒/濒死?)
    MP_NUM_COLOR = (130, 170, 255)         # 蓝色
    MOVE_NUM_COLOR = (140, 200, 255)
    SHADOW = (0, 0, 0, 110)

    # ---- 时序常量 ----
    ENEMY_TURN_DELAY_MS = 350     # 走完 + 攻击前停顿 (显示攻击/伤害范围)
    ENEMY_PRE_MOVE_PAUSE_MS = 450  # ENEMY_TURN 进入后先停这么久显示移动范围, 然后才 AI 移动
    CAMERA_LERP = 0.18            # 镜头平滑系数 (0=不移, 1=瞬移)
    UNIT_TILES_PER_SEC = 11.0     # 单位走动速度 (格/秒, 与世界地图节奏一致). 8 → 11 全局加速 4/3x
    WALK_FRAME_PERIOD_MS = 60     # 行走帧切换间隔 (80 → 60)
    IDLE_FRAME_PERIOD_MS = 300    # 待机呼吸帧切换间隔 (400 → 300)
    WALK_HOLD_DELAY_MS = 80       # 按住方向键超过此时长才自动连走
    # 受击表现: 原版是硬切, 不做位移/混合插值. 加位移插值反而违和.
    ANIM_EPSILON = 0.05           # render 与逻辑差小于此值视为已到位
    HUD_TOP_BUFFER = 96           # 镜头顶部预留 (px), 让 HUD 不挡角色
    LOG_BOTTOM_BUFFER = 116       # 镜头底部预留 (px), 让日志不挡角色

    # 死亡动画时长 (ms). exe FUN_004399c5/9b42 等 +0x124=0x14 = 20 ticks/帧 = 800ms.
    # 只 2 帧: row 4 col 0 (倒下中) + col 1 (躺平 corpse).
    # 一级菜单打开动画 (同步进行): 白方框收缩 + 4 icon 顺时针旋转放大入位.
    MENU_ANIM_TOTAL_MS = 200
    # 一级 → 二级 过渡: A icons 再转 90° 消失 + 白点扩成白框移到所选 icon 位置;
    # B 二级菜单 panel 缩放出现 (白框保持); C 白框移动 + 变形到二级菜单首行选项.
    MENU_TRANSITION_A_MS = 120
    MENU_TRANSITION_B_MS = 100
    MENU_TRANSITION_C_MS = 100
    MENU_TRANSITION_TOTAL_MS = MENU_TRANSITION_A_MS + MENU_TRANSITION_B_MS + MENU_TRANSITION_C_MS
    # 二级 → 一级 反向动画: 二级 panel 缩小消失. 完成后立即接 _menu_anim_t (= 一级打开动画).
    MENU_CLOSE_MS = 120
    # 一级菜单关闭回战斗的动画 (跟 L1→L2 phase A 同形): icons 转 90° 淡出 + 选中 icon 的
    # 白框形成. ESC 路径不画白框; End/Item/Settings 走完白框成型后整体消失.
    MENU_DISMISS_MS = 120

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

        self._enemy_turn_started_at: int | None = None
        self._enemy_pre_move_started_at: int | None = None
        self._battle_over_signaled = False
        self._floats: list[FloatText] = []
        # anim_engine tick 累积器 (40ms/tick); update() 每帧累加 dt_ms
        self._eng_acc_ms: int = 0
        # FM op 触发时记录其总 ticks (用于 sub-frame 插值: cols > n 的 atlas)
        self.battle.engine.on('frame_change', self._on_engine_frame_change)
        # MOVE op 触发时记录其自己的 ticks + 起点 (ticks=0 = 瞬移不 lerp; ticks>0 = lerp 那段时长)
        self.battle.engine.on('move', self._on_engine_move)
        # anim seq 'sound' op (0x0411 PLAY) → 按全局 sound_id 播战斗音效
        self.battle.engine.on('sound_play', lambda ent, sid: self.audio.play_sfx_id(sid))
        # 'sound' op (0x0412 STOP) / 技能收尾 → 切断还在播的长音 (exe FUN_00416388)
        self.battle.engine.on('sound_stop', lambda ent, sid: self.audio.stop_sfx_id(sid))
        # 密集技能音 (青龙冰锥雨等): 同 id 单通道不叠放 (exe 单 DirectSound buffer 语义)
        self.battle.engine.on('sound_play_solo', lambda ent, sid: self.audio.play_sfx_id(sid, solo=True))
        # 升级流程: VICTORY 后, 玩家按键先看完所有升级框, 才返回地图
        self._levelup_idx = 0           # 当前显示的升级报告下标 (-1 表已结束)
        self._victory_acknowledged = False
        self._float_big = load_chinese_font(22)
        self._float_small = load_chinese_font(14)
        # 行动菜单: ESC 弹出十字 4 选项 (上=技能, 左=道具, 右=设置, 下=回合结束)
        self._menu_open = False
        self._menu_font = load_chinese_font(16)
        # 二级菜单: None / 'skill' (上→技能列表). 在二级菜单按 ESC 回退到一级.
        self._submenu: str | None = None
        # 技能二级菜单的选中 idx (0..len(current.known_skills)-1). 每次打开二级菜单从 0 起.
        self._skill_cursor: int = 0
        # 打开一级菜单的动画计时 (ms 累加; None = 已完成静态显示).
        # phase 1: 白方框收缩, phase 2: 4 icon 旋转放大入位. 见 scenes.battle.hud.
        self._menu_anim_t: int | None = None
        # 一级 → 二级 过渡动画计时. None = 不在过渡中.
        self._menu_transition_t: int | None = None
        # 过渡选中的 icon (= 白框终点 / 二级菜单类型). 仅 SMENU_SKILL 实装.
        self._menu_transition_target: int = 0
        # 二级 → 一级 反向动画 (panel 缩小消失). 完成后会自动接 _menu_anim_t 重播打开动画.
        self._menu_close_t: int | None = None
        # 一级 → 战斗 关闭动画. target = 选中 icon idx (None = ESC 路径, 无白框).
        # action = 完成时执行的回合动作 ('end_turn' 或 None).
        self._menu_dismiss_t: int | None = None
        self._menu_dismiss_target: int | None = None
        self._menu_dismiss_action: str | None = None
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
        self._damage_tint = self._make_tint(self.DAMAGE_TINT)
        self._attack_range_tint = self._make_tint(self.ATTACK_RANGE_TINT)
        self._focus_tint = self._make_tint(self.FOCUS_TINT)
        self._shadow_surf = self._make_shadow()

    # ------- 生命周期 -------
    def on_enter(self) -> None:
        try:
            self.audio.play_bgm("battle0.wav")
        except FileNotFoundError as e:
            print(f"battle BGM 缺失: {e}")

    def update(self, dt_ms: int) -> None:
        update_mod.tick(self, dt_ms)

    def handle_event(self, event: pygame.event.Event) -> bool:
        return input_mod.handle_event(self, event)

    # ------- 渲染管线 -------
    def draw(self) -> None:
        self.surface.fill((0, 0, 0))
        cam_x, cam_y = int(self._cam_x), int(self._cam_y)
        # 屏幕震动 (玄武地震): 相机原点每 tick 随机抖动 (engine entity 写 battle.shake_offset)
        sx, sy = self.battle.shake_offset
        cam_x += sx
        cam_y += sy

        # 1) 复用世界地图的地形
        self.world_map.draw_terrain(self.surface, cam_x, cam_y)
        # 2) 移动 / 攻击高亮
        self._draw_overlays(cam_x, cam_y)
        # 2.5) 敌人身后的命中特效 (分身上方那只 = 站敌人身后, 应被敌人挡) → 单位之前画
        draw_hit_effects(self, cam_x, cam_y, behind=True)
        # 3) 单位 (含影子, HP 数字)
        units_mod.draw_units(self, cam_x, cam_y)
        # 4) 行动菜单 (ESC 弹出)
        hud_mod.draw_action_menu(self, cam_x, cam_y)
        # 5) 命中特效 (hit-spark anim_engine entity, 单位之上, 飘字之下)
        draw_hit_effects(self, cam_x, cam_y)
        # 6) 浮动伤害
        hud_mod.draw_floats(self, cam_x, cam_y)
        # 6) HUD (不滚动)
        hud_mod.draw_hud(self)
        # 7) 日志 (L2 静态时让位给技能描述长条)
        if self._submenu == 'skill' and self._menu_transition_t is None \
                and self._menu_close_t is None:
            hud_mod.draw_skill_desc_bar(self)
        else:
            hud_mod.draw_log(self)
        # 8) 胜负 (等死亡动画跑完再出 banner, 否则技能秒杀最后一个敌人会跳过死亡演出)
        if (self.battle.phase in (Phase.VICTORY, Phase.DEFEAT)
                and not update_mod.death_animations_pending(self)):
            hud_mod.draw_end_banner(self)

    def _draw_overlays(self, cam_x: int, cam_y: int) -> None:
        u = self.battle.current
        phase = self.battle.phase
        if phase not in (Phase.PLAYER_MOVE, Phase.PLAYER_AIM, Phase.ENEMY_TURN):
            return
        moving = (abs(u.render_x - u.x) > self.ANIM_EPSILON
                  or abs(u.render_y - u.y) > self.ANIM_EPSILON)

        # ---- 敌方回合 (镜像玩家显示, 没有交互) ----
        # 流程: ENEMY_TURN 进入 → pre-move pause (450ms 显移动范围) → AI 移动 lerp →
        #   pre-attack pause (350ms 显攻击/伤害范围) → 攻击动画
        if phase == Phase.ENEMY_TURN and not u.is_player:
            # pre-move pause OR 正在 lerp 移动: 显移动范围
            if self.battle._enemy_ai_pending or moving or u.move_path:
                for (x, y) in self.battle.turn_move_range:
                    self.surface.blit(self._move_tint, self._tile_rect(x, y, cam_x, cam_y))
                return
            # pre-attack pause: 攻击未启动 (entity 未 attacking), 仍有 pending target
            pending = self.battle._pending_enemy_attack
            if pending is not None and not u.is_attacking:
                for (px, py) in self.battle.attack_range(u):
                    self.surface.blit(self._attack_range_tint,
                                      self._tile_rect(px, py, cam_x, cam_y))
                cursor = (pending.x, pending.y)
                for (sx, sy) in self.battle.damage_range(cursor, u):
                    self.surface.blit(self._damage_tint, self._tile_rect(sx, sy, cam_x, cam_y))
                self.surface.blit(self._focus_tint,
                                  self._tile_rect(cursor[0], cursor[1], cam_x, cam_y))
            return

        if phase == Phase.PLAYER_MOVE:
            # 蓝 = 移动范围 (move range, 含 lerp 中)
            for (x, y) in self.battle.turn_move_range:
                self.surface.blit(self._move_tint, self._tile_rect(x, y, cam_x, cam_y))
            # 白 = 攻击范围 preview (= AIM 阶段 cursor 可游走的格子集合).
            # 孙悟空 1×3 / 蒙面人 3×2. lerp 中不画 (避免跟着角色漂).
            if not moving:
                for (px, py) in self.battle.attack_range():
                    self.surface.blit(self._attack_range_tint,
                                      self._tile_rect(px, py, cam_x, cam_y))
            return

        # PLAYER_AIM: lerp 中不画 (AIM 阶段角色应已静止, 但保险一下)
        if moving:
            return

        # PLAYER_AIM: 隐藏移动范围. 三层叠加:
        #   Layer 1 (白): 攻击范围 = cursor 可游走的格子
        #   Layer 2 (红): 伤害范围 = 当前 cursor 对应的命中格 (跟着 cursor 变)
        #   Layer 3 (白焦点): cursor 自身 → 跟红叠加 = 浅红高亮
        for (px, py) in self.battle.aim_attack_range:
            self.surface.blit(self._attack_range_tint,
                              self._tile_rect(px, py, cam_x, cam_y))
        cur = self.battle.aim_cursor
        if cur is None:
            return
        for (sx, sy) in self.battle.damage_range(cur):
            self.surface.blit(self._damage_tint, self._tile_rect(sx, sy, cam_x, cam_y))
        self.surface.blit(self._focus_tint,
                          self._tile_rect(cur[0], cur[1], cam_x, cam_y))

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
