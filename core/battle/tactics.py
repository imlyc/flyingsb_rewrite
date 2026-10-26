"""TacticsBattle — 战斗主状态机. 持有 players / enemies / map / phase / turn_order.

实际结算 (伤害/反应/必杀) 转发到 core.battle.combat, AI 走位转发到 core.battle.ai,
空间查询 (occupant / movement_range / bfs_path / attack_tiles) 转发到 self.q
(BattleQueries 实例, 见 core.battle.queries).
本文件只管:
  - 摆阵 / 回合流转 (start_round, enter_current, end_unit_turn, post_enemy_turn)
  - 玩家行动公开 API (player_step / enter_attack_aim / confirm_attack_aim / ...)
  - anim_engine glue (engine.on signal → 派发)
  - 胜负检测 + 升级分配
"""

from __future__ import annotations

import random

from core.anim_engine.entity import Entity
from core.character import UNSET
from core.battle import ai, combat
from core.battle.aim_profiles import get_aim_funcs
from core.skill_patterns import compute_skill_pattern, compute_skill_strike
from core.battle.queries import BattleQueries
from core.battle.data import (
    BattleMap,
    BattleUnit,
    EXP_PER_LEVEL,
    LevelUpReport,
    Phase,
    default_battle_map,
)


class TacticsBattle:
    def __init__(
        self,
        players: list[BattleUnit],
        enemies: list[BattleUnit],
        battle_map: BattleMap | None = None,
        rng: random.Random | None = None,
        player_positions: list[tuple[int, int]] | None = None,
        enemy_positions: list[tuple[int, int]] | None = None,
        arena_mode: bool = False,
    ) -> None:
        self.rng = rng or random.Random()
        # 竞技场模式: 胜利不结算经验/金钱/升级 (纯对战沙盒)
        self.arena_mode = arena_mode
        self.players = players
        self.enemies = enemies
        self.map = battle_map or default_battle_map(rng=self.rng)
        # 空间查询: 共享 map/players/enemies 引用; 见 core.battle.queries
        self.q = BattleQueries(self.map, self.players, self.enemies)
        self.messages: list[str] = []
        self.exp_gained = 0
        self.money_gained = 0
        # 单位回合内的 "原位置" (取消移动用)
        self._pre_move_pos: tuple[int, int] | None = None
        # 本回合可达范围 (起点 BFS 缓存; 每回合开始更新)
        self.turn_move_range: set[tuple[int, int]] = set()
        self.phase = Phase.PLAYER_MOVE
        self._turn_order: list[BattleUnit] = []      # [当前行动者] (行动值制, 见 _pick_next)
        self._turn_idx = 0
        self.round_no = 0
        # 给 UI 的浮动伤害事件队列; UI 自己消费 + 计时
        from core.battle.data import DamageEvent  # 仅为类型, 实例由 combat 模块创建
        self.damage_events: list[DamageEvent] = []
        self.float_pending: int = 0                  # 未落定飘字数 (= exe dispatcher +0x3e), core.battle.float_digits
        self.float_events: list = []                 # ('flash'|'settled', unit), 场景每帧消费
        # 战斗胜利时填; UI 弹完才返回地图
        self.level_ups: list[LevelUpReport] = []
        # 敌方 AI 计算的待执行攻击 (在移动动画结束后才打出)
        self._pending_enemy_attack: BattleUnit | None = None
        self._pending_enemy_skill: int | None = None      # 敌人待放技能 (exe 敌人表的技能)
        self._pending_enemy_cursor: tuple[int, int] | None = None
        # 敌方 AI 延迟执行标志: ENEMY_TURN 进入时为 True (= 先显示移动范围),
        # scene pre-move 暂停结束后 UI 调 run_pending_enemy_ai 触发实际移动.
        self._enemy_ai_pending: bool = False
        # 攻击 SIGNAL -110 END 触发后, 等所有动画跑完才切回合 (= advance_turn_when_ready 触发)
        self._pending_turn_end: bool = False
        # AIM 阶段状态:
        #   aim_cursor:       当前 cursor 位置 (单格坐标)
        #   aim_attack_range: 攻击范围 (= cursor 可游走的格子集合, 见 attack_range())
        #   aim_skill_id:     当前 aim 的技能 ID, None = 普攻
        # 方向键在攻击范围内移动 cursor; shift+方向键转 facing 重算攻击范围.
        # 真伤害集合 = damage_range(cursor), 跟着 cursor 变.
        self.aim_cursor: tuple[int, int] | None = None
        self.aim_attack_range: set[tuple[int, int]] = set()
        self.aim_skill_id: int | None = None
        # AoE 攻击 (孙悟空横扫等) 确认时存的伤害范围. IMPACT 时一次性对其内所有敌人造伤.
        # None = 单点攻击, IMPACT 走 combat.apply_pending_attack 的默认 pending_attack_target 路径.
        self._pending_damage_range: set[tuple[int, int]] | None = None
        self._pending_damage_falloff: dict | None = None   # 伤害格 → 衰减权重 (core.battle.combat._falloff)
        # 动画引擎: 跑攻击 seq 字节码, 通过 SIGNAL 回调战斗逻辑.
        # UI 每 40ms 调一次 self.engine.tick() 推进所有 entity.
        from core.anim_engine.engine import Engine
        from core.anim_engine.entity import SIG_IMPACT, SIG_END, SIG_IMPACT_2
        self.engine = Engine()
        # 屏幕震动偏移 (px): 玄武地震等由 engine entity 每 tick 写随机抖动, scene.draw 叠加到相机.
        # (0,0) = 不震. 见 core.son_transform earthquake_think (exe FUN_004d8b0c 抖相机原点).
        self.shake_offset: tuple[int, int] = (0, 0)
        self.dim_level: float = 0.0          # 技能施放期间战场暗化 0..1 (core.battle.skill_dim)
        # 可见屏幕中心 (世界 px), 由 BattleScene 每帧发布. 满屏特效 (超亂舞滑板) 用它当
        # 框中心, 避免施法者靠地图/相机边缘时特效整体偏到半屏. None = 无 UI (headless 测试).
        self.view_center_world: tuple[int, int] | None = None
        self._SIG_IMPACT = SIG_IMPACT
        self._SIG_IMPACT_2 = SIG_IMPACT_2
        self._SIG_END = SIG_END
        self.engine.on('signal', self._on_anim_signal)
        self._place_units(player_positions, enemy_positions)
        self._zihe_battle_start()
        self._start_round()

    def _on_anim_signal(self, source_entity: Entity, sig: int) -> None:
        """anim_engine SIGNAL 路由:
          -100 IMPACT  (caster seq): 结算伤害 / B 类技能 spawn 投射物
          -250 IMPACT_2 (投射物落地): 投射物 think_fn 发, 强制走伤害结算流程
          -110 END     (caster seq): 结束攻击回合 (清 pending, 等死亡动画跑完切回合)
        """
        if sig == self._SIG_IMPACT_2:
            # 投射物落地 → 强制走完整伤害流程 (绕过 multi-impact dedup). 信号来源是投射物
            # entity (没 'unit' user_data), 但当前 pending attacker 还是 caster.
            caster = self._find_pending_attacker()
            if caster is not None:
                # B 类技能落地命中音 (exe dispatcher case -200 显式播, e.g. 火龍斬 0xbd)
                from core.skill_seq import SKILL_IMPACT2_SOUNDS
                snd = SKILL_IMPACT2_SOUNDS.get(caster.pending_skill_id, -1)
                if snd >= 0:
                    self.engine._emit('sound_play', source_entity, snd)
                # 让 apply_pending_attack 走最终结算分支: 把 count 提到 total 之上, 强制 last;
                # pending_impact2 让它跳过 "再 spawn 投射物" (skill_id 保留, MP/状态类分支还要看它)
                caster.pending_impact_count = caster.pending_impact_total - 1
                caster.pending_impact2 = True
                try:
                    combat.apply_pending_attack(self, caster)
                finally:
                    caster.pending_impact2 = False
                # B 类 cast seq 没 SIG_END, post_attack_anim 不会自动触发 — 这里手动收尾;
                # 来源实体标 defer_end (紫河 coordinator) 则由它等受击 seq 播完后再发 SIG_END (带 unit) 收尾
                if not source_entity.user_data.get('defer_end'):
                    self.post_attack_anim(caster)
            return
        unit = source_entity.user_data.get('unit')
        if unit is None:
            return
        # 技能 seq 专属信号 (jump -1000..-1005): exe dispatcher 在这些 case 播挥击音 / 登记命中音
        # (DAT_006566c0 → engine.swing_sound, IMPACT 时播). 表见 core.skill_seq.SKILL_SIGNAL_*.
        # 放在 coord 拦截之前: 破天舞 cdit1_g0 挥刀的 -1001 也要播 (coord 只吞 IMPACT/END).
        if sig <= -1000 and unit.pending_skill_id is None and getattr(unit, 'ra_coord', None) is not None:
            from core.ranged_attack import on_signal as _ra_signal
            if _ra_signal(self, unit, sig):          # 远程普攻专用信号 (RA_*)
                return
        if sig <= -1000 and unit.pending_skill_id is not None:
            from core.skill_seq import skill_signal_sounds
            play, hit = skill_signal_sounds(unit.pending_skill_id, sig)
            if play >= 0:
                self.engine._emit('sound_play', source_entity, play)
            if hit >= 0:
                self.engine.swing_sound = hit
            from core.skill_seq import SKILL_CAST_SIGNAL_HANDLERS
            h = SKILL_CAST_SIGNAL_HANDLERS.get(unit.pending_skill_id)
            if h is not None and h(self, unit, sig):
                return
        # 破天舞 PHASE_CASTER_DASH 期间, caster.entity 跑 cdit1_g0 的 'impact'/'end' 不走
        # 常规结算流程, 而是转发给 coord (coord 控制何时真正 SIG_IMPACT_2 + damage + END).
        coord = unit.pending_caster_coord
        if coord is not None:
            if sig == self._SIG_IMPACT:
                cb = coord.user_data.get('on_caster_impact')
                if cb is not None:
                    cb(coord, self.engine)
            # SIG_END / 其他: 都吞掉, coord 完成时自己收尾
            return
        if sig == self._SIG_IMPACT:
            combat.apply_pending_attack(self, unit)
            # 命中音 (swing sound): exe melee IMPACT `if(-1<DAT_006566c0) FUN_00416311(它)`.
            if self.engine.swing_sound >= 0:
                self.engine._emit('sound_play', source_entity, self.engine.swing_sound)
        elif sig == unit.pending_draw_signal:    # 挥砍/斩击音 (与挥刀帧同步; 信号因 char_id 组而异)
            if unit.pending_draw_sound >= 0:
                self.engine._emit('sound_play', source_entity, unit.pending_draw_sound)
        elif sig == self._SIG_END:
            if unit.pending_skill_id is None and unit.attack_cur is not None and unit.entity is not None:
                # 普攻 END (-110) 后 exe 末帧再显示 1 tick 才回待机 (实录 na0_00/03/07)
                unit.entity.user_data['hold_until_tick'] = self.engine._tick_id + 1
            self.post_attack_anim(unit)

    def _find_pending_attacker(self) -> BattleUnit | None:
        """找当前还有 pending_attack_target 的玩家/敌方单位 (= 正在攻击中的 caster)."""
        for u in self.all_units:
            if u.pending_attack_target is not None:
                return u
        return None

    # ---- 摆阵 ----
    def _place_units(
        self,
        player_positions: list[tuple[int, int]] | None,
        enemy_positions: list[tuple[int, int]] | None,
    ) -> None:
        if player_positions is not None:
            for p, pos in zip(self.players, player_positions):
                p.x, p.y = pos
        else:
            for i, p in enumerate(self.players):
                p.x, p.y = 1, min(self.map.h - 2, 1 + i * 2)
                while not self.q.is_free(p.x, p.y, p):
                    p.y = (p.y + 1) % self.map.h
        if enemy_positions is not None:
            for e, pos in zip(self.enemies, enemy_positions):
                e.x, e.y = pos
        else:
            for i, e in enumerate(self.enemies):
                e.x, e.y = self.map.w - 2, min(self.map.h - 2, 1 + i * 2)
                while not self.q.is_free(e.x, e.y, e):
                    e.y = (e.y + 1) % self.map.h
        # 摆阵后初始化渲染坐标 (避免开局所有人从 (0,0) 滑出来)
        for u in self.all_units:
            u.snap_render()

    # ---- 查询 (空间相关全部在 self.q; 这里只留回合/状态相关的) ----
    @property
    def all_units(self) -> list[BattleUnit]:
        return self.q.all_units

    @property
    def alive_units(self) -> list[BattleUnit]:
        return self.q.alive_units

    @property
    def current(self) -> BattleUnit:
        return self._turn_order[self._turn_idx]

    @property
    def turn_order(self) -> list[BattleUnit]:
        return self._turn_order

    @property
    def turn_idx(self) -> int:
        return self._turn_idx

    def next_actor(self) -> BattleUnit | None:
        """预测下一个行动者 (同 _pick_next 规则, 不改行动值; 本回合没人够 20 → 按下回合加速度后再挑)."""
        vals = {id(u): u.action_value for u in self.all_units}
        u = self._pick_next(dry=True)
        if u is None:
            for x in self.all_units:
                x.action_value += self._action_gain(x, dry=True)
            u = self._pick_next(dry=True)
            for x in self.all_units:
                x.action_value = vals[id(x)]
        return u

    # ---- 行动值 (exe FUN_004a4108 加速度 / FUN_004a432c 挑人) ----
    ACTION_COST = 20
    NO_ACT = 0x200 | 0x800                    # 睡眠 / 痲痺 (+ 倒地) 不加行动值也不被挑

    def _can_act(self, u: BattleUnit) -> bool:
        from core.battle.status import has_status
        return u.alive and not any(has_status(u, b) for b in (0x200, 0x800))

    def _action_gain(self, u: BattleUnit, dry: bool = False) -> int:
        """每回合加的行动值: 速度 (玩家装 坏的手表 0x146 → rand%(2×速度)); 中毒 ×3/4; 不能行动 0."""
        from core.battle.status import has_status
        if not self._can_act(u):
            return 0
        sp = u.speed if u.speed > 0 else max(1, u.agile)      # 无速度数据的单位 (测试/占位敌人) 用敏捷
        if u.is_player and 0x146 in getattr(u, 'equipment', ()) and not dry:
            sp = self.rng.randrange(max(1, sp * 2))
        if has_status(u, 0x100):
            sp = sp * 3 // 4
        return sp

    def _pick_next(self, dry: bool = False) -> BattleUnit | None:
        """FUN_004a432c: 行动值最高且 ≥ 20 的单位 (先扫我方再扫敌方, 同分后扫到的胜), 被挑中 -20."""
        best, thr = None, self.ACTION_COST
        for u in list(self.players) + list(self.enemies):
            if self._can_act(u) and u.action_value >= thr:
                best, thr = u, u.action_value
        if best is not None and not dry:
            best.action_value -= self.ACTION_COST
        return best

    # ---- 回合 ----
    def _start_round(self) -> None:
        # 状态回合递减 (exe 回合管理器 FUN_004a4f94 state 1 → FUN_004a3738, 每新回合对全体一次)
        from core.battle.status import round_tick
        round_tick(self.all_units)
        from core.battle import energy
        energy.round_start(self)                 # exe FUN_004a4108: SG 每回合 +1 (+装备加成)
        for z_u in self.players:                 # exe 新回合清 DAT_007e2d4c (待变身标记)
            if getattr(z_u, 'zihe', None) is not None:
                z_u.zihe['pending'] = False
        from core.battle import status_icons
        status_icons.sync(self, create=False)    # exe FUN_004a3c1f: 到期的状态摘图标
        for u in self.all_units:                 # exe FUN_004a4108: 行动值 += 速度 (敌人不能行动时清 0)
            if not u.is_player and not self._can_act(u):
                u.action_value = 0
            u.action_value += self._action_gain(u)
            u.has_acted = False
        self.refresh_status_snapshot(working=False)   # exe 新回合 FUN_004a4e42(0)
        self.round_no += 1
        self._log(f"--- 第 {self.round_no} 回合 (行动值 " +
                  ", ".join(f"{u.name}{u.action_value}" for u in self.alive_units) + ") ---")
        self._enter_current()

    def refresh_status_snapshot(self, working: bool = True) -> None:
        """exe FUN_004a4e42: 拷一份我方 HP/MP/SG/状态字给状态栏画 (状态栏不显示实时值).
        working: exe 参数 1 = 工作 HP, 0 = 角色表 HP; 我们只有一份 hp, 两者相同."""
        from core.battle.energy import status_snapshot
        self.status_snapshot = [status_snapshot(u) for u in self.players]

    def _zihe_turn_point(self, actor: BattleUnit) -> None:
        """exe FUN_004a4f94 case 0xb→0xc (每个单位**行动结束**后): 刚行动完的是已变身的紫河 (无保温瓶) → 变回;
        否则有待变身标记 → 变身. 即: 被打中 → 打她的单位行动完变身 → 她以兽形行动一次 → 这次行动完变回.
        换卡即刻生效, 闪烁 31t 只是表现."""
        from core.normal_attack import zihe_switch
        for z_u in self.players:
            z = getattr(z_u, 'zihe', None)
            if z is None or z['thermos'] or not z_u.alive:
                continue
            if z_u is actor and z['transformed']:
                zihe_switch(z_u, to_beast=False)
                self._log(f"{z_u.name} 变回人形")
            elif z['pending'] and not z['transformed']:
                z['pending'] = False
                zihe_switch(z_u, to_beast=True)
                self._log(f"{z_u.name} 变身 (形态 {z['form']})")

    def _zihe_battle_start(self) -> None:
        """exe FUN_004a31c8 case 5/6: 装了滿的保溫瓶 → 开战闪 31t 变身, 整场保持."""
        from core.normal_attack import zihe_switch
        for z_u in self.players:
            z = getattr(z_u, 'zihe', None)
            if z is not None and z['thermos']:
                zihe_switch(z_u, to_beast=True)

    def _enter_current(self) -> None:
        u = self._pick_next()
        if u is None:                             # 本回合没人行动值够 20 → 新回合
            if not any(self._action_gain(x, dry=True) > 0 for x in self.all_units):
                return                            # 谁都动不了 (全睡/痲痺): 防死循环
            self._start_round()
            return
        self._turn_order = [u]
        self._turn_idx = 0
        self.refresh_status_snapshot()           # exe case 3: 轮到单位行动 FUN_004a4e42(1)
        if u.is_player:
            self.phase = Phase.PLAYER_MOVE
            self._pre_move_pos = (u.x, u.y)
            self.turn_move_range = self.q.movement_range(u)
            return
        self.phase = Phase.ENEMY_TURN
        # 进入敌方回合前先算移动范围 (= AI 即将走的可达格集合).
        # AI take_turn 会立即把 unit.x/y 改到 dest, 所以必须现在算.
        self.turn_move_range = self.q.movement_range(u)
        # AI 延后执行: scene 显示移动范围一会儿后调 run_pending_enemy_ai.
        self._enemy_ai_pending = True            # 等 UI 调 run_pending_enemy_ai → 再调 post_enemy_turn

    def end_unit_turn(self) -> None:
        if self._turn_idx < len(self._turn_order):
            self._turn_order[self._turn_idx].has_acted = True
            self.refresh_status_snapshot()           # exe case 0xb: 行动结束 FUN_004a4e42(1), 在紫河判定之前
            self._zihe_turn_point(self._turn_order[self._turn_idx])
        self._pre_move_pos = None
        if self._check_end():
            return
        self._enter_current()

    def run_pending_enemy_ai(self) -> None:
        """scene 在 pre-move 暂停结束后调: 实际执行 AI 移动/攻击计划."""
        if not self._enemy_ai_pending or self.phase != Phase.ENEMY_TURN:
            return
        self._enemy_ai_pending = False
        ai.take_turn(self, self.current)
        self._check_end()

    def post_enemy_turn(self) -> None:
        """UI 在 ENEMY_TURN 走动动画结束后调用: 启动攻击动画 (走 attack_seq), UI 推完才结束回合.
        如果没有待发攻击 (= 没攻击范围或 AI 选择不攻击), 直接 end_unit_turn.
        """
        if self.phase != Phase.ENEMY_TURN:
            return
        from core.bosan_skills import mine_at, trigger_mine
        if not self.current.is_player and mine_at(self, self.current):
            # exe FUN_004a4f94 case 4: 敌人移动完站在地雷上 → 本回合改为引爆地雷 (招式 247), 不再攻击
            self._pending_enemy_attack = None
            self._pending_enemy_skill = None
            self._pending_enemy_cursor = None
            self._pending_damage_range = None
            self._pending_damage_falloff = None
            trigger_mine(self, self.current)
            return
        if self._pending_enemy_attack is not None and self._pending_enemy_attack.alive:
            sid = self._pending_enemy_skill
            cursor = self._pending_enemy_cursor
            target = self._pending_enemy_attack
            self._pending_enemy_attack = None
            self._pending_enemy_skill = None
            self._pending_enemy_cursor = None
            u = self.current
            if sid is None:
                self._pending_damage_range = None
                self._pending_damage_falloff = None
            # 敌招 (现只用第 0 招当普攻): exe FUN_004a6efe 开头 敌 MP -= 招式表 +0xc
            u.pending_enemy_move = u.enemy_moves[0] if (sid is None and u.enemy_moves) else None
            if u.pending_enemy_move is not None:
                from core.battle.formulas import enemy_move
                u.mp = max(0, u.mp - enemy_move(u.pending_enemy_move)['mp_cost'])
            try:
                combat.begin_attack(self, self.current, target,
                                    skill_id=sid, cursor=cursor)
            except Exception as e:      # 技能 seq 缺失等 → 回退普攻
                print(f"[AI] 敌人技能 {sid} 执行失败, 回退普攻: {e}")
                self._pending_damage_range = None
                self._pending_damage_falloff = None
                if target.alive:
                    combat.begin_attack(self, self.current, target)
            return  # UI 跑 attack_seq, 命中点回调 apply_pending_attack, 'end' 回调 post_attack_anim
        self._pending_enemy_attack = None
        if self._check_end():
            return
        self.end_unit_turn()

    def _check_end(self) -> bool:
        if not any(p.alive for p in self.players):
            self.phase = Phase.DEFEAT
            self._log("我方全员阵亡, 战斗失败")
            return True
        if not any(e.alive for e in self.enemies):
            self.phase = Phase.VICTORY
            if self.arena_mode:
                self._log("敌人全灭! (竞技场模式: 无经验结算)")
            else:
                self.exp_gained = sum(e.exp_reward for e in self.enemies)
                self.money_gained = sum(e.money_reward for e in self.enemies)
                self._log(f"敌人全灭! 经验+{self.exp_gained} 金钱+{self.money_gained}")
                self._allocate_levelups()
            return True
        return False

    def _allocate_levelups(self) -> None:
        """战斗胜利时分配经验, 触发升级 + 生成升级报告.

        有原版数据 (assets/characters_table.json) 时用**真实经验表 + 成长表**:
        逐级扣 exp_needed(level), 应用 growth_gains(level) 到 HP/MP/攻/防.
        缺数据时回退旧的随机成长占位.
        """
        from core import character_data
        survivors = [p for p in self.players if p.alive]
        if not survivors or self.exp_gained <= 0:
            return
        per = self.exp_gained // len(survivors)
        real = bool(character_data.records())
        for p in survivors:
            levels = 0
            hp_inc = mp_inc = atk_inc = def_inc = 0
            if real:
                remaining = per
                while p.level < character_data.MAX_LEVEL:
                    need = character_data.exp_needed(p.level)
                    if need <= 0 or remaining < need:
                        break
                    remaining -= need
                    g = character_data.growth_gains(p.name, p.level + 1)
                    p.level += 1
                    levels += 1
                    hp_inc += g.get("MaxHP", 0)
                    mp_inc += g.get("MaxMP", 0)
                    atk_inc += g.get("base_atk", 0)
                    def_inc += g.get("base_def", 0)
            else:
                levels = per // EXP_PER_LEVEL
                if levels <= 0:
                    continue
                hp_inc = sum(self.rng.randint(3, 8) for _ in range(levels))
                mp_inc = sum(self.rng.randint(0, 3) for _ in range(levels))
                atk_inc = sum(self.rng.randint(1, 3) for _ in range(levels))
                def_inc = sum(self.rng.randint(1, 3) for _ in range(levels))
                p.level += levels
            if levels <= 0:
                continue
            p.max_hp += hp_inc
            p.hp = min(p.max_hp, p.hp + hp_inc)  # 原版升级回满
            p.max_mp += mp_inc
            p.mp = min(p.max_mp, p.mp + mp_inc)
            p.attack += atk_inc
            p.defence += def_inc
            if real:   # 升级后刷新已学技能 (按真实学习表)
                learned = character_data.learned_skills(p.name, p.level)
                if learned:
                    p.known_skills = learned
            self.level_ups.append(LevelUpReport(
                name=p.name, new_level=p.level, gained_levels=levels,
                hp_inc=hp_inc, mp_inc=mp_inc, atk_inc=atk_inc, def_inc=def_inc,
            ))

    # ---- 玩家行动 ----
    def player_step(self, dx: int, dy: int) -> bool:
        """方向键: 总是更新朝向; 若朝向格在本回合可达范围且空闲, 走一步."""
        u = self.current
        if self.phase != Phase.PLAYER_MOVE or not u.is_player:
            return False
        u.facing = (dx, dy)
        nx, ny = u.x + dx, u.y + dy
        if (nx, ny) not in self.turn_move_range:
            return False
        if not self.map.passable(nx, ny):
            return False
        if self.q.occupant(nx, ny, ignore=u) is not None:
            return False
        u.x, u.y = nx, ny
        return True

    def attack_range(self, u: BattleUnit | None = None,
                     skill_id: int | None = None) -> set[tuple[int, int]]:
        """攻击范围: cursor 在 AIM 阶段可游走的格子集合. 不改 phase, 可在 MOVE 阶段
        做 preview 用. 普攻按角色 profile (孙悟空 1×3 / 蒙面人 3×2), 技能按 skill pattern."""
        u = u or self.current
        if skill_id is not None:
            return compute_skill_pattern(u, self.map, skill_id)
        idx = self._normal_attack_idx(u)
        if idx is not None:
            from core.normal_attack import entry
            from core.skill_patterns import compute_template_pattern
            return compute_template_pattern(u, self.map, entry(idx).template)
        pattern_fn, _ = get_aim_funcs(u.name)
        return pattern_fn(u, self.map)

    def _normal_attack_idx(self, u: BattleUnit) -> int | None:
        """普攻表项: 瞄准中 = 进瞄准时定下的 (贴身 → 近身项); 其余 (移动阶段预览) = +0x74 (exe FUN_004a4f94 同)."""
        if u.attack_normal is None:
            return None
        if self.phase == Phase.PLAYER_AIM and u is self.current and self.aim_skill_id is None and u.attack_cur is not None:
            return u.attack_cur
        return u.attack_normal

    def damage_range(self, cursor: tuple[int, int],
                     u: BattleUnit | None = None,
                     skill_id: int | None = None) -> set[tuple[int, int]]:
        """伤害范围: cursor 上按下确认后实际命中的 tile 集合. 跟着 cursor 移动而变.
        普攻按角色 profile (孙悟空 3 格垂直线 / 蒙面人 / 默认 单格);
        技能按 exe pattern. skill_id=None 时若处于 PLAYER_AIM 自动取 aim_skill_id."""
        u = u or self.current
        if skill_id is None and self.phase == Phase.PLAYER_AIM:
            skill_id = self.aim_skill_id
        if skill_id is not None:
            return {(x, y) for (x, y) in compute_skill_strike(u, cursor, skill_id, self.map)
                    if self.map.in_bounds(x, y)}
        idx = self._normal_attack_idx(u)
        if idx is not None:
            from core.normal_attack import entry
            from core.skill_patterns import compute_template_strike
            return {(x, y) for (x, y) in compute_template_strike(u, cursor, entry(idx).template, self.map)
                    if self.map.in_bounds(x, y)}
        _, strike_fn = get_aim_funcs(u.name)
        return {(x, y) for (x, y) in strike_fn(u, cursor) if self.map.in_bounds(x, y)}

    def damage_falloff(self, cursor: tuple[int, int], u: BattleUnit | None = None,
                       skill_id: int | None = None) -> dict[tuple[int, int], int]:
        """伤害格 → 衰减权重 (8 = 满额), 与 damage_range 同一 pattern (core.skill_patterns.strike_falloff)."""
        from core.skill_patterns import strike_falloff, SKILL_TEMPLATE
        u = u or self.current
        if skill_id is not None:
            tmpl = SKILL_TEMPLATE.get(skill_id)
        else:
            idx = self._normal_attack_idx(u)
            if idx is None:
                return {}
            from core.normal_attack import entry
            tmpl = entry(idx).template
        return strike_falloff(u, cursor, tmpl)

    def _pick_initial_cursor(self, u: BattleUnit,
                             rng: set[tuple[int, int]]) -> tuple[int, int] | None:
        """AIM 初始 cursor: 1) self-cast (unit 自己在范围内) → unit;
        2) 沿 facing 中轴 d=1..11 找第一格在范围内 → 该格;
        3) 兜底: 按 (forward 投影最大, |side| 最小, 字典序) 确定性挑.
        ⚠ 不能用 next(iter(rng)) — set 顺序不稳定, cursor 会跳."""
        if not rng:
            return None
        if (u.x, u.y) in rng:
            return (u.x, u.y)
        fx, fy = u.facing
        for d in range(1, 12):
            cand = (u.x + fx * d, u.y + fy * d)
            if cand in rng:
                return cand
        def key(t):
            dx, dy = t[0] - u.x, t[1] - u.y
            forward = dx * fx + dy * fy
            side = abs(dx * (-fy) + dy * fx)
            return (-forward, side, t)
        return min(rng, key=key)

    def enter_attack_aim(self, skill_id: int | None = None) -> bool:
        """从 PLAYER_MOVE 进入 PLAYER_AIM (= 选攻击目标阶段).
        计算攻击范围, cursor 初始 = facing 前一格 (若在范围中) 或范围第一格.
        skill_id=None 普攻; 否则按技能算 (远程多格).
        """
        u = self.current
        if self.phase != Phase.PLAYER_MOVE or not u.is_player:
            return False
        if skill_id is not None:
            from core.battle import energy
            if not energy.can_cast(u, skill_id):     # exe FUN_0042878a: MP / SG 不够 → 菜单灰掉选不了
                return False
        if skill_id is None:
            # FUN_004a47d3: 开普攻那一刻定普攻项 — 上下左右有可打敌人 → 贴身项 (+0x78), 否则 +0x74
            from core.normal_attack import current_attack
            u.attack_cur = current_attack(self, u, aiming=True)
        self.aim_skill_id = skill_id
        self.phase = Phase.PLAYER_AIM
        rng = self.attack_range(u, skill_id)
        if not rng:
            self.phase = Phase.PLAYER_MOVE
            return False
        self.aim_skill_id = skill_id
        self.aim_attack_range = rng
        self.aim_cursor = self._pick_initial_cursor(u, rng)
        return True

    def aim_move_cursor(self, dx: int, dy: int) -> bool:
        """AIM 方向键: cursor 在攻击范围内移动一步. 越出 → 不变."""
        if self.phase != Phase.PLAYER_AIM or self.aim_cursor is None:
            return False
        nx, ny = self.aim_cursor[0] + dx, self.aim_cursor[1] + dy
        if (nx, ny) in self.aim_attack_range:
            self.aim_cursor = (nx, ny)
            return True
        return False

    def aim_turn_facing(self, dx: int, dy: int) -> bool:
        """AIM shift+方向键: 转 facing, 重算攻击范围 + cursor 重置到新 facing 前一格.
        让远程攻击的攻击范围跟着朝向旋转, 普攻则单格 cursor 跳到新方向.
        """
        u = self.current
        if self.phase != Phase.PLAYER_AIM or not u.is_player:
            return False
        u.facing = (dx, dy)
        rng = self.attack_range(u, self.aim_skill_id)
        if not rng:
            return False
        self.aim_attack_range = rng
        self.aim_cursor = self._pick_initial_cursor(u, rng)
        return True

    def confirm_attack_aim(self) -> bool:
        """AIM 阶段 Enter: 攻击 cursor 对应伤害范围上所有敌人.
        统一走 combat.begin_attack 拿 attack_seq 动画.
        primary = cursor 上的敌人 (优先) 或伤害范围内任一. IMPACT 时若 _pending_damage_range
        非 None, 一次性损伤所有伤害格的敌人 (AoE); 否则只伤 primary (单点).
        命中 0 个敌人 → 返回 False, 让 UI log 提示.
        """
        if self.phase != Phase.PLAYER_AIM or self.aim_cursor is None:
            return False
        u = self.current
        from core.skill_seq import is_heal_skill
        from core.skill_table import skill_targets_allies
        # 回复/状态类技能 (exe SKILL 表 flags 0x01000000) 选友军 (is_player 相同); 攻击技能选敌人.
        heal = is_heal_skill(self.aim_skill_id) or skill_targets_allies(self.aim_skill_id)
        if self.aim_skill_id == 0x35:
            # 裝置地雷: 目标是空格子 (exe FUN_004a6efe: 可通行/无人/无雷/<30), 自己当 pending 目标占位
            from core.bosan_skills import can_place_mine
            if not can_place_mine(self, self.aim_cursor):
                return False
            self._pending_damage_range = None
            self._pending_damage_falloff = None
            from core.battle import energy
            energy.pay(u, 0x35)
            combat.begin_attack(self, u, u, skill_id=0x35, cursor=self.aim_cursor)
            self._clear_aim_overlay()
            return True
        dmg_tiles = self.damage_range(self.aim_cursor)
        targets = []
        from core.skills import REVIVE_SKILLS
        revive = self.aim_skill_id in REVIVE_SKILLS
        for (x, y) in dmg_tiles:
            occ = self.q.occupant(x, y)
            if occ is None or (not occ.alive and not (revive and occ.is_player == u.is_player)):
                continue                         # 复活类技能 (回生舞步/強力慢曲/甦生/重生) 可选倒地队友
            same_side = occ.is_player == u.is_player
            if (heal and same_side) or (not heal and not same_side):
                targets.append(occ)
        if not targets:
            return False
        # primary target: cursor 上的优先 (= 动画落点最合理)
        cx, cy = self.aim_cursor
        cur_occ = self.q.occupant(cx, cy)
        primary = cur_occ if cur_occ in targets else targets[0]
        # AoE: 缓存伤害范围给 IMPACT 扫. 单点攻击保持 None 走默认路径.
        self._pending_damage_range = dmg_tiles if len(dmg_tiles) > 1 else None
        self._pending_damage_falloff = self.damage_falloff(self.aim_cursor, u, self.aim_skill_id)
        from core.battle import energy
        energy.pay(u, self.aim_skill_id)         # exe FUN_004a6efe act==2: 出手扣 MP / SG
        # 孙悟空变身技能: 不走标准 attack seq, 由 son_transform coordinator 驱动翻跟头隐现 +
        # 神兽 + AOE 伤害. 手动设 pending (begin_attack 的子集, 不 attach caster seq).
        from core.son_transform import is_son_transform_skill, start_son_transform
        if is_son_transform_skill(self.aim_skill_id):
            u.pending_attack_target = primary
            u.pending_attack_cursor = self.aim_cursor
            u.pending_attack_skill = True
            u.pending_skill_id = self.aim_skill_id
            u.pending_impact_count = 0
            u.pending_impact_total = 1
            start_son_transform(self, u, self.aim_cursor, self.aim_skill_id)
            self._clear_aim_overlay()
            return True
        combat.begin_attack(self, u, primary, skill_id=self.aim_skill_id,
                            cursor=self.aim_cursor)
        self._clear_aim_overlay()
        return True

    def _clear_aim_overlay(self) -> None:
        """攻击/施法已确认 → 清 AIM 高亮 (红伤害范围 / 白攻击范围 / cursor 消失), 攻击走 pending_*."""
        self.aim_cursor = None
        self.aim_attack_range = set()

    def cancel_attack_aim(self) -> bool:
        """AIM 阶段 ESC: 取消, 退回 PLAYER_MOVE. 清 cursor / 攻击范围."""
        if self.phase != Phase.PLAYER_AIM:
            return False
        self.phase = Phase.PLAYER_MOVE
        self.aim_cursor = None
        self.aim_attack_range = set()
        self.aim_skill_id = None
        return True

    def post_attack_anim(self, attacker: BattleUnit) -> None:
        """UI 在 attack_seq END 时调: 清攻击状态. *不立即* 切回合 — 标记 pending,
        scene 等所有动画 (伤害数字 + 死亡动画) 跑完才调 advance_turn_when_ready()."""
        was_skill = attacker.pending_skill_id is not None
        sid = attacker.pending_skill_id
        hold = attacker.cast_hold
        combat.clear_pending_attack(attacker)
        self._pending_damage_range = None
        self._pending_damage_falloff = None
        from core.battle import status_icons
        ent = None
        if was_skill:
            from core.battle.skill_dim import end_skill_dim

            def _after_fade():
                if hold:
                    attacker.cast_hold = False
                status_icons.sync(self)          # exe FUN_004cbc9d case 1: dispatcher (含渐亮) 结束后才按状态挂/摘图标
            # 渐亮 (projectile 实体, 回合切换等它完). 施法者放手时机按 dispatcher 模板: 多数在渐亮**结束** (0x28 后 |= 0x10000);
            # 少数 (core.jah_skills.IDLE_BEFORE_FADE) 在进渐亮前已由协调实体把 cast_hold 清掉 → 这里 hold=False 不再保持
            ent = end_skill_dim(self, on_done=_after_fade, skill_id=sid)
            if ent is not None and hold:
                attacker.cast_hold = True
        if ent is None:
            status_icons.sync(self)              # 没有渐亮: 行动结束当刻挂图标
        self._pending_turn_end = True

    def advance_turn_when_ready(self) -> None:
        """scene 在 _units_animating() 全部清空后调; 处理 pending turn 切换."""
        if not self._pending_turn_end:
            return
        self._pending_turn_end = False
        if self._check_end():
            return
        self.end_unit_turn()

    def cancel_to_move(self) -> bool:
        """把单位拉回本回合起点位置 (X 键)."""
        u = self.current
        if self.phase != Phase.PLAYER_MOVE or self._pre_move_pos is None:
            return False
        u.x, u.y = self._pre_move_pos
        return True

    # 兼容旧测试: 直接跳到任意可达格 (UI 不再用)
    def player_move(self, x: int, y: int) -> bool:
        u = self.current
        if self.phase != Phase.PLAYER_MOVE or not u.is_player:
            return False
        if (x, y) not in self.turn_move_range:
            return False
        if (x, y) != (u.x, u.y) and self.q.occupant(x, y) is not None:
            return False
        u.x, u.y = x, y
        return True

    def player_end_turn(self) -> None:
        """结束当前角色的回合."""
        if self.phase == Phase.PLAYER_MOVE:
            self.end_unit_turn()

    # ---- 工具 ----
    def _log(self, msg: str) -> None:
        self.messages.append(msg)
        if len(self.messages) > 64:
            self.messages = self.messages[-64:]
