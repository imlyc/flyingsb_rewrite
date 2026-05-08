"""战棋回合制战斗 (SLG, 全键盘操作).

设计:
  - BattleMap: 战场网格 + 障碍物
  - BattleUnit: 战场单位 (位置, 属性, 已行动标记)
  - TacticsBattle: 总状态机
      Phase.PLAYER_MOVE → 选移动目标 → Phase.PLAYER_ACT → 选攻击 / 跳过 → 下一个
      取消 (cancel_action) 把刚移动的单位拉回原位, 退回 PLAYER_MOVE
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto

from core.character import UNSET, Character


# ---------------- 事件 / 升级 ----------------
@dataclass
class DamageEvent:
    """单次战斗事件, UI 用来弹飘字 (伤害数字 / MISS).
    miss=True 时 damage 无意义, UI 显示 'MISS'.
    """
    damage: int           # 本次伤害 (绿色大字; miss 时忽略)
    remaining_hp: int     # 受击后剩余 HP (蓝色小字; miss 时忽略)
    x: int
    y: int
    miss: bool = False


@dataclass
class LevelUpReport:
    """战斗胜利后的升级报告 (UI 弹框用)."""
    name: str
    new_level: int
    gained_levels: int
    hp_inc: int
    mp_inc: int
    atk_inc: int
    def_inc: int


# 简易升级规则: 单位本场获得的经验 ÷ EXP_PER_LEVEL = 升级数
EXP_PER_LEVEL = 25

# 闪避判定参数 (重击/轻击区分已废弃: 原版只有一种受击反应, 见 reaction_seq.py)
BASE_MISS_RATE = 0.05            # 同等敏捷时的基础闪避率
AGILE_MISS_FACTOR = 0.005        # 敏捷差每 1 点对闪避率的贡献
MAX_MISS_RATE = 0.30


# ---------------- 单位 ----------------
@dataclass
class BattleUnit:
    name: str
    level: int
    max_hp: int
    hp: int
    max_mp: int
    mp: int
    sg: int                  # UNSET 视为 ∞
    attack: int
    defence: int
    agile: int
    move: int                # 移动范围 (格)
    is_player: bool
    color: tuple[int, int, int] = (200, 80, 80)
    attack_range: int = 1    # Manhattan
    x: int = 0
    y: int = 0
    facing: tuple[int, int] = (0, 1)  # (dx, dy), 默认朝下
    has_acted: bool = False
    exp_reward: int = 0
    money_reward: int = 0
    sprite_key: str | None = None    # 角色 atlas 资源名 (如 'ps_CSON100'); None=用 color 方块
    # 渲染态 (UI 写入, 战斗逻辑不动)
    anim_time_ms: int = 0                                  # 行走帧累计时间, 静止时 0
    idle_time_ms: int = 0                                  # 待机呼吸帧累计时间, 移动时 0
    turn_remaining_ms: int = 0                             # 90° 转向过渡剩余时间
    turn_from_facing: tuple[int, int] | None = None        # 过渡起始朝向
    move_path: list[tuple[int, int]] = field(default_factory=list)   # render 待经过的剩余路径节点 (不含起点; 含终点)
    # 渲染坐标 (浮点 tile 单位); UI 帧间向 x/y 插值, 实现走动动画
    render_x: float = 0.0
    render_y: float = 0.0
    # 受击/闪避动画: 由 reaction_seq.py 的脚本驱动 (UI 计时, 战斗逻辑只指定序列)
    reaction_seq: list | None = None          # 当前序列 (HIT_SEQ[i] 或 DODGE_SEQ[i])
    reaction_step_idx: int = 0
    reaction_step_elapsed_ms: int = 0
    reaction_step_start_off: tuple[float, float] = (0.0, 0.0)
    reaction_offset: tuple[float, float] = (0.0, 0.0)   # 当前像素位移 (dx, dy)
    reaction_frame: int | None = None         # atlas 06 的帧索引 (0-19), None=不画
    reaction_saved_facing: tuple[int, int] | None = None   # 进入受击前的朝向
    # 攻击者动画: 由 attack_seq.py 驱动. 攻击者播 → impact 步骤触发受击者反应 → 序列结束才回合结束
    attack_seq: list | None = None
    attack_step_idx: int = 0
    attack_step_elapsed_ms: int = 0
    attack_step_start_off: tuple[float, float] = (0.0, 0.0)
    attack_offset: tuple[float, float] = (0.0, 0.0)
    attack_fm_atlas: int | None = None        # 0 / 1 等, 选择哪个 fm_ atlas
    attack_fm_frame: int | None = None
    # 待发的攻击 (impact 步骤时才真正应用伤害)
    pending_attack_target: "BattleUnit | None" = None
    pending_attack_kind: str = ""             # "hit" / "dodge"
    pending_attack_dmg: int = 0
    pending_attack_skill: bool = False        # 是否必杀

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def snap_render(self) -> None:
        """把渲染坐标瞬间对齐到逻辑位置 (无动画). 摆阵 / 复活时用."""
        self.render_x = float(self.x)
        self.render_y = float(self.y)


def _try_sprite_key(name: str) -> str | None:
    from core.character_sprites import CHARACTER_SPRITES, sprite_resource
    return sprite_resource(name) if name in CHARACTER_SPRITES else None


def unit_from_character(name: str, ch: Character) -> BattleUnit:
    """把存档里的角色转换成战场单位.

    存档里的 Attack/Defence 含装备加成数值很大 (1142, 358), 直接用会一击秒杀.
    Unknow_5 / Unknow_6 看起来是基础攻防 (17/18 这种合理值), 战棋平衡用这两个.
    """
    base_atk = ch.Unknow_5 if ch.Unknow_5 > 0 else max(10, ch.Power)
    base_def = ch.Unknow_6 if ch.Unknow_6 > 0 else max(5, ch.Wisdom // 2)
    return BattleUnit(
        name=name,
        level=ch.Level,
        max_hp=ch.MaxHP, hp=max(1, ch.CurrentHP),
        max_mp=ch.MaxMP, mp=ch.CurrentMP,
        sg=ch.SG,
        attack=base_atk, defence=base_def, agile=ch.Agile,
        move=max(2, ch.Agile // 25),     # 99/25 ≈ 3, 49/25 ≈ 1 → max(2, .)
        is_player=True,
        color=(120, 200, 230),
        sprite_key=_try_sprite_key(name),
    )


# ---------------- 敌人模板 ----------------
# sprite 字段是 ase_ps 资源名 (不含 ps_ 前缀和扩展名, 例: 'CSKEL00' / 'CSKEL000'); None=保留色块
ENEMY_TEMPLATES: dict[str, dict] = {
    "骷髅":   dict(level=3, max_hp=30, attack=10, defence=5,  agile=8,  move=3, exp_reward=40,  money_reward=15,
                  color=(220, 220, 220), sprite="CSKEL00"),
    "黄色怪": dict(level=5, max_hp=50, attack=15, defence=8,  agile=6,  move=2, exp_reward=80,  money_reward=30,
                  color=(220, 200,  60), sprite="CGHOU00"),
    "乌鸦怪": dict(level=2, max_hp=20, attack=8,  defence=3,  agile=12, move=4, exp_reward=30,  money_reward=10,
                  color=( 80,  60,  90), sprite="CCROW00"),
}


def make_enemy(name: str) -> BattleUnit:
    t = ENEMY_TEMPLATES[name]
    sprite_key = f"ps_{t['sprite']}" if t.get("sprite") else None
    return BattleUnit(
        name=name,
        level=t["level"],
        max_hp=t["max_hp"], hp=t["max_hp"],
        max_mp=0, mp=0, sg=0,
        attack=t["attack"], defence=t["defence"], agile=t["agile"],
        move=t["move"],
        is_player=False,
        color=t["color"],
        exp_reward=t["exp_reward"], money_reward=t["money_reward"],
        sprite_key=sprite_key,
    )


# ---------------- 地图 ----------------
@dataclass
class BattleMap:
    w: int
    h: int
    obstacles: set[tuple[int, int]] = field(default_factory=set)

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def passable(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and (x, y) not in self.obstacles


def default_battle_map(w: int = 15, h: int = 10, rng: random.Random | None = None) -> BattleMap:
    rng = rng or random.Random()
    m = BattleMap(w, h)
    for _ in range(8):
        x = rng.randint(3, w - 4)
        y = rng.randint(1, h - 2)
        m.obstacles.add((x, y))
    return m


# ---------------- 阶段 ----------------
class Phase(Enum):
    PLAYER_MOVE = auto()    # 等玩家选移动目标
    PLAYER_ACT = auto()     # 移动后选攻击 / 跳过
    ENEMY_TURN = auto()     # 敌方 AI (UI 演示后调 post_enemy_turn)
    VICTORY = auto()
    DEFEAT = auto()


# ---------------- 战斗 ----------------
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
        self.damage_events: list[DamageEvent] = []
        # 战斗胜利时填; UI 弹完才返回地图
        self.level_ups: list[LevelUpReport] = []
        # 敌方 AI 计算的待执行攻击 (在移动动画结束后才打出)
        self._pending_enemy_attack: BattleUnit | None = None
        self._place_units(player_positions, enemy_positions)
        self._start_round()

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
                while not self._is_free(p.x, p.y, p):
                    p.y = (p.y + 1) % self.map.h
        if enemy_positions is not None:
            for e, pos in zip(self.enemies, enemy_positions):
                e.x, e.y = pos
        else:
            for i, e in enumerate(self.enemies):
                e.x, e.y = self.map.w - 2, min(self.map.h - 2, 1 + i * 2)
                while not self._is_free(e.x, e.y, e):
                    e.y = (e.y + 1) % self.map.h
        # 摆阵后初始化渲染坐标 (避免开局所有人从 (0,0) 滑出来)
        for u in self.all_units:
            u.snap_render()

    def _is_free(self, x: int, y: int, ignore: BattleUnit) -> bool:
        return self.map.passable(x, y) and self.occupant(x, y, ignore=ignore) is None

    # ---- 查询 ----
    @property
    def all_units(self) -> list[BattleUnit]:
        return self.players + self.enemies

    @property
    def alive_units(self) -> list[BattleUnit]:
        return [u for u in self.all_units if u.alive]

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

    def occupant(self, x: int, y: int, ignore: BattleUnit | None = None) -> BattleUnit | None:
        for u in self.alive_units:
            if u is ignore:
                continue
            if u.x == x and u.y == y:
                return u
        return None

    # ---- 范围 ----
    def movement_range(self, unit: BattleUnit) -> set[tuple[int, int]]:
        start = (unit.x, unit.y)
        dist = {start: 0}
        q = deque([start])
        while q:
            x, y = q.popleft()
            d = dist[(x, y)]
            if d >= unit.move:
                continue
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = x + dx, y + dy
                if (nx, ny) in dist:
                    continue
                if not self.map.passable(nx, ny):
                    continue
                if self.occupant(nx, ny, ignore=unit) is not None:
                    continue
                dist[(nx, ny)] = d + 1
                q.append((nx, ny))
        return set(dist.keys())

    def bfs_path(self, unit: BattleUnit, dst: tuple[int, int]) -> list[tuple[int, int]]:
        """从 unit 当前位置到 dst 的最短路径 (不含起点, 含终点). 不通时返回空."""
        start = (unit.x, unit.y)
        if start == dst:
            return []
        parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        q = deque([start])
        while q:
            cur = q.popleft()
            if cur == dst:
                path: list[tuple[int, int]] = []
                node: tuple[int, int] | None = cur
                while node is not None and parent[node] is not None:
                    path.append(node)
                    node = parent[node]
                path.reverse()
                return path
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nxt = (cur[0] + dx, cur[1] + dy)
                if nxt in parent:
                    continue
                if not self.map.passable(*nxt):
                    continue
                if self.occupant(*nxt, ignore=unit) is not None:
                    continue
                parent[nxt] = cur
                q.append(nxt)
        return []

    def attack_tiles(self, unit: BattleUnit, x: int, y: int) -> set[tuple[int, int]]:
        r = unit.attack_range
        out = set()
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                d = abs(dx) + abs(dy)
                if d == 0 or d > r:
                    continue
                nx, ny = x + dx, y + dy
                if self.map.in_bounds(nx, ny):
                    out.add((nx, ny))
        return out

    def attackable_enemies(self, unit: BattleUnit) -> list[BattleUnit]:
        tiles = self.attack_tiles(unit, unit.x, unit.y)
        return [u for u in self.alive_units
                if u.is_player != unit.is_player and (u.x, u.y) in tiles]

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
                    self.turn_move_range = self.movement_range(u)
                    return
                else:
                    self.phase = Phase.ENEMY_TURN
                    self._ai_take_turn(u)
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
        """UI 在 ENEMY_TURN 走动动画结束后调用: 执行 AI 待发的攻击, 然后下一回合."""
        if self.phase != Phase.ENEMY_TURN:
            return
        if self._pending_enemy_attack is not None and self._pending_enemy_attack.alive:
            self._strike(self.current, self._pending_enemy_attack)
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
        if self.occupant(nx, ny, ignore=u) is not None:
            return False
        u.x, u.y = nx, ny
        return True

    def player_attack_facing(self) -> bool:
        """攻击当前面向格子上的敌人 (Enter 键). 启动 attack_seq, UI 推完才结束回合."""
        u = self.current
        if self.phase != Phase.PLAYER_MOVE or not u.is_player:
            return False
        fx, fy = u.x + u.facing[0], u.y + u.facing[1]
        target = self.occupant(fx, fy)
        if target is None or target.is_player == u.is_player:
            return False
        if (fx, fy) not in self.attack_tiles(u, u.x, u.y):
            return False
        self._begin_attack(u, target)
        return True

    def post_attack_anim(self, attacker: BattleUnit) -> None:
        """UI 在 attack_seq 跑到 'end' 步骤后调: 清攻击状态, 检查胜负, 结束回合."""
        self._clear_pending_attack(attacker)
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
        if (x, y) != (u.x, u.y) and self.occupant(x, y) is not None:
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
                   and (e.x, e.y) in self.attack_tiles(u, u.x, u.y)]
        if not targets:
            self._log(f"{u.name} 攻击范围内无敌人")
            return False
        if u.sg != UNSET:
            u.sg = max(0, u.sg - SG_COST)
        self._log(f"{u.name} 释放必杀!")
        for t in targets:
            self._strike_skill(u, t)
        if self._check_end():
            return True
        self.end_unit_turn()
        return True

    def _miss_chance(self, attacker: BattleUnit, defender: BattleUnit) -> float:
        diff = defender.agile - attacker.agile
        return max(0.0, min(MAX_MISS_RATE, BASE_MISS_RATE + diff * AGILE_MISS_FACTOR))

    def _set_reaction(self, defender: BattleUnit, seq_kind: str, attacker: BattleUnit | None = None) -> None:
        """seq_kind ∈ {'hit','dodge'}. 转面向攻击者, 加载对应的 reaction_seq.py 脚本."""
        from core.reaction_seq import HIT_SEQ, DODGE_SEQ, facing_to_seq_index
        # 保存原朝向 (动画结束 UI 还原); 多次连击不覆盖
        if defender.reaction_saved_facing is None:
            defender.reaction_saved_facing = defender.facing
        # 转面向攻击者
        if attacker is not None:
            dx = attacker.x - defender.x
            dy = attacker.y - defender.y
            if abs(dx) >= abs(dy) and dx != 0:
                defender.facing = (1 if dx > 0 else -1, 0)
            elif dy != 0:
                defender.facing = (0, 1 if dy > 0 else -1)
        idx = facing_to_seq_index(defender.facing)
        defender.reaction_seq = (DODGE_SEQ if seq_kind == "dodge" else HIT_SEQ)[idx]
        defender.reaction_step_idx = 0
        defender.reaction_step_elapsed_ms = 0
        defender.reaction_step_start_off = (0.0, 0.0)
        defender.reaction_offset = (0.0, 0.0)
        defender.reaction_frame = None

    def _apply_damage(self, attacker: BattleUnit, defender: BattleUnit, dmg: int, label: str) -> None:
        defender.hp = max(0, defender.hp - dmg)
        self.damage_events.append(DamageEvent(dmg, defender.hp, defender.x, defender.y))
        self._set_reaction(defender, "hit", attacker)
        self._log(f"{attacker.name} → {defender.name}: {dmg} {label}命中"
                  + (f" ({defender.hp}/{defender.max_hp})" if defender.alive else " [击倒]"))

    def _strike_skill(self, attacker: BattleUnit, defender: BattleUnit) -> None:
        # 必杀不能被闪避, 强制重击表现 (技能不走 attack_seq, 立即生效)
        raw = attacker.attack - defender.defence + self.rng.randint(-5, 5)
        dmg = max(1, raw * 2)
        defender.hp = max(0, defender.hp - dmg)
        self.damage_events.append(DamageEvent(dmg, defender.hp, defender.x, defender.y))
        self._set_reaction(defender, "hit", attacker)
        self._log(f"  {attacker.name} → {defender.name}: {dmg} 必杀伤害"
                  + (f" ({defender.hp}/{defender.max_hp})" if defender.alive else " [击倒]"))

    # ---- 普攻 (走 attack_seq 动画) ----
    def _begin_attack(self, attacker: BattleUnit, defender: BattleUnit) -> None:
        """决定攻击结果, 设置 attack_seq + 待发伤害 (UI 推进序列, impact 时调 _apply_pending_attack)."""
        from core.attack_seq import attack_seq_for
        if self.rng.random() < self._miss_chance(attacker, defender):
            kind, dmg = "dodge", 0
        else:
            raw = attacker.attack - defender.defence + self.rng.randint(-5, 5)
            kind, dmg = "hit", max(1, raw)
        attacker.pending_attack_target = defender
        attacker.pending_attack_kind = kind
        attacker.pending_attack_dmg = dmg
        attacker.pending_attack_skill = False
        attacker.attack_seq = attack_seq_for(attacker.name, attacker.facing)
        attacker.attack_step_idx = 0
        attacker.attack_step_elapsed_ms = 0
        attacker.attack_step_start_off = (0.0, 0.0)
        attacker.attack_offset = (0.0, 0.0)
        attacker.attack_fm_atlas = None
        attacker.attack_fm_frame = None

    def _apply_pending_attack(self, attacker: BattleUnit) -> None:
        """attack_seq 跑到 'impact' 步骤时由 UI 调. 实际扣血 + 触发受击/闪避动画."""
        target = attacker.pending_attack_target
        if target is None or not target.alive:
            return
        if attacker.pending_attack_kind == "dodge":
            self.damage_events.append(DamageEvent(0, target.hp, target.x, target.y, miss=True))
            self._set_reaction(target, "dodge", attacker)
            self._log(f"{attacker.name} → {target.name}: MISS (闪避)")
        else:
            self._apply_damage(attacker, target, attacker.pending_attack_dmg, "")

    def _clear_pending_attack(self, attacker: BattleUnit) -> None:
        attacker.pending_attack_target = None
        attacker.pending_attack_kind = ""
        attacker.pending_attack_dmg = 0
        attacker.attack_seq = None
        attacker.attack_offset = (0.0, 0.0)
        attacker.attack_fm_atlas = None
        attacker.attack_fm_frame = None

    # 兼容旧 API: 立即结算 (测试 / 必杀沿用)
    def _strike(self, attacker: BattleUnit, defender: BattleUnit) -> None:
        if self.rng.random() < self._miss_chance(attacker, defender):
            self.damage_events.append(DamageEvent(0, defender.hp, defender.x, defender.y, miss=True))
            self._set_reaction(defender, "dodge", attacker)
            self._log(f"{attacker.name} → {defender.name}: MISS (闪避)")
            return
        raw = attacker.attack - defender.defence + self.rng.randint(-5, 5)
        dmg = max(1, raw)
        self._apply_damage(attacker, defender, dmg, "")

    # ---- 敌方 AI ----
    def _ai_take_turn(self, unit: BattleUnit) -> None:
        """AI: 选目标 → 走 (逻辑坐标立即改, render 由 UI 插值动画) → 攻击留到 post_enemy_turn."""
        targets = [p for p in self.players if p.alive]
        if not targets:
            return
        target = min(targets, key=lambda p: abs(p.x - unit.x) + abs(p.y - unit.y))

        # 已经能打就不动
        if (target.x, target.y) in self.attack_tiles(unit, unit.x, unit.y):
            self._face_toward(unit, target)
            self._pending_enemy_attack = target
            return

        # 朝目标走一步: 取可达格子里 Manhattan 最近的
        reachable = self.movement_range(unit)
        cands = [(x, y) for (x, y) in reachable
                 if (x, y) == (unit.x, unit.y) or self.occupant(x, y) is None]
        best = min(cands, key=lambda p: abs(p[0] - target.x) + abs(p[1] - target.y))
        if best != (unit.x, unit.y):
            self._log(f"{unit.name} 移动到 {best}")
            # 计算真实路径让 render 沿格逐步走 (避免两轴并行 lerp 出 45° 飞行)
            path = self.bfs_path(unit, best)
            unit.move_path = list(path)
            # 朝向 = 第一段方向
            if path:
                step0 = path[0]
                ddx = step0[0] - unit.x
                ddy = step0[1] - unit.y
                if abs(ddx) >= abs(ddy) and ddx != 0:
                    unit.facing = (1 if ddx > 0 else -1, 0)
                elif ddy != 0:
                    unit.facing = (0, 1 if ddy > 0 else -1)
            unit.x, unit.y = best
        # 走到了能攻击的位置就计划攻击, 但留到 post_enemy_turn 才打
        if target.alive and (target.x, target.y) in self.attack_tiles(unit, unit.x, unit.y):
            self._face_toward(unit, target)
            self._pending_enemy_attack = target

    def _face_toward(self, unit: BattleUnit, target: BattleUnit) -> None:
        """让 unit 朝向 target 所在格 (用于攻击前)."""
        dx = target.x - unit.x
        dy = target.y - unit.y
        if abs(dx) >= abs(dy):
            unit.facing = (1 if dx > 0 else -1 if dx < 0 else unit.facing[0], 0)
        else:
            unit.facing = (0, 1 if dy > 0 else -1)

    # ---- 工具 ----
    def _log(self, msg: str) -> None:
        self.messages.append(msg)
        if len(self.messages) > 64:
            self.messages = self.messages[-64:]
