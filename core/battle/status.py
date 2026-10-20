"""战斗异常/增益状态 (exe 角色表状态字, 逆向 2026-10-20).

exe 每个玩家角色记录 (stride 0xbc) 有 3 个状态 dword:
  A @0x689d58: 状态位. bit 8..17 = 十种计时状态 (8..12 异常 5 种, 13 幸運進行曲 0x2000, 14 斗轉星移 0x4000,
               15 返荷杖 0x8000, 16 強力森巴 0x10000, 17 強力防禦 0x20000); 0x200000/0x400000 = 死亡/离场.
  B @0x689d5c: 8 个 nibble 计数器 (nibble i ↔ A bit 8+i); C @0x689d60: nibble 0/1 ↔ A bit 16/17.
施放 (FUN_004a6efe 的 skill switch): 置位 + nibble = N (斗轉/返荷 N=2).
回合递减 (FUN_004a3738, 每**新回合**开始时对全体调一次, 由回合管理器 FUN_004a4f94 state 1 调):
  先清 A bit 8..17; 对每个 nibble>0: nibble-=1 并**重新置位**. 所以 N=2 的状态在施放回合 + 之后 2 个回合有效,
  第 3 次递减时 (nibble 已 0) 才消失.
效果 (伤害结算 FUN_004a6efe): 斗轉 0x4000 → 受到的伤害归零 (仍算命中, 飘 0); 返荷 0x8000 → 本人伤害归零,
  攻击者扣 "攻击者攻击力" (×暴击) (= local_250, 不是伤害的一半); 有返荷时命中判定强制命中.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.battle.data import BattleUnit

ST_DOUZHUAN = 0x4000     # 斗轉星移 (英雄樂章 0x2d 也给同一位)
ST_FANHE = 0x8000        # 返荷杖
TIMED_STATUS_BITS = tuple(1 << b for b in range(8, 18))   # exe 清位掩码 0xfffc00ff 覆盖 bit 8..17


def apply_status(unit: "BattleUnit", bit: int, turns: int) -> None:
    """置位 + 计数 (= exe `A |= bit; nibble = turns`, 覆盖旧计数)."""
    unit.status_bits |= bit
    unit.status_turns[bit] = turns


def has_status(unit: "BattleUnit", bit: int) -> bool:
    return bool(unit.status_bits & bit)


def clear_status(unit: "BattleUnit", bit: int) -> None:
    unit.status_bits &= ~bit
    unit.status_turns.pop(bit, None)


def round_tick(units) -> None:
    """新回合开始: exe FUN_004a3738 语义 (死亡单位跳过)."""
    for u in units:
        if not u.alive:
            continue
        for bit in TIMED_STATUS_BITS:
            u.status_bits &= ~bit
        for bit in TIMED_STATUS_BITS:
            n = u.status_turns.get(bit, 0)
            if n > 0:
                u.status_turns[bit] = n - 1
                u.status_bits |= bit
