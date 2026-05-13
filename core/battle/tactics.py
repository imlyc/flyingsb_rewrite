"""TacticsBattle — 战斗主状态机. 持有 players / enemies / map / phase / turn_order.

实际结算 (伤害/反应/必杀) 转发到 core.battle.combat, AI 走位转发到 core.battle.ai,
空间查询 (occupant / movement_range / bfs_path / attack_tiles) 转发到 self.q
(BattleQueries 实例, 见 core.battle.queries).
本文件只管:
  - 摆阵 / 回合流转 (start_round, enter_current, end_unit_turn, post_enemy_turn)
  - 玩家行动公开 API (player_step / player_attack_facing / player_use_skill / ...)
  - anim_engine glue (engine.on signal → 派发)
  - 胜负检测 + 升级分配
"""

from __future__ import annotations

import random

from core.anim_engine.entity import Entity
from core.character import UNSET
from core.battle import ai, combat
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
    ) -> None:
        self.rng = rng or random.Random()
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
        # 攻击 SIGNAL -110 END 触发后, 等所有动画跑完才切回合 (= advance_turn_when_ready 触发)
        self._pending_turn_end: bool = False
        # 动画引擎: 跑攻击 seq 字节码, 通过 SIGNAL 回调战斗逻辑.
        # UI 每 40ms 调一次 self.engine.tick() 推进所有 entity.
        from core.anim_engine.engine import Engine
        from core.anim_engine.entity import SIG_IMPACT, SIG_END
        self.engine = Engine()
        self._SIG_IMPACT = SIG_IMPACT
        self._SIG_END = SIG_END
        self.engine.on('signal', self._on_anim_signal)
        self._place_units(player_positions, enemy_positions)
        self._start_round()

    def _on_anim_signal(self, source_entity: Entity, sig: int) -> None:
        """anim_engine SIGNAL 路由: -100 IMPACT → 结算伤害, -110 END → 结束攻击回合."""
        unit = source_entity.user_data.get('unit')
        if unit is None:
            return
        if sig == self._SIG_IMPACT:
            combat.apply_pending_attack(self, unit)
        elif sig == self._SIG_END:
            self.post_attack_anim(unit)

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
                    ai.take_turn(self, u)
                    if self._check_end():
                        return
                    return  # 等 UI 调 post_enemy_turn
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

    def player_attack_facing(self) -> bool:
        """攻击当前面向格子上的敌人 (Enter 键). 启动 attack_seq, UI 推完才结束回合."""
        u = self.current
        if self.phase != Phase.PLAYER_MOVE or not u.is_player:
            return False
        fx, fy = u.x + u.facing[0], u.y + u.facing[1]
        target = self.q.occupant(fx, fy)
        if target is None or target.is_player == u.is_player:
            return False
        if (fx, fy) not in self.q.attack_tiles(u, u.x, u.y):
            return False
        combat.begin_attack(self, u, target)
        return True

    def post_attack_anim(self, attacker: BattleUnit) -> None:
        """UI 在 attack_seq END 时调: 清攻击状态. *不立即* 切回合 — 标记 pending,
        scene 等所有动画 (伤害数字 + 死亡动画) 跑完才调 advance_turn_when_ready()."""
        combat.clear_pending_attack(attacker)
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
