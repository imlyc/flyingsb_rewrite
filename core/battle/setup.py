"""战场单位 / 敌人模板的构造函数.

unit_from_character: 存档角色 → BattleUnit (从 Character 字段映射, 用 Unknow_5/6 当基础攻防)
make_enemy:          ENEMY_TEMPLATES 表 → BattleUnit
"""

from __future__ import annotations

from core.character import Character
from core.battle.data import BattleUnit
from core.items import item_combat_bonus


def _try_sprite_key(name: str) -> str | None:
    from core.character_sprites import CHARACTER_SPRITES, sprite_resource
    return sprite_resource(name) if name in CHARACTER_SPRITES else None


def _equip_bonus(ch: Character) -> dict[str, int]:
    """汇总角色五件装备的战斗加成 (真实值, 取自 exe 物品表; 见 core.items.item_combat_bonus)."""
    tot: dict[str, int] = {}
    for eq in (ch.Head, ch.Body, ch.Hand, ch.Accessories1, ch.Accessories2):
        if eq == 0xFFFFFFFF or eq < 0:
            continue
        for k, v in item_combat_bonus(eq).items():
            tot[k] = tot.get(k, 0) + v
    return tot


def unit_from_character(name: str, ch: Character) -> BattleUnit:
    """把存档里的角色转换成战场单位.

    逆向确认: 存档 Character.Attack/Defence/Luck (index 19/20/21) 是**含装备的最终值**;
    其"裸装基础值"分别存在 Unknow_5 / Unknow_6 / Unknow_7 (index 12/13/14)
    (证据: 装备应用函数 0x4334b0 把 item 攻击加成加到角色 Attack, 而 0x43332d 又把
    Unknow_6 写回 Defence; 升级逻辑也只加 Unknow_5/6).
    故战场用「基础值 + 真实装备加成」= 原版最终值.
    """
    base_atk = ch.Unknow_5 if ch.Unknow_5 > 0 else max(10, ch.Power)
    base_def = ch.Unknow_6 if ch.Unknow_6 > 0 else max(5, ch.Wisdom // 2)
    eb = _equip_bonus(ch)
    return BattleUnit(
        name=name,
        level=ch.Level,
        max_hp=ch.MaxHP + eb.get("hp", 0), hp=max(1, ch.CurrentHP + eb.get("hp", 0)),
        max_mp=ch.MaxMP + eb.get("mp", 0), mp=ch.CurrentMP + eb.get("mp", 0),
        sg=ch.SG,
        attack=base_atk + eb.get("atk", 0),
        defence=base_def + eb.get("def", 0),
        agile=ch.Agile,
        move=max(2, ch.Agile // 25),     # 99/25 ≈ 3, 49/25 ≈ 1 → max(2, .)
        is_player=True,
        color=(120, 200, 230),
        sprite_key=_try_sprite_key(name),
        # 已学技能: 优先用存档角色块里解出的真实列表 (原版存档载入时), 否则按学习表推算
        known_skills=list(getattr(ch, "skills", []) or []) or _default_known_skills(name, ch.Level),
    )


def _default_known_skills(name: str, level: int = 99) -> list[int]:
    """该角色在 `level` 级已学会的技能 (原版学习表; 缺数据回退满池)."""
    from core import character_data
    known = character_data.learned_skills(name, level)
    if known:
        return known
    from core.skills import default_skills_for
    return default_skills_for(name)


# ---------------- 敌人模板 ----------------
# sprite 字段是 ase_ps 资源名 (不含 ps_ 前缀和扩展名, 例: 'CSKEL00' / 'CSKEL000'); None=保留色块
ENEMY_TEMPLATES: dict[str, dict] = {
    "骷髅":   dict(level=3, max_hp=30, attack=10, defence=5,  agile=8,  move=3, exp_reward=40,  money_reward=15,
                  color=(220, 220, 220), sprite="CSKEL00"),
    "黄色怪": dict(level=5, max_hp=50, attack=15, defence=8,  agile=6,  move=2, exp_reward=80,  money_reward=30,
                  color=(220, 200,  60), sprite="CGHOU00"),
    "贼":     dict(level=4, max_hp=35, attack=12, defence=5,  agile=14, move=4, exp_reward=50,  money_reward=20,
                  color=(180, 140, 100), sprite="CTHI00"),
    "乌鸦怪": dict(level=2, max_hp=20, attack=8,  defence=3,  agile=12, move=4, exp_reward=30,  money_reward=10,
                  color=( 80,  60,  90), sprite="CCROW00"),
}


def make_enemy(name: str) -> BattleUnit:
    t = ENEMY_TEMPLATES[name]
    sprite_key = f"ps_{t['sprite']}" if t.get("sprite") else None
    return BattleUnit(
        name=name,
        level=t["level"],
        max_hp=t["max_hp"], hp=t["max_hp"],
        max_mp=0, mp=0, sg=0,
        attack=t["attack"], defence=t["defence"], agile=t["agile"],
        move=t["move"],
        is_player=False,
        color=t["color"],
        exp_reward=t["exp_reward"], money_reward=t["money_reward"],
        sprite_key=sprite_key,
    )


def make_enemy_by_type(etype: int) -> BattleUnit | None:
    """用原版敌人表 (assets/enemy_table.json) 的真实数值构造敌人.

    字段语义见 tools/extract_enemies.py: hp(已证) / attack(已证) / exp / money /
    ai / 技能 / 掉落; defence 与 agile 为推断值 (仍标注在 enemy_table.json 里).
    缺数据返回 None.
    """
    from core.character_data import enemy as _enemy
    e = _enemy(etype)
    if e is None:
        return None
    hp = max(1, int(e.get("hp", 1)))
    attack = max(1, int(e.get("attack", 1)))
    defence = max(0, int(e.get("magic_def", 0)))     # 推断: 防御
    agile = max(1, int(e.get("unk13", 10)))          # 推断: 敏捷
    move = min(6, max(2, int(e.get("unk10", 3)) or 3))
    variant = int(e.get("variant", 1))
    return BattleUnit(
        name=e.get("name") or f"敌人#{etype}",
        level=max(1, variant),
        max_hp=hp, hp=hp,
        max_mp=0, mp=0, sg=0,
        attack=attack, defence=defence, agile=agile,
        move=move,
        is_player=False,
        color=(210, 120, 120),
        exp_reward=max(0, int(e.get("exp", 0))),
        money_reward=max(0, int(e.get("money", 0))),
        sprite_key=None,
        known_skills=list(e.get("skills", [])),
        ai_group=max(0, int(e.get("ai_group", 0))),
    )
