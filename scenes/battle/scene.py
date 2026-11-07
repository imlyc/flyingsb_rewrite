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
    # 范围格 (exe FUN_004b463c): 每格取 "格子标记 & 掩码 0x7e2d50" 的低 3 位 (1 移动 / 2 攻击 / 4 伤害), 用调色板 0xdf+值 隔像素画
    # 棋盘格 (另一半像素露出地面). 颜色 = exe 0x654d7c 表 (FUN_004c8184 送到调色板 0xe0..0xe5), 两位重叠是表里单独的颜色.
    RANGE_COLORS = {1: (50, 70, 180), 2: (140, 140, 150), 3: (100, 120, 195),
                    4: (255, 90, 40), 5: (0, 0, 0), 6: (220, 110, 80)}
    RANGE_MOVE, RANGE_ATTACK, RANGE_DAMAGE = 1, 2, 4
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
        self._range_tiles: dict = {}         # (格子值, 奇偶) → 棋盘格 tile
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
                and not update_mod.death_animations_pending(self)
                and getattr(self.battle, 'victory_revert', None) is None):
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

    def _range_cells(self) -> dict:
        """各格的范围位 (exe 掩码 0x7e2d50 只会是 0/1/3/6; FUN_004a4f94 第 4 步 + FUN_004af268/FUN_004b1286):
        我方选位: 1 (移动), 站定后 |2 (攻击范围); 瞄准: 6 (攻击 + 伤害).
        敌方走格: 只移动 = 1, 已选定招式 (FUN_004af268) = 3; 走到位后出招前 20 tick: 6. 菜单开着 (0x7e2ddc) 不画."""
        u = self.battle.current
        phase = self.battle.phase
        if phase not in (Phase.PLAYER_MOVE, Phase.PLAYER_AIM, Phase.ENEMY_TURN):
            return {}
        moving = (abs(u.render_x - u.x) > self.ANIM_EPSILON
                  or abs(u.render_y - u.y) > self.ANIM_EPSILON)
        cells: dict = {}

        def mark(tiles, bit):
            for t in tiles:
                cells[t] = cells.get(t, 0) | bit

        M, A, D = self.RANGE_MOVE, self.RANGE_ATTACK, self.RANGE_DAMAGE
        if phase == Phase.ENEMY_TURN and not u.is_player:
            pending = self.battle._pending_enemy_attack
            if self.battle._enemy_ai_pending or moving or u.move_path:
                mark(self.battle.turn_move_range, M)
                if pending is not None:
                    mark(self.battle.attack_range(u), A)
            elif pending is not None and not u.is_attacking:
                mark(self.battle.attack_range(u), A)
                # 招式的光标/伤害范围以 AI 出招时算出的为准 (群体招罩多格)
                cursor = self.battle._pending_enemy_cursor or (pending.x, pending.y)
                strike = self.battle._pending_damage_range
                if strike is None:
                    strike = {cursor} if self.battle._pending_enemy_move is not None else self.battle.damage_range(cursor, u)
                mark(strike, D)
            return cells
        if phase == Phase.PLAYER_MOVE:
            if self._menu is not None:
                return cells
            mark(self.battle.turn_move_range, M)
            if not moving:
                mark(self.battle.attack_range(), A)
            return cells
        if moving:
            return cells
        mark(self.battle.aim_attack_range, A)
        cur = self.battle.aim_cursor
        if cur is not None:
            mark(self.battle.damage_range(cur), D)
        return cells

    def _draw_overlays(self, cam_x: int, cam_y: int) -> None:
        for (x, y), bits in self._range_cells().items():
            if bits in self.RANGE_COLORS:
                r = self._tile_rect(x, y, cam_x, cam_y)
                self.surface.blit(self._range_tile(bits, (r.x + r.y) & 1), r)

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
    def _range_tile(self, bits: int, parity: int) -> pygame.Surface:
        """棋盘格 tile: 屏幕坐标 (x+y) 为偶数的像素画纯色 (原版连拍实测), parity = tile 左上角 (x+y) 的奇偶."""
        key = (bits, parity)
        s = self._range_tiles.get(key)
        if s is None:
            s = pygame.Surface((TILE_W, TILE_H), pygame.SRCALPHA)
            c = self.RANGE_COLORS[bits]
            for y in range(TILE_H):
                for x in range((y + parity) & 1, TILE_W, 2):
                    s.set_at((x, y), c)
            self._range_tiles[key] = s
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
