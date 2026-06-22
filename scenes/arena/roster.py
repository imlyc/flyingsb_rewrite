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


def build_player_unit(name: str) -> BattleUnit:
    agile = _PLAYER_AGILE.get(name, 45)
    return BattleUnit(
        name=name, level=10,
        max_hp=60, hp=60, max_mp=40, mp=40, sg=50,
        attack=24, defence=14, agile=agile,
        move=max(2, agile // 18),
        is_player=True,
        color=(120, 200, 230),
        sprite_key=sprite_resource(name),
        known_skills=default_skills_for(name),
    )


def build_enemy_unit(name: str) -> BattleUnit:
    return make_enemy(name)
