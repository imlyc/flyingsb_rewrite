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
    mp: bool = False      # True = MP 变化 (化精/吸精/化精為氣), damage = 变化量, remaining_hp = 之后的 MP


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
    # ---- 公式用属性 (exe 角色表 / 敌人表, 2026-10-25 字段确认; 见 tools/extract_enemies.py) ----
    luck: int = 0                    # 幸运: 玩家 +0x58 / 敌 +0x34 — 命中/闪避/暴击
    magic_atk: int = 0               # 法攻: 敌 +0x0c (玩家无)
    evade: int = 0                   # 闪避: 敌 +0x28 (玩家命中率 - 此值; 玩家无)
    speed: int = 0                   # 行动值增量: 玩家 +0x5c (存档 Unknow_9) / 敌 +0x38
    action_value: int = 0            # 行动值 (玩家角色表 +0x1c = 存档 Unknow_1, 跨战斗保留; 敌实例 +0x20) — exe ATB
    is_countering: bool = False      # 正在演反击 (不再触发反击; tactics._start_counter)
    pending_enemy_move: int | None = None   # 敌人本次行动用的招式 (敌招表下标; formulas.enemy_attack)
    enemy_type: int = -1             # 敌人表下标 (那印 9/10 等特判); 玩家 -1
    unit_class: int = 0              # 反击概率表行: 玩家 exe 0x641820[角色] / 敌 +0x08
    move_weights: list = field(default_factory=list)   # 敌出招权重 (+0x50..), 与 enemy_moves 对应
    wisdom: int = 0                  # 智力 (角色表 +0x48; 战斗中道具回复量用, core.battle.energy)
    equipment: tuple = ()            # 装备着的道具 id (exe FUN_0049cc2d 查 5 槽; 脱皮盾/血盾/丝巾 等影响 MP/SG)
    save_ref: object = None          # 存档 Character (战斗结束 MP/SG 写回, energy.write_back)
    type_flags: int = 0              # 原版敌人表 +0x00 flags (摆阵 FUN_0049ff07 拷进实例表 0x86ada8); 0x10000000 = 不触发地雷
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
    # 孙悟空召唤演出: cast_hidden → caster 完全不画 (神兽攻击阶段隐身).
    # (翻跟头本身走 attach_seq @0x670dc4 + units.py mode2 渲染 ps_XXX105, 无专用字段.)
    cast_hidden: bool = False
    # 翻跟斗前的简短施法姿: ps_CSON102 帧索引 (非 None → render 显示该帧, 方向行×4+col).
    cast_pose_frame: int | None = None
    # 施法姿 (破天舞): 非 None = ps_ atlas 资源名 (如 'ps_CDIT102'), render 循环其**前两列**
    # (col 0↔1, 朝 facing) = 蒙面人披风下施法手势 (看着静止其实有细微动作). exe mode2 ps_ 路径.
    cast_anim_key: str | None = None
    # True → 本次攻击命中不放受击特效 (ef010 红刺 / et00 斩击). 破天舞: 视觉只有天字斩开+爆炸.
    suppress_hit_fx: bool = False
    # 普攻音效 (本次攻击): 挥砍/斩击音(seq jump -1001 时播) + 命中音(jump -1000 设 swing, IMPACT 播).
    # exe 玩家攻击 wrapper 按 char_id 配; 见 combat.PLAYER_ATTACK_SOUNDS. -1 = 无.
    pending_draw_sound: int = -1
    pending_swing_sound: int = -1
    pending_draw_signal: int = -1000   # 起手音触发的 seq 信号 (cid<8 组=-1000, cid>=8 组=-1001)
    pending_impact_count: int = 0             # 本次攻击已触发 IMPACT 次数
    pending_impact_total: int = 1             # 本次攻击 seq 里 IMPACT 总数 (= 多段攻击的段数).
    pending_impact2: bool = False             # B 类技能: 投射物落地 (SIG_IMPACT_2) 的结算中 (不再 spawn)
    # 施法姿保持: exe 技能 dispatcher case 10 清 unit flag 0x10000 (= 不走待机动画) 再挂 cast seq, seq EXIT 后
    # 单位**停在最后一帧** (如紫河举手) 直到 END (-110) 或 dispatcher 收尾才 |= 0x10000. 我们: seq 播完仍渲染
    # entity 当前帧, clear_pending_attack 时解除.
    cast_hold: bool = False
    # 结算 (-200) 时不重放受击动作: 有些技能 exe 的 -200 只飘数字 (受击动作已在 -250 放过), 见 core.jah_skills
    suppress_hit_reaction: bool = False
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
    # 普攻 (core.normal_attack): +0x74 / +0x78 普攻表 idx (None = 非玩家/未接), 本次出招用的 idx
    attack_normal: int | None = None
    attack_melee: int | None = None
    attack_cur: int | None = None
    zihe: dict | None = None         # 紫河变身状态 (core.normal_attack.zihe_setup)
    ra_coord: object | None = None   # 远程普攻协调实体 (core.ranged_attack)
    flicker: dict | None = None      # 变身闪烁 {t, other, to} (渲染按 FLICKER_MASK 选 sprite)
    # 状态 (exe 角色表状态字 A @0x689d58 的 bit + nibble 计数; 见 core.battle.status)
    status_bits: int = 0
    status_turns: dict[int, int] = field(default_factory=dict)
    # 原版敌人表 skill0..3 = **敌方招式表** (assets/enemy_actions.json, 248 项) 的下标, 不是玩家技能 id;
    # 第 0 项多为普攻 (音效由 core.battle.exe_sounds.ENEMY_MOVE_SOUNDS 给)
    enemy_moves: list[int] = field(default_factory=list)

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
