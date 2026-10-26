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
ARENA_LEVEL = 40          # 竞技场我方等级 (40 级时学习表技能已全学会; 美娜 召喚精靈 是剧情学的, 另补)


def build_player_unit(name: str, weapon: int | None = None, accessories: tuple = (),
                      level: int = ARENA_LEVEL) -> BattleUnit:
    """原版真实数值: 初始角色表 (core.character_data.make_character) 逐级 level_up 到 level, 再走战场同一路径
    (core.battle.setup.unit_from_character: 敏捷/HP/MP/攻防/智力/幸运/速度, 移动 = 敏捷 ÷ 10).
    沙盒设定: MP 型满 MP, SG 型 SG=16; 武器/饰品按参数 (None = 空手, 普攻 = 本组第 0 项); 技能 = 学习表 ∪ 全技能."""
    from core import character_data
    from core.battle import energy
    from core.battle.setup import unit_from_character
    ch = character_data.make_character(name)
    if ch is None:
        raise KeyError(name)
    for lv in range(ch.Level + 1, level + 1):
        character_data.level_up(ch, name, lv)
    UNSET = 0xFFFFFFFF
    ch.Hand = UNSET if weapon is None else weapon
    acc = tuple(accessories) + (UNSET, UNSET)
    ch.Accessories1, ch.Accessories2 = acc[0], acc[1]
    ch.Agile = character_data.agile_with_equipment(ch)     # 换了武器/饰品 → 重算敏捷 (移动 = 敏捷 ÷ 10)
    ch.CurrentHP, ch.CurrentMP = ch.MaxHP, ch.MaxMP
    if energy.ENERGY_TYPE.get(name) != energy.ENERGY_MP:
        ch.SG = energy.SG_MAX
    ch.skills = []
    u = unit_from_character(name, ch)
    u.mp = u.max_mp
    if energy.ENERGY_TYPE.get(name) == energy.ENERGY_MP:
        u.sg = 0xFFFFFFFF                       # MP 型无 SG (同原版 -1)
    else:
        u.sg = energy.SG_MAX
    learned = character_data.learned_skills(name, level)
    u.known_skills = learned + [s for s in default_skills_for(name) if s not in learned]
    sk = sprite_resource(name)
    if sk:
        u.sprite_key = sk
    return u


def build_enemy_unit(key: str) -> BattleUnit:
    if key.startswith("#"):
        from core.battle.setup import make_enemy_by_type
        u = make_enemy_by_type(int(key[1:]))
        if u is not None:
            return u
    return make_enemy(key)
