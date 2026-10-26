"""竞技场可选名册 + BattleUnit 构造.

左侧 (我方) = 10 个可玩角色; 右侧 (敌方) = 原版敌人表里全部真实敌人 (键 "#编号", 按等级排序;
2026-10-26 扩充, 原先是 4 个占位模板). 敌人用 setup.make_enemy_by_type 的真实数值/贴图/招式.
"""

from __future__ import annotations

from core.battle.data import BattleUnit
from core.battle.setup import ENEMY_TEMPLATES, make_enemy
from core.character import CHARACTER_NAMES, PLAYABLE_SLOTS
from core.character_sprites import sprite_resource
from core.skills import default_skills_for

# 左侧可选: 10 个可玩角色 (按槽位顺序)
PLAYER_ROSTER: list[str] = [CHARACTER_NAMES[s] for s in PLAYABLE_SLOTS]

def _real_enemies() -> list[str]:
    """原版敌人表里能上场的: 有 HP、有贴图文件、不是"身份不詳"空档. 按 (等级, 编号) 排."""
    from core.character_data import enemy
    from core.sprites.base import SPRITES_DIR as SPRITE_DIR
    out = []
    for k in range(256):
        e = enemy(k)
        if not e or int(e.get("hp", 0)) <= 0 or e.get("name") in (None, "", "身份不詳"):
            continue
        spr = e.get("sprite")
        if not spr or not (SPRITE_DIR / f"{spr}.png").exists():
            continue
        out.append((int(e.get("level", 0)), k))
    return [f"#{k}" for _, k in sorted(out)]


# 右侧可选: 全部真实敌人 ("#编号"); 缺资源时回退占位模板名
ENEMY_ROSTER: list[str] = _real_enemies() or list(ENEMY_TEMPLATES.keys())


def enemy_label(key: str) -> str:
    """名册键 → 显示名 ("#83" → 電熨斗)."""
    if key.startswith("#"):
        from core.character_data import enemy
        e = enemy(int(key[1:])) or {}
        return e.get("name") or key
    return key


def enemy_level(key: str) -> int | None:
    if key.startswith("#"):
        from core.character_data import enemy
        e = enemy(int(key[1:])) or {}
        return int(e.get("level", 0)) or None
    return ENEMY_TEMPLATES.get(key, {}).get("level")


def enemy_sprite_key(key: str) -> str | None:
    if key.startswith("#"):
        from core.character_data import enemy
        return (enemy(int(key[1:])) or {}).get("sprite")
    spr = ENEMY_TEMPLATES.get(key, {}).get("sprite")
    return f"ps_{spr}" if spr else None

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


def build_enemy_unit(key: str) -> BattleUnit:
    if key.startswith("#"):
        from core.battle.setup import make_enemy_by_type
        u = make_enemy_by_type(int(key[1:]))
        if u is not None:
            return u
    return make_enemy(key)
