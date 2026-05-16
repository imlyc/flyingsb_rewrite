"""战斗结算: 命中率 / reaction 序列 / 伤害扣血 / 普攻动画启动 / 必杀.

自由函数, 第一参数 battle (TacticsBattle 实例) 当 namespace 用. 把状态机的"结算瞬间"
和外面的回合流/AI 分开, 跟 scenes/battle/ 的 free-function 模式一致.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.battle.data import (
    AGILE_MISS_FACTOR,
    BASE_MISS_RATE,
    BattleUnit,
    DamageEvent,
    MAX_MISS_RATE,
)

if TYPE_CHECKING:
    from core.battle.tactics import TacticsBattle


def miss_chance(attacker: BattleUnit, defender: BattleUnit) -> float:
    diff = defender.agile - attacker.agile
    return max(0.0, min(MAX_MISS_RATE, BASE_MISS_RATE + diff * AGILE_MISS_FACTOR))


def set_reaction(defender: BattleUnit, seq_kind: str, attacker: BattleUnit | None = None) -> None:
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


def apply_damage(battle: "TacticsBattle", attacker: BattleUnit,
                 defender: BattleUnit, dmg: int, label: str) -> None:
    defender.hp = max(0, defender.hp - dmg)
    battle.damage_events.append(DamageEvent(dmg, defender.hp, defender.x, defender.y))
    set_reaction(defender, "hit", attacker)
    battle._log(f"{attacker.name} → {defender.name}: {dmg} {label}命中"
                + (f" ({defender.hp}/{defender.max_hp})" if defender.alive else " [击倒]"))


def strike_skill(battle: "TacticsBattle", attacker: BattleUnit, defender: BattleUnit) -> None:
    # 必杀不能被闪避, 强制重击表现 (技能不走 attack_seq, 立即生效)
    raw = attacker.attack - defender.defence + battle.rng.randint(-5, 5)
    dmg = max(1, raw * 2)
    defender.hp = max(0, defender.hp - dmg)
    battle.damage_events.append(DamageEvent(dmg, defender.hp, defender.x, defender.y))
    set_reaction(defender, "hit", attacker)
    battle._log(f"  {attacker.name} → {defender.name}: {dmg} 必杀伤害"
                + (f" ({defender.hp}/{defender.max_hp})" if defender.alive else " [击倒]"))


# ---- 普攻 (走 anim_engine 字节码) ----
def begin_attack(battle: "TacticsBattle", attacker: BattleUnit, defender: BattleUnit) -> None:
    """启动攻击 seq; anim_engine 跑字节码, SIGNAL -100 时 apply_pending_attack 独立 roll 命中/伤害.
    多段攻击: seq 含多个 SIGNAL -100, 每次独立判定 (= 原版多次 jump -100).
    """
    from core.attack_seq import attack_seq_for
    from core.anim_engine.bytecode import tuple_to_bytecode
    attacker.pending_attack_target = defender
    attacker.pending_attack_skill = False
    attacker.pending_attack_kind = ""
    attacker.pending_attack_dmg = 0
    # 创建/复用 entity, 关联回 BattleUnit (signal handler 用)
    if attacker.entity is None:
        attacker.entity = battle.engine.spawn()
    attacker.entity.x = 0
    attacker.entity.y = 0
    attacker.entity.z = 0
    # 清掉上一次攻击残留的 render snapshot (_move_start_*, _fm_total_ticks 等),
    # 否则新攻击第 1 帧会按旧 snapshot 算 MOVE lerp, 出现瞬移+退回的鬼畜.
    attacker.entity.user_data = {'unit': attacker}
    # tuple seq → bytecode 后挂载. attach_seq 自动跑到第一个阻塞 op.
    seq_bc = tuple_to_bytecode(attack_seq_for(attacker.name, attacker.facing))
    battle.engine.attach_seq(attacker.entity, seq_bc)


def apply_pending_attack(battle: "TacticsBattle", attacker: BattleUnit) -> None:
    """attack_seq 跑到 'impact' 步骤时由 UI 调. 实际扣血 + 触发受击/闪避动画.
    每次 impact 独立 roll (支持多段攻击; 目标死亡后续 impact 自动跳过).
    AoE: 若 battle._pending_damage_range 非 None, 一次性扫伤害范围里所有敌人,
    每个独立 miss roll. 否则走单点 pending_attack_target.
    """
    dmg_tiles = getattr(battle, '_pending_damage_range', None)
    if dmg_tiles:
        for (x, y) in dmg_tiles:
            t = battle.q.occupant(x, y)
            if t is None or not t.alive or t.is_player == attacker.is_player:
                continue
            _roll_damage_one(battle, attacker, t)
        return
    target = attacker.pending_attack_target
    if target is None or not target.alive:
        return
    _roll_damage_one(battle, attacker, target)


def _roll_damage_one(battle: "TacticsBattle", attacker: BattleUnit, target: BattleUnit) -> None:
    """对单个 target roll miss/hit + 损伤 + 反应动画. 抽出来给 AoE 多目标循环用."""
    if battle.rng.random() < miss_chance(attacker, target):
        battle.damage_events.append(DamageEvent(0, target.hp, target.x, target.y, miss=True))
        set_reaction(target, "dodge", attacker)
        battle._log(f"{attacker.name} → {target.name}: MISS (闪避)")
    else:
        raw = attacker.attack - target.defence + battle.rng.randint(-5, 5)
        dmg = max(1, raw)
        apply_damage(battle, attacker, target, dmg, "")


def clear_pending_attack(attacker: BattleUnit) -> None:
    attacker.pending_attack_target = None
    attacker.pending_attack_kind = ""
    attacker.pending_attack_dmg = 0
    # 强制清掉 entity 的 playing flag, 防止后续 tick 还在跑 (即使 seq 没显式 EXIT)
    if attacker.entity is not None:
        attacker.entity.flags &= ~0x20000
        attacker.entity.seq = b''
        attacker.entity.x = 0
        attacker.entity.y = 0
        attacker.entity.z = 0


# 兼容旧 API: 立即结算 (测试 / 必杀沿用)
def strike(battle: "TacticsBattle", attacker: BattleUnit, defender: BattleUnit) -> None:
    if battle.rng.random() < miss_chance(attacker, defender):
        battle.damage_events.append(DamageEvent(0, defender.hp, defender.x, defender.y, miss=True))
        set_reaction(defender, "dodge", attacker)
        battle._log(f"{attacker.name} → {defender.name}: MISS (闪避)")
        return
    raw = attacker.attack - defender.defence + battle.rng.randint(-5, 5)
    dmg = max(1, raw)
    apply_damage(battle, attacker, defender, dmg, "")
