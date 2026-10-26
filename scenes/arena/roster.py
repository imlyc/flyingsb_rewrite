"""竞技场可选名册 + BattleUnit 构造.

左侧 (我方) = 10 个可玩角色; 右侧 (敌方) = ENEMY_TEMPLATES.
玩家单位用一套统一的竞技场基础数值 (满技能池), 敌人复用 setup.make_enemy.
"""

from __future__ import annotations

from core.battle.data import BattleUnit
from core.battle.setup import ENEMY_TEMPLATES, make_enemy
from core.character import CHARACTER_NAMES, PLAYABLE_SLOTS
from core.character_sprites import sprite_resource
from core.skills import default_skills_for

# 左侧可选: 10 个可玩角色 (按槽位顺序)
PLAYER_ROSTER: list[str] = [CHARACTER_NAMES[s] for s in PLAYABLE_SLOTS]

# 右侧可选: 敌人模板名
ENEMY_ROSTER: list[str] = list(ENEMY_TEMPLATES.keys())

# 竞技场玩家统一基础数值 (沙盒对战, 不读存档). agile 影响出手序 + 移动力.
_PLAYER_AGILE = {
    "孙悟空": 60, "美娜": 55, "三藏法师": 40, "猪八戒": 35, "沙悟净": 45,
    "蒙面人": 65, "乐神杰特": 50, "破无": 48, "捕山": 42, "紫河": 52,
}


def build_player_unit(name: str, weapon: int | None = None, accessories: tuple = ()) -> BattleUnit:
    agile = _PLAYER_AGILE.get(name, 45)
    from core.battle import energy
    if energy.ENERGY_TYPE.get(name) == energy.ENERGY_MP:
        max_mp, sg = 999, 0xFFFFFFFF            # MP 型: 沙盒给足 MP, 无 SG (同原版 -1)
    else:
        max_mp, sg = 0, energy.SG_MAX           # SG 型: 满格兴奋值, 无 MP
    u = BattleUnit(
        name=name, level=10,
        max_hp=60, hp=60, max_mp=max_mp, mp=max_mp, sg=sg,
        attack=24, defence=14, agile=agile,
        move=max(2, agile // 18),
        is_player=True,
        color=(120, 200, 230),
        sprite_key=sprite_resource(name),
        known_skills=default_skills_for(name),
        speed=24,                               # 原版主角速度 (角色表 +0x5c) 21..26
    )
    from core import normal_attack as NA
    u.attack_normal, u.attack_melee = NA.attack_ids(name, weapon, accessories)   # 无武器 = 本组第 0 项
    NA.zihe_setup(u, accessories)
    return u


def build_enemy_unit(name: str) -> BattleUnit:
    return make_enemy(name)
