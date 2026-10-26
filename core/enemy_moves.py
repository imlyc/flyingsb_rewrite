"""敌方招式 (exe 招式表 0x692F54, 数据 core/enemy_move_data.py 由 tools/extract_enemy_moves.py 生成), 2026-10-26.

flags & 3 = 目标: 0 / 2 打我方, 1 对己方 (回复等, AI 优先). (flags >> 24) & 0xf = 结算类别 (FUN_004a6efe 敌方分支):
  0 伤害 (core.battle.formulas.enemy_attack)
  1 加异常: 对每种异常位 k (flags & 0x100<<k, 目标未中): 成功率 = 威力 + (敌智 - 我智)/2 + (威力 + 敌幸运 - 我幸运) + 相性,
    clamp 10..90 → FUN_004a6c6b (毒 4 / 睡 3 / 沉默 3 / 痲痺 2 / 咀咒 3 回合)
  2 回复己方: (威力 × 敌 MaxHP × (rand%20+90) / 10000 + 敌智 × 威力 / 100) × 衰减/8, 封顶 MaxHP
  3 召唤 (未做)
  4 固定伤害自爆: 敌种 0xb7/0xb8/0xb9 → 44 / 444 / 666, 自己倒下
演出: kind 'doit' = DOIT_melee (seq 表 + 命中特效, 同玩家普攻); 'tmpl' / 'custom' 演出另做 (现回落通用攻击动作).
AI (FUN_004b1286 / 4af4bf): 候选 = 扣 MP ≤ 当前 MP 的招式; 先排第一个带 flags&1 的, 其余按权重无放回抽签定顺序,
  依次找能用的站位/目标; 沉默只能用物理招. 站位打分 (FUN_004aece7) 现用"罩住最多目标"近似.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from core.enemy_move_data import MOVES, SEQ_TABLES

if TYPE_CHECKING:
    from core.battle.data import BattleUnit

FX_STYLE = {'starburst': 'STARBURST', 'claw': 'CLAW', 'oval': 'OVAL', 'dir4': 'LANCE', 'spark2': 'STARBURST2'}
CAT_DAMAGE, CAT_STATUS, CAT_HEAL, CAT_SUMMON, CAT_FIXED = 0, 1, 2, 3, 4
SELF_DESTRUCT_DMG = {0xb7: 44, 0xb8: 444, 0xb9: 666}


class EnemyMove(NamedTuple):
    idx: int
    name: str
    power: int
    flags: int
    mp_cost: int
    p4: int
    template: int
    fn: int
    kind: str
    called: str | None
    arg: int | None
    fx: str | None

    @property
    def category(self) -> int:
        return (self.flags >> 24) & 0xf

    @property
    def target_type(self) -> int:
        return self.flags & 3

    @property
    def physical(self) -> bool:
        return bool(self.flags & 0x800000)


def move(idx: int) -> EnemyMove | None:
    if idx is None or not 0 <= idx < len(MOVES):
        return None
    return EnemyMove(idx, *MOVES[idx])


def seq_for(idx: int, facing: tuple[int, int]) -> list[tuple] | None:
    """DOIT 招式的施法者 seq (exe 原字节, 槽号是全局 fm 图集); 非 DOIT → None."""
    from core.attack_seq import facing_to_atk_index
    m = move(idx)
    if m is None or not m.kind.startswith('doit') or m.arg not in SEQ_TABLES:
        return None
    return SEQ_TABLES[m.arg][facing_to_atk_index(facing)]


def hit_style(idx: int) -> str | None:
    m = move(idx)
    return FX_STYLE.get(m.fx) if m and m.fx else None


# ---------------- AI 选招顺序 (FUN_004af4bf + FUN_004b1286) ----------------
def move_order(battle, unit: "BattleUnit") -> list[int]:
    """返回本回合尝试的招式 id 顺序."""
    from core.battle.status import has_status
    weights = list(getattr(unit, 'move_weights', []) or [])
    cands = []
    for slot, mid in enumerate(unit.enemy_moves):
        m = move(mid)
        if m is None or m.mp_cost > unit.mp:
            continue
        cands.append((slot, mid, max(0, weights[slot]) if slot < len(weights) else 0))
    if has_status(unit, 0x400):                          # 沉默: 只能物理招
        cands = [c for c in cands if move(c[1]).physical]
    order: list[int] = []
    pri = next((c for c in cands if move(c[1]).flags & 1), None)
    rest = list(cands)
    if pri is not None:
        order.append(pri[1])
        rest.remove(pri)
    while rest:
        total = sum(w for _, _, w in rest)
        if total <= 0:
            order += [mid for _, mid, _ in rest]
            break
        r = battle.rng.randrange(total)
        acc = 0
        for c in rest:
            acc += c[2]
            if r < acc:
                order.append(c[1])
                rest.remove(c)
                break
    return order


# ---------------- 非伤害类结算 ----------------
def status_chance(att: "BattleUnit", dfn: "BattleUnit", m: EnemyMove) -> int:
    from core.battle.formulas import affinity
    c = m.power + (att.wisdom - dfn.wisdom) // 2 + (m.power + att.luck - dfn.luck) + affinity(att, dfn)
    return max(10, min(90, c))


def resolve_status(battle, att: "BattleUnit", dfn: "BattleUnit", m: EnemyMove) -> list[int]:
    """类别 1: 对每种异常位各掷一次 (rand%101 < 成功率), 已中的不再加."""
    from core.battle.status import apply_status, has_status
    from core.normal_attack import STATUS_ROUNDS
    got = []
    chance = status_chance(att, dfn, m)
    for k in range(5):
        bit = 0x100 << k
        if m.flags & bit and not has_status(dfn, bit) and battle.rng.randrange(101) < chance:
            apply_status(dfn, bit, STATUS_ROUNDS[bit])
            got.append(bit)
    return got


def heal_amount(battle, att: "BattleUnit", m: EnemyMove, falloff: int = 8) -> int:
    from core.battle.formulas import _div
    amt = _div(m.power * att.max_hp * (battle.rng.randrange(20) + 90), 10000) + _div(att.wisdom * m.power, 100)
    return max(0, _div(amt * falloff, 8))
