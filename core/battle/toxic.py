"""中毒演出 BTLdoToxic (exe FUN_004cb5da → 实体 FUN_004cb42b), 2026-10-26 (reverse_engineering/toxic_decomp.txt).

exe FUN_004a4f94 case 1: 轮到的单位中毒 (0x100) → 伤害 = FUN_004a4018 (当前 HP / 4), 立即扣 HP (FUN_004a4dbe), 起 BTLdoToxic,
状态机进 case 3 等它结束 (FUN_004cb62d) 才刷新状态栏 (FUN_004a4e42(1)) 并开始行动. 实体:
  state 0   age == 10 → 10
  state 10  单位挂受击 seq 6557f0[单位朝向] (不转向) + 飘字 (FUN_004d05d8(单位, 伤害)), 计数 = 1 → 0x14
  -20       飘字完: 单位回待机, 计数 = 0
  state 0x14 计数 0 → 记 age + 16 → 0x1e
  state 0x1e age 到 → 自毁 (DAT_008698dc = 0).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.anim_engine.engine import Engine
    from core.anim_engine.entity import Entity

START_AGE = 10
TAIL_TICKS = 16


def _think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'toxic' not in ud:
        return
    battle, u = ud['battle'], ud['unit_t']
    age = ud['age']
    st = ud['state']
    if st == 0:
        if age == START_AGE:
            ud['state'] = 10
            st = 10
    if st == 10:
        from core.battle import combat
        from core.battle.data import DamageEvent
        combat.set_reaction(u, "hit", None)
        combat.push_damage_event(battle, u, DamageEvent(ud['dmg'], u.hp, u.x, u.y))
        ud['state'] = 0x14
    elif st == 0x14:
        if getattr(battle, 'float_pending', 0) <= 0 and u.reaction_seq is None:
            ud['end'] = age + TAIL_TICKS
            ud['state'] = 0x1e
    elif st == 0x1e:
        if age >= ud['end']:
            battle.toxic_active = False
            battle.refresh_status_snapshot()             # exe case 3 → 4: 演完才刷新状态栏
            eng.destroy(e)
            return
    ud['age'] = age + 1


def start(battle, unit, dmg: int) -> None:
    """起中毒演出 (projectile 门控: 演完前玩家不能操作 / 敌人不开始 AI)."""
    e = battle.engine.spawn(think_fn=_think)
    e.flags = 0x800 | 0x10000
    e.user_data.update(kind='toxic', projectile=True, toxic=True, battle=battle, unit_t=unit, dmg=dmg, age=0, state=0)
    battle.toxic_active = True
