"""战棋战斗场景 — 协调器.

战斗发生在世界地图上, 不切场景. 拆分:
  update.py   每帧 tick (位置/动画/伤害/引擎/相机/回合切换)
  input.py    handle_event + 玩家长按 polling
  units.py    单位渲染 (live/dying/dead/blink/facing)
  hud.py      HUD/菜单/banner/日志/升级框

操作:
  方向键   走 1 格 + 转面向 (走不了就只转身); 走过的格子计入本回合可达范围
  Enter    攻击当前面向格子上的敌人 (近战范围内). 没敌人则无动作.
  ESC      调出行动菜单 (上=技能 / 左=道具 / 右=设置 / 下=回合结束)
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
from scenes.battle import enemy_panel
from scenes.battle import hud as hud_mod
from scenes.battle import input as input_mod
from scenes.battle import units as units_mod
from scenes.battle import update as update_mod
from scenes.battle.hit_effect import draw_effect, draw_effect_shadow, effect_drawn

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
    MOVE_NUM_COLOR = (140, 200, 255)
    SHADOW = (0, 0, 0, 110)

    # ---- 时序常量 ----
    ENEMY_TURN_DELAY_MS = 350     # 走完 + 攻击前停顿 (显示攻击/伤害范围)
    ENEMY_PRE_MOVE_PAUSE_MS = 450  # ENEMY_TURN 进入后先停这么久显示移动范围, 然后才 AI 移动
    CAMERA_LERP = 0.18            # 镜头平滑系数 (0=不移, 1=瞬移)
    WALK_HOLD_DELAY_MS = 80       # 按住方向键超过此时长才自动连走
    # 受击表现: 原版是硬切, 不做位移/混合插值. 加位移插值反而违和.
    ANIM_EPSILON = 0.05           # render 与逻辑差小于此值视为已到位
    HUD_TOP_BUFFER = 96           # 镜头顶部预留 (px), 让 HUD 不挡角色
    LOG_BOTTOM_BUFFER = 116       # 镜头底部预留 (px), 让日志不挡角色

    # 死亡动画时长 (ms). exe FUN_004399c5/9b42 等 +0x124=0x14 = 20 ticks/帧 = 800ms.
    # 只 2 帧: row 4 col 0 (倒下中) + col 1 (躺平 corpse).
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
        # 道具栏: 剧情战斗 = 存档的 inventory; 竞技场的 "world_map" 是 terrain 没有 save → None
        # (子类可自行塞一个沙盒 Inventory). 道具菜单/使用都只走这个引用, 不再碰 world_map.save.
        save = getattr(world_map, 'save', None)
        self.inventory = getattr(save, 'inventory', None)
        self.return_scene = return_scene
        self.font = load_chinese_font(18)
        self.small = load_chinese_font(13)
        self.tiny = load_chinese_font(11)
        self.float_font = load_chinese_font(20)
        self.big = load_chinese_font(36)

        self._enemy_turn_started_at: int | None = None
        self._enemy_pre_move_started_at: int | None = None
        self._battle_over_signaled = False
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
        # 行动菜单: 移动态 ESC 开原版菜单系统 (scenes.battle.battle_menu: 十字窗口 0xf → 道具 / 特殊能力 / 战斗设定); None = 没开
        self._menu = None
        # 敌招名横幅 (scenes.battle.technique, 战斗设定「攻击技术」); None = 没有
        self._technique = None
        self._technique_acc = 0
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
        # 1.5) 技能暗化: 原版施法期间地形色段 (调色板 16..111) 渐变到 50% 亮度, 角色/特效不变 (core.battle.skill_dim)
        dim = getattr(self.battle, 'dim_level', 0.0)
        if dim > 0.0:
            shade = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
            shade.fill((0, 0, 0, int(min(1.0, dim) * 0.5 * 255)))   # exe 只把地形色段 (16..111) 乘 50%
            self.surface.blit(shade, (0, 0))
        # 2) 移动 / 攻击高亮
        self._draw_overlays(cam_x, cam_y)
        # 3) 单位与特效 (含飘字): 原版统一精灵队列 — 影子全部先画, 其余按地面 y 选择排序 (core.battle.draw_queue)
        drawn = self._draw_world(cam_x, cam_y)
        # 3.2) 敌人状态面板 (精灵之上, exe FUN_004cf98d)
        enemy_panel.draw(self, drawn)
        # 3.5) 敌招名横幅 (画面框中心)
        if self._technique is not None:
            sw, sh = self.surface.get_size()
            self._technique.draw(self.surface, (0, 0, sw, sh))
        # 4) HUD (不滚动) + 日志
        hud_mod.draw_hud(self)
        hud_mod.draw_log(self)
        # 5) 行动菜单 (原版菜单系统窗口 + 光标)
        if self._menu is not None:
            self._menu.draw(self.surface)
        # 8) 胜负 (等死亡动画跑完再出 banner, 否则技能秒杀最后一个敌人会跳过死亡演出)
        if (self.battle.phase in (Phase.VICTORY, Phase.DEFEAT)
                and not update_mod.death_animations_pending(self)):
            hud_mod.draw_end_banner(self)

    def _draw_world(self, cam_x: int, cam_y: int) -> list:
        """exe FUN_004c8184: 单位 (槽序在前) + 可见特效 (池序) 进队列, 键 = 地面 y; 影子项键 0 先画; 选择排序后依次画."""
        from core.battle import draw_queue
        b = self.battle
        unit_ents = {id(u.entity) for u in b.all_units if u.entity is not None}
        units = [u for u in draw_queue.unit_slot_order(b.players, b.enemies)
                 if units_mod.unit_drawn(self, u, cam_x, cam_y)]
        effects = [e for e in b.engine.entities if id(e) not in unit_ents and effect_drawn(e)]
        for u in units:
            units_mod.draw_unit_shadow(self, u, cam_x, cam_y)
        def cam_of(e):
            """跟随单位的特效 (状态图标) 随单位一起做 tick 间插值, 否则走格时比单位早一 tick."""
            u = e.user_data.get('unit') if e.user_data.get('status_icon') else None
            if u is None or u.loco_prev is None:
                return cam_x, cam_y
            rx, ry = self._unit_draw_pos(u)
            return cam_x - round((rx - u.render_x) * TILE_W), cam_y - round((ry - u.render_y) * TILE_H)
        for e in effects:
            draw_effect_shadow(self, e, *cam_of(e))
        items = [(True, u, units_mod.unit_ground_y(self, u)) for u in units] + \
                [(False, e, draw_queue.entity_key(e)) for e in effects]
        for is_unit, obj, _ in draw_queue.selection_sort(items, key=lambda it: it[2]):
            if is_unit:
                units_mod.draw_unit(self, obj, cam_x, cam_y)
            else:
                draw_effect(self, obj, *cam_of(obj))
        return units

    # ------- 行动菜单 -------
    def open_menu(self) -> None:
        """移动态 Esc: 开菜单系统 + 十字窗口 0xf (exe 0x7e2ddc = 1)."""
        from scenes.battle.battle_menu import BattleMenu, cross_center
        u = self.battle.current
        inv = self.inventory if self.inventory is not None else _EmptyInventory()
        self._menu = BattleMenu(self.audio, inv, u, cross_center(self, u))

    def use_consumable(self, item_id: int) -> None:
        """道具窗口选中: 进道具瞄准 (模板按道具, core.item_use.item_template), Enter 确认后才使用并扣背包 (原版: 用完结束该角色回合).
        没有一个目标生效 (如煙霧彈 / 雙光, 或对象没有该异常) 时确认不成立, 留在瞄准 (exe FUN_004a6efe 返回 0)."""
        u = self.battle.current
        if u is None or not u.is_player or self.inventory is None:
            return
        if self.battle.enter_item_aim(item_id):
            self._input_gated = False

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
                # 招式的光标/伤害范围以 AI 出招时算出的为准 (群体招罩多格; 以前一律按普攻在目标脚下画单格)
                cursor = self.battle._pending_enemy_cursor or (pending.x, pending.y)
                strike = self.battle._pending_damage_range
                if strike is None:
                    strike = {cursor} if self.battle._pending_enemy_move is not None else self.battle.damage_range(cursor, u)
                for (sx, sy) in strike:
                    self.surface.blit(self._damage_tint, self._tile_rect(sx, sy, cam_x, cam_y))
                self.surface.blit(self._focus_tint,
                                  self._tile_rect(cursor[0], cursor[1], cam_x, cam_y))
            return

        if phase == Phase.PLAYER_MOVE:
            if self._menu is not None:           # exe: 菜单系统开着 (0x7e2ddc = 1) 不画移动 / 攻击范围
                return
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
        """用 render_x/y (浮点 tile) 算单位的渲染像素 rect. 走格时在上一 tick 与本 tick 坐标间按 tick 内已过时间插值:
        逻辑每 30ms 走 1/4 格, 画面 60fps — 不插值的话有的 16px 停 2 帧有的停 1 帧, 看着卡顿 (原版 1 帧 = 1 tick 没这问题)."""
        rx, ry = self._unit_draw_pos(u)
        px = int(round(rx * TILE_W)) - cam_x
        py = int(round(ry * TILE_H)) - cam_y
        return pygame.Rect(px, py, TILE_W, TILE_H)

    def _unit_draw_pos(self, u) -> tuple[float, float]:
        """画面坐标 (浮点 tile): 走格时上一 tick → 本 tick 按 tick 内已过时间插值."""
        rx, ry = u.render_x, u.render_y
        if u.loco_prev is not None:
            from scenes.battle.update import LOCO_TICK_MS
            f = min(1.0, getattr(self, "_loco_acc", 0) / LOCO_TICK_MS)
            px0, py0 = u.loco_prev
            rx, ry = px0 + (rx - px0) * f, py0 + (ry - py0) * f
        return rx, ry

    def _compute_camera_offset(self, focus_x: float, focus_y: float) -> tuple[float, float]:
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


class _EmptyInventory:
    """竞技场等无存档背包: 道具列表为空."""

    def count(self, item_id: int) -> int:
        return 0
