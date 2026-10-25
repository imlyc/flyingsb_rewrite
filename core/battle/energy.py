"""主角能量: MP / SG (兴奋值) — 2026-10-25 按 exe 逆向 (reverse_engineering/mp_sg_funcs.txt, fn_4a6efe.txt).

角色表 +0x7c = 能量类型 (exe 初始表): 1 = MP (孙悟空/美娜/乐神杰特/紫河), 2 = SG (三藏/八戒/蒙面人/破无/捕山),
3 = SG 两格 (沙悟净), 0 = 无 (紫河兽形卡 13-15, MP 0 不能施法). MP 型的 SG 恒为 -1, SG 型的 MaxMP 恒为 0.

**MP**: 放技能扣技能表 [4] (FUN_004a6efe act==2); 装备 脱皮盾 0xfa → 扣 2 倍, 0xfb → 扣一半 (C 整除).
  技能菜单可用判定 (FUN_0042878a): MP >= (消耗 × 0x10000/0x20000/0x8000) >> 16, 与扣法同值.
**SG** (0..16, 上限 0x10): 放技能扣技能表 [5], 不足扣到 0. 技能菜单按**列表位置**判门槛 2/5/8/12/16
  (沙悟净 6/16) = 状态栏 5 格 (沙悟净 2 格), 各技能表 SG 消耗与门槛一致.
  涨: 每回合开始 (FUN_004a4108) 活着且无 睡眠/痲痺/倒地 → +1, 再各 +1 若装备 火大的丝巾 0x145 / 血盾 0xf4;
  被敌人**命中** (普攻/招式/固定伤害招 0xb7-0xb9/反击, 闪避不算) → +1. 自己攻击不涨.
  兴奋剂 0x13a → 直接 16.
**战斗中道具** (FUN_004a6efe act==3): 量 = (威力 × (rng%20+90)/100 + 使用者智力 × 威力/100) × 衰减/8 (8 = 满),
  封顶上限; 目标倒地无效. 威力 = 道具表 +0x6954f4 (恢复药 50 / 良药 300 / 药草 50 / MP 良药 200 / 优药·仙桃·天桃·白粉 10000).
  天桃 0x132 / 强力针灸 0x134 对倒地者 → 复活 HP = MaxHP/5. 战斗外用法见 core.items.field_use (固定量).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.battle.data import BattleUnit

ENERGY_NONE, ENERGY_MP, ENERGY_SG, ENERGY_SG2 = 0, 1, 2, 3
ENERGY_TYPE = {'孙悟空': ENERGY_MP, '美娜': ENERGY_MP, '乐神杰特': ENERGY_MP, '紫河': ENERGY_MP,
               '三藏法师': ENERGY_SG, '猪八戒': ENERGY_SG, '蒙面人': ENERGY_SG, '破无': ENERGY_SG, '捕山': ENERGY_SG,
               '沙悟净': ENERGY_SG2}
SG_MAX = 16
SG_THRESHOLDS = {ENERGY_SG: (2, 5, 8, 12, 16), ENERGY_SG2: (6, 16)}     # 菜单门槛 = 状态栏格子
# 状态栏 SG 槽宽 (px, 每格 16): exe 0x54ca40 (5 格) / 0x54ca84 (沙悟净 2 格), 下标 = SG
SG_GAUGE_PX = {ENERGY_SG: (0, 8, 16, 22, 27, 32, 38, 43, 48, 52, 56, 60, 64, 68, 72, 76, 80),
               ENERGY_SG2: (0, 3, 6, 9, 12, 14, 16, 18, 20, 22, 24, 26, 28, 29, 30, 31, 32)}
SG_ROUND_BONUS_ITEMS = (0x145, 0xf4)     # 火大的丝巾 / 血盾: 每回合额外 +1
MP_COST_DOUBLE, MP_COST_HALF = 0xfa, 0xfb   # 脱皮盾
ITEM_SG_FULL = 0x13a                     # 兴奋剂
NO_SG_STATUS = (0x200, 0x800)            # 睡眠 / 痲痺 (倒地 = not alive)
HP_ITEMS = (0x12b, 0x12c, 0x12d, 0x131, 0x132, 0x133)
MP_ITEMS = (0x12e, 0x12f, 0x130, 0x131, 0x132, 0x133)
REVIVE_ITEMS = (0x132, 0x134)


def energy_type(u: "BattleUnit") -> int:
    z = getattr(u, 'zihe', None)
    if z is not None and z.get('transformed'):
        return ENERGY_NONE                    # 兽形卡 13-15: 类型 0
    return ENERGY_TYPE.get(u.name, ENERGY_NONE)


def uses_sg(u: "BattleUnit") -> bool:
    return energy_type(u) in (ENERGY_SG, ENERGY_SG2) and 0 <= u.sg <= 0x7fffffff


def _equipped(u: "BattleUnit", item: int) -> bool:
    return item in getattr(u, 'equipment', ())


def mp_cost(u: "BattleUnit", skill_id: int) -> int:
    from core.skill_table import skill_mp_cost
    c = skill_mp_cost(skill_id)
    if _equipped(u, MP_COST_DOUBLE):
        return c * 2
    if _equipped(u, MP_COST_HALF):
        return c // 2
    return c


def sg_threshold(u: "BattleUnit", skill_id: int) -> int:
    """菜单门槛: 按技能在已学列表里的位置 (exe 写死 2/5/8/12/16, 沙悟净 6/16)."""
    th = SG_THRESHOLDS.get(energy_type(u))
    skills = list(getattr(u, 'known_skills', []) or [])
    if th is None or skill_id not in skills:
        from core.skill_table import skill_sg_cost
        return skill_sg_cost(skill_id)
    i = skills.index(skill_id)
    return th[i] if i < len(th) else 9999


def can_cast(u: "BattleUnit", skill_id: int) -> bool:
    if u.name not in ENERGY_TYPE:
        return True                           # 非主角 (测试假人 / 敌人): 不受 MP/SG 限制
    t = energy_type(u)
    if t == ENERGY_MP:
        return u.max_mp > 0 and u.mp >= mp_cost(u, skill_id)
    if t in (ENERGY_SG, ENERGY_SG2):
        return uses_sg(u) and u.sg >= sg_threshold(u, skill_id)
    return False


def pay(u: "BattleUnit", skill_id: int) -> None:
    """FUN_004a6efe act==2: 扣 MP (MP 型) / SG (SG 型, 不低于 0)."""
    t = energy_type(u)
    if t == ENERGY_MP:
        u.mp -= mp_cost(u, skill_id)
    elif t in (ENERGY_SG, ENERGY_SG2) and uses_sg(u):
        from core.skill_table import skill_sg_cost
        u.sg = max(0, u.sg - skill_sg_cost(skill_id))


def sg_gain(u: "BattleUnit", n: int = 1) -> None:
    for _ in range(n):
        if uses_sg(u) and u.sg < SG_MAX:
            u.sg += 1


def round_start(battle) -> None:
    """FUN_004a4108 (新回合, 状态递减之后): 我方 SG 自然增长."""
    from core.battle.status import has_status
    for u in battle.players:
        if not u.alive or any(has_status(u, b) for b in NO_SG_STATUS):
            continue
        sg_gain(u)
        for it in SG_ROUND_BONUS_ITEMS:
            if _equipped(u, it):
                sg_gain(u)


def on_hit(attacker: "BattleUnit", defender: "BattleUnit") -> None:
    """被敌人命中 → SG +1 (FUN_004a6efe 敌普攻/招式命中、固定伤害招、反击 三处)."""
    if defender.is_player and not attacker.is_player:
        sg_gain(defender)


def battle_item(battle, user: "BattleUnit", target: "BattleUnit", item_id: int, falloff: int = 8) -> dict:
    """FUN_004a6efe act==3: 返回 {'hp': 回复量, 'mp': 回复量, 'sg': 增量, 'revived': bool}; 空 dict = 无效果."""
    from core.items import item_power
    out: dict = {}
    if item_id in REVIVE_ITEMS and not target.alive:
        target.hp = target.max_hp // 5
        out['revived'] = True
        out['hp'] = target.hp
        return out
    if not target.alive:
        return out
    power = item_power(item_id)
    wis = getattr(user, 'wisdom', 0)

    def amount() -> int:
        v = (power * (battle.rng.randrange(20) + 90) // 100 + wis * power // 100) * falloff
        return int(v / 8) if v < 0 else v >> 3

    if item_id in HP_ITEMS:
        a = min(amount(), target.max_hp - target.hp)
        target.hp += a
        out['hp'] = a
    if item_id in MP_ITEMS:
        a = max(0, min(amount(), target.max_mp - target.mp))
        target.mp += a
        out['mp'] = a
    if item_id == ITEM_SG_FULL and uses_sg(target):
        out['sg'] = SG_MAX - target.sg
        target.sg = SG_MAX
    return out


def write_back(battle) -> None:
    """战斗结束: MP / SG 写回存档角色 (原版 MP/SG 就在角色表上, 跨战斗保留)."""
    for u in battle.players:
        ch = getattr(u, 'save_ref', None)
        if ch is None:
            continue
        mp, max_mp = u.mp, u.max_mp
        z = getattr(u, 'zihe', None)
        if z is not None and z.get('transformed') and z.get('human'):
            mp, max_mp = z['human']['mp'], z['human']['max_mp']    # 兽形卡 MP 0, 人形 MP 另存
        bonus = max(0, max_mp - ch.MaxMP)                          # 装备 MP 加成 (setup 加在 max_mp/mp 上)
        ch.CurrentMP = max(0, min(ch.MaxMP, mp - bonus))
        if uses_sg(u):
            ch.SG = u.sg
