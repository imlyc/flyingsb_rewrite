"""战斗领域数据类型: BattleUnit / BattleMap / DamageEvent / LevelUpReport / Phase + 调参常量.

纯数据 (无逻辑), 让战斗主类 tactics.TacticsBattle 和 combat/ai 模块都能 import 这里.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum, auto

from core.anim_engine.entity import Entity
from core.anim_state import AnimationState


# ---------------- 事件 / 升级 ----------------
@dataclass
class DamageEvent:
    """单次战斗事件, UI 用来弹飘字 (伤害数字 / MISS).
    miss=True 时 damage 无意义, UI 显示 'MISS'.
    """
    damage: int           # 本次伤害 (绿色大字; miss 时忽略). heal=True 时 = 回复量
    remaining_hp: int     # 受击后剩余 HP (蓝色小字; miss 时忽略)
    x: int
    y: int
    miss: bool = False
    heal: bool = False    # True = 回血事件 (生命之火等), 飘字显示 +N 绿色


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
    anim: AnimationState = field(default_factory=AnimationState)
    move_path: list[tuple[int, int]] = field(default_factory=list)   # render 待经过的剩余路径节点 (不含起点; 含终点)
    # AI 移动结束后强制朝向 (= face_toward 设的攻击朝向). UI 走完 move_path 时还原, 防止
    # 移动 lerp 中 "切下一段方向" 把攻击 facing 覆盖成最后一段移动方向.
    post_move_facing: tuple[int, int] | None = None
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
    # 攻击者动画: 由 anim_engine 驱动. entity 持有 seq 状态 (atlas/frame/x/y/ticks),
    # SIGNAL -100 IMPACT 触发 apply_pending_attack, -110 END 触发 post_attack_anim.
    # entity is None = 未在攻击; entity.is_playing() = 攻击中.
    entity: Entity | None = None
    # 待发的攻击 (impact 步骤时才真正应用伤害)
    pending_attack_target: "BattleUnit | None" = None
    pending_attack_kind: str = ""             # "hit" / "dodge"
    pending_attack_dmg: int = 0
    pending_attack_skill: bool = False        # 是否必杀 (旧字段, 留作兼容)
    pending_skill_id: int | None = None       # 技能 ID (普攻 None); IMPACT 时给 hit-effect 看决定 extra fx
    pending_attack_cursor: tuple[int, int] | None = None  # AIM cursor 选中的格 (= 投射物落点 / 伤害中心)
    pending_caster_coord: object | None = None             # 多阶段 B 类技能 coordinator entity (e.g. 破天舞)
                                                            # 非空 → tactics 拦截 caster.entity 的 IMPACT/END,
                                                            # 转发给 coord, 跳过常规结算/post_attack_anim
    # 白虎旋风: 被风吹起的高度 (px, >0 = 离地腾空). 渲染时本体上移 wind_lift, 影子留地面.
    wind_lift: float = 0.0
    # 腾空旋转: 显示 idle atlas06 row4(重击姿) 的列号 = 朝向, 循环 UP→RIGHT→DOWN→LEFT 切帧
    # = 绕自身中轴线转 (原版 seq 0x656ef8 = 帧16/19/17/18). -1 = 不旋转.
    wind_spin_col: int = -1
    # 孙悟空召唤演出: caster 翻跟头隐现 (ps_CSON105). cast_flip_frame 非 None → render 显示
    # 翻跟头第 N 帧 (覆盖普通 sprite); cast_hidden → caster 完全不画 (神兽攻击阶段隐身).
    cast_flip_frame: int | None = None
    cast_hidden: bool = False
    # 翻跟斗前的简短施法姿: ps_CSON102 帧索引 (非 None → render 显示该帧, 方向行×4+col).
    cast_pose_frame: int | None = None
    pending_impact_count: int = 0             # 本次攻击已触发 IMPACT 次数
    pending_impact_total: int = 1             # 本次攻击 seq 里 IMPACT 总数 (= 多段攻击的段数).
                                              # 多段攻击 (e.g. 無限刀 5 hit): 只有最后一次结算伤害,
                                              # 之前的 IMPACT 只放 hit-fx + reaction (视觉反馈)
    # === 原版式双值 HP (working buffer + committed) + 事件(signal)驱动提交 ===
    # 原版: 命中即扣"工作缓冲"(判死亡/AI), 攻击动画结束(受击反应后)才 commit 回真实表(= 显示值),
    # 死亡动画由数字闪烁信号触发. 我们对应:
    #   hp                = 工作缓冲 (apply_damage 即扣; alive/AI/胜负读它)
    #   committed_hp 显示  = 真实表 (受击反应结束 commit_hp 提交 → display_hp; 死亡保留旧值不显 0)
    # shown_hp_override = committed 显示值的滞后表示 (None = 已与 hp 同步; 非 None = 受击前旧值待提交).
    shown_hp_override: int | None = None
    # 死亡/虚弱视觉门控: True = 工作缓冲已死但死亡动画/尸体未放行 (保持站立呼吸). 数字闪烁信号
    # (_on_damage_flash) 或大金刚批量释放. settle_batch: 大金刚等逐个砸 AOE, 不在自己数字信号时
    # 释放, 等全砸完批量统一 (= 最后一个敌人受击结束).
    settle_pending: bool = False
    settle_batch: bool = False
    # 死亡动画计时 (HP=0 + reaction 结束 + 数字进 flash 阶段后开始累计 ms; -1 = 未启动).
    # 时序源 exe FUN_004399c5 / 00439b42 等: 切 ps_*04 row 4 (frames 12/13/14), 每帧 hold 0x14=20 ticks=800ms.
    # 玩家: 走完 fall 永久 hold (尸体, 可复活); 敌人: hold 一段后闪烁消失.
    death_anim_time_ms: int = -1
    # 已学技能 id 列表 (顺序 = 显示顺序 = 习得顺序). 玩家创建时由 setup.py 按
    # core.skills.CHARACTER_SKILL_POOL 初始化, 敌方留空. 后续 level-up 解锁动这个字段.
    known_skills: list[int] = field(default_factory=list)

    @property
    def is_attacking(self) -> bool:
        return self.entity is not None and self.entity.is_playing()

    @property
    def is_weakened(self) -> bool:
        """HP < 40% (= 原版 FUN_004c2492 的 hp*100/max_hp < 0x28 阈值). 死亡不算虚弱."""
        return self.hp > 0 and self.hp * 100 < self.max_hp * 40

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def display_hp(self) -> int:
        """committed HP (= 显示值/真实表). 提交前显示受击前旧值, 提交后 = 工作缓冲 hp."""
        return self.shown_hp_override if self.shown_hp_override is not None else self.hp

    @property
    def display_weakened(self) -> bool:
        """显示用虚弱判定 (基于 committed display_hp, 让虚弱色/姿态跟 HP 一起在提交时变)."""
        h = self.display_hp
        return h > 0 and h * 100 < self.max_hp * 40

    def commit_hp(self) -> None:
        """提交工作缓冲 → committed 显示值 (原版动作结束/受击反应后 commit 回真实表).
        存活 → 显示同步到 hp; 死亡 → 保留旧值 (原版死亡闪烁期不显 0, 保持原值直到消失)."""
        if self.alive:
            self.shown_hp_override = None

    def release_death_visual(self) -> None:
        """放行死亡/虚弱视觉门控 (由数字闪烁信号触发). 之前一直保持站立呼吸."""
        self.settle_pending = False
        self.settle_batch = False

    def snap_render(self) -> None:
        """把渲染坐标瞬间对齐到逻辑位置 (无动画). 摆阵 / 复活时用."""
        self.render_x = float(self.x)
        self.render_y = float(self.y)


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
    PLAYER_AIM = auto()     # 选攻击目标 (cursor 在 facing 格, 红 tile, Enter 确认)
    ENEMY_TURN = auto()     # 敌方 AI (UI 演示后调 post_enemy_turn)
    VICTORY = auto()
    DEFEAT = auto()
