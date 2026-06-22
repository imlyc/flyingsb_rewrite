"""TacticsBattle — 战斗主状态机. 持有 players / enemies / map / phase / turn_order.

实际结算 (伤害/反应/必杀) 转发到 core.battle.combat, AI 走位转发到 core.battle.ai,
空间查询 (occupant / movement_range / bfs_path / attack_tiles) 转发到 self.q
(BattleQueries 实例, 见 core.battle.queries).
本文件只管:
  - 摆阵 / 回合流转 (start_round, enter_current, end_unit_turn, post_enemy_turn)
  - 玩家行动公开 API (player_step / enter_attack_aim / confirm_attack_aim / player_use_skill / ...)
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
        self._turn_order: list[BattleUnit] = []
        self._turn_idx = 0
        # 给 UI 的浮动伤害事件队列; UI 自己消费 + 计时
        from core.battle.data import DamageEvent  # 仅为类型, 实例由 combat 模块创建
        self.damage_events: list[DamageEvent] = []
        # 战斗胜利时填; UI 弹完才返回地图
        self.level_ups: list[LevelUpReport] = []
        # 敌方 AI 计算的待执行攻击 (在移动动画结束后才打出)
        self._pending_enemy_attack: BattleUnit | None = None
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
        # 动画引擎: 跑攻击 seq 字节码, 通过 SIGNAL 回调战斗逻辑.
        # UI 每 40ms 调一次 self.engine.tick() 推进所有 entity.
        from core.anim_engine.engine import Engine
        from core.anim_engine.entity import SIG_IMPACT, SIG_END, SIG_IMPACT_2
        self.engine = Engine()
        # 屏幕震动偏移 (px): 玄武地震等由 engine entity 每 tick 写随机抖动, scene.draw 叠加到相机.
        # (0,0) = 不震. 见 core.son_transform earthquake_think (exe FUN_004d8b0c 抖相机原点).
        self.shake_offset: tuple[int, int] = (0, 0)
        # 可见屏幕中心 (世界 px), 由 BattleScene 每帧发布. 满屏特效 (超亂舞滑板) 用它当
        # 框中心, 避免施法者靠地图/相机边缘时特效整体偏到半屏. None = 无 UI (headless 测试).
        self.view_center_world: tuple[int, int] | None = None
        self._SIG_IMPACT = SIG_IMPACT
        self._SIG_IMPACT_2 = SIG_IMPACT_2
        self._SIG_END = SIG_END
        self.engine.on('signal', self._on_anim_signal)
        self._place_units(player_positions, enemy_positions)
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
                # 让 apply_pending_attack 走最终结算分支: 把 count 提到 total 之上, 强制 last
                caster.pending_impact_count = caster.pending_impact_total - 1
                # 临时清 skill_id 让 has_impact_spawn 检查失败 (= 不再 spawn 第 2 个投射物)
                saved_sid = caster.pending_skill_id
                caster.pending_skill_id = None
                combat.apply_pending_attack(self, caster)
                caster.pending_skill_id = saved_sid
                # B 类 cast seq 没 SIG_END, post_attack_anim 不会自动触发 — 这里手动收尾
                self.post_attack_anim(caster)
            return
        unit = source_entity.user_data.get('unit')
        if unit is None:
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
        elif sig == self._SIG_END:
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
        """同一轮里下一个还没走的活单位; 没了就返回下一轮的头一个."""
        for i in range(self._turn_idx + 1, len(self._turn_order)):
            u = self._turn_order[i]
            if u.alive and not u.has_acted:
                return u
        # 下一轮: 按 agile 重排活单位, 取第一个
        nxt = sorted(self.alive_units, key=lambda u: -u.agile)
        for u in nxt:
            if u is not self.current and u.alive:
                return u
        return None

    # ---- 回合 ----
    def _start_round(self) -> None:
        self._turn_order = sorted(self.alive_units, key=lambda u: -u.agile)
        for u in self._turn_order:
            u.has_acted = False
        self._turn_idx = 0
        self._log(f"--- 新回合 ({' > '.join(u.name for u in self._turn_order)}) ---")
        self._enter_current()

    def _enter_current(self) -> None:
        while self._turn_idx < len(self._turn_order):
            u = self._turn_order[self._turn_idx]
            if u.alive:
                if u.is_player:
                    self.phase = Phase.PLAYER_MOVE
                    self._pre_move_pos = (u.x, u.y)
                    self.turn_move_range = self.q.movement_range(u)
                    return
                else:
                    self.phase = Phase.ENEMY_TURN
                    # 进入敌方回合前先算移动范围 (= AI 即将走的可达格集合).
                    # AI take_turn 会立即把 unit.x/y 改到 dest, 所以必须现在算.
                    self.turn_move_range = self.q.movement_range(u)
                    # AI 延后执行: scene 显示移动范围一会儿后调 run_pending_enemy_ai.
                    self._enemy_ai_pending = True
                    return  # 等 UI 调 run_pending_enemy_ai → 再调 post_enemy_turn
            self._turn_idx += 1
        self._start_round()

    def end_unit_turn(self) -> None:
        if self._turn_idx < len(self._turn_order):
            self._turn_order[self._turn_idx].has_acted = True
        self._turn_idx += 1
        self._pre_move_pos = None
        if self._check_end():
            return
        if self._turn_idx >= len(self._turn_order):
            self._start_round()
        else:
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
        if self._pending_enemy_attack is not None and self._pending_enemy_attack.alive:
            combat.begin_attack(self, self.current, self._pending_enemy_attack)
            self._pending_enemy_attack = None
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
        """战斗胜利时分配经验, 触发升级 + 生成升级报告."""
        survivors = [p for p in self.players if p.alive]
        if not survivors or self.exp_gained <= 0:
            return
        per = self.exp_gained // len(survivors)
        for p in survivors:
            levels = per // EXP_PER_LEVEL
            if levels <= 0:
                continue
            hp_inc = sum(self.rng.randint(3, 8) for _ in range(levels))
            mp_inc = sum(self.rng.randint(0, 3) for _ in range(levels))
            atk_inc = sum(self.rng.randint(1, 3) for _ in range(levels))
            def_inc = sum(self.rng.randint(1, 3) for _ in range(levels))
            p.level += levels
            p.max_hp += hp_inc
            p.hp = min(p.max_hp, p.hp + hp_inc)  # 顺手补血
            p.max_mp += mp_inc
            p.mp = min(p.max_mp, p.mp + mp_inc)
            p.attack += atk_inc
            p.defence += def_inc
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
        pattern_fn, _ = get_aim_funcs(u.name)
        return pattern_fn(u, self.map)

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
        _, strike_fn = get_aim_funcs(u.name)
        return {(x, y) for (x, y) in strike_fn(u, cursor) if self.map.in_bounds(x, y)}

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
        rng = self.attack_range(u, skill_id)
        if not rng:
            return False
        self.phase = Phase.PLAYER_AIM
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
        heal = is_heal_skill(self.aim_skill_id)
        dmg_tiles = self.damage_range(self.aim_cursor)
        # heal 技能选友军 (is_player 相同); 攻击技能选敌人.
        targets = []
        for (x, y) in dmg_tiles:
            occ = self.q.occupant(x, y)
            if occ is None or not occ.alive:
                continue
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
        combat.clear_pending_attack(attacker)
        self._pending_damage_range = None
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

    def player_use_skill(self) -> bool:
        """SG 必杀: 对当前攻击范围内全敌 ×2 伤害. 消耗 10 SG (UNSET 不消耗)."""
        u = self.current
        if self.phase != Phase.PLAYER_MOVE or not u.is_player:
            return False
        SG_COST = 10
        if u.sg != UNSET and u.sg < SG_COST:
            self._log(f"{u.name} SG 不足, 无法释放必杀")
            return False
        targets = [e for e in self.alive_units
                   if e.is_player != u.is_player
                   and (e.x, e.y) in self.q.attack_tiles(u, u.x, u.y)]
        if not targets:
            self._log(f"{u.name} 攻击范围内无敌人")
            return False
        if u.sg != UNSET:
            u.sg = max(0, u.sg - SG_COST)
        self._log(f"{u.name} 释放必杀!")
        for t in targets:
            combat.strike_skill(self, u, t)
        if self._check_end():
            return True
        self.end_unit_turn()
        return True

    # ---- 工具 ----
    def _log(self, msg: str) -> None:
        self.messages.append(msg)
        if len(self.messages) > 64:
            self.messages = self.messages[-64:]
