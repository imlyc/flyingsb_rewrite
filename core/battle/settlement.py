"""战后结算 — exe FUN_004a5c63 (奖励) / FUN_004a5f60 (经验分配) / FUN_004a5e0b (加经验升级) / FUN_004a611c·4a62a2 (收尾),
2026-10-26 逆向 (reverse_engineering/enemy_field_users.txt, exp_distribution.txt, formation_init.txt).

- 奖励: 经验 / 金钱 = 全部敌人之和 × 145 / 100; 每只敌人 rand%1000 < 掉落千分比 → 掉落物 (+0x68).
- 经验分配: 有"经验集中"目标 (乐神杰特 0x29, exe DAT_007d9900) 且其未倒 → 全给他; 否则按活着的队员平分 (整除).
  装备 黄金苹果 0xe1 → 所得 ×2. 加经验 = core.character_data.add_exp (累计经验, 一场最多升一级).
- 收尾: 工作 HP 写回角色表 (封顶 MaxHP); 倒下 (HP<1) 的队员 → 1 HP; 行动值 >19 → 15 (core.battle.energy.write_back).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.battle.data import LevelUpReport

if TYPE_CHECKING:
    from core.battle.tactics import TacticsBattle

REWARD_PCT = 145
GOLDEN_APPLE = 0xE1


def rewards(battle: "TacticsBattle") -> None:
    """FUN_004a5c63: 算 exp_gained / money_gained / drops (掉落物 [(道具, 个数)])."""
    battle.exp_gained = sum(max(0, e.exp_reward) for e in battle.enemies) * REWARD_PCT // 100
    battle.money_gained = sum(max(0, e.money_reward) for e in battle.enemies) * REWARD_PCT // 100
    drops: dict[int, int] = {}
    for e in battle.enemies:
        if e.drop_item >= 0 and battle.rng.randrange(1000) < e.drop_rate:
            drops[e.drop_item] = drops.get(e.drop_item, 0) + 1
    battle.drops = sorted(drops.items())


def distribute_exp(battle: "TacticsBattle") -> None:
    """FUN_004a5f60 + FUN_004a5e0b: 分经验 → 升级 (作用在存档角色 save_ref 上, 再同步战斗单位用于升级框)."""
    from core import character_data
    total = battle.exp_gained
    recv = getattr(battle, 'exp_receiver', None)
    if recv is not None and recv.alive:
        shares = {id(recv): (recv, total)}
    else:
        alive = [p for p in battle.players if p.alive]
        per = total // len(alive) if alive else 0
        shares = {id(p): (p, per) for p in alive}
    for p, amt in shares.values():
        if GOLDEN_APPLE in getattr(p, 'equipment', ()):
            amt *= 2
        ch = getattr(p, 'save_ref', None)
        if ch is None or amt <= 0:
            continue
        before = (ch.MaxHP, ch.MaxMP, ch.Attack, ch.Defence)
        gained = character_data.add_exp(ch, p.name, amt)
        if not gained:
            continue
        hp_inc, mp_inc = ch.MaxHP - before[0], ch.MaxMP - before[1]
        atk_inc, def_inc = ch.Attack - before[2], ch.Defence - before[3]
        p.level = ch.Level
        p.max_hp += hp_inc
        p.max_mp += mp_inc
        p.attack += atk_inc
        p.defence += def_inc
        p.hp, p.mp = p.max_hp, p.max_mp                  # 原版升级回满 (FUN_004ac12e)
        learned = character_data.learned_skills(p.name, p.level)
        if learned:
            p.known_skills = learned
        battle.level_ups.append(LevelUpReport(name=p.name, new_level=p.level, gained_levels=1,
                                              hp_inc=hp_inc, mp_inc=mp_inc, atk_inc=atk_inc, def_inc=def_inc))


def write_back(battle: "TacticsBattle", save=None) -> None:
    """战斗结束: HP (倒下 → 1, 封顶上限) / MP / SG / 行动值 写回存档角色; 胜利时金钱 / 掉落物进存档."""
    from core.battle import energy
    from core.battle.data import Phase
    for u in battle.players:
        ch = getattr(u, 'save_ref', None)
        if ch is None:
            continue
        bonus = max(0, u.max_hp - ch.MaxHP)               # 装备 HP 加成 (setup 加在 max_hp/hp 上)
        ch.CurrentHP = max(1, min(ch.MaxHP, u.hp - bonus))
    energy.write_back(battle)
    if save is not None and battle.phase == Phase.VICTORY and not battle.arena_mode:
        save.money = getattr(save, 'money', 0) + battle.money_gained
        inv = getattr(save, 'inventory', None)
        if inv is not None:
            for iid, n in getattr(battle, 'drops', []):
                inv.add(iid, n)
