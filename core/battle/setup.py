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


# exe 0x641820[角色槽]: 反击概率表 (FUN_004a65b6) 的行
PLAYER_UNIT_CLASS = {'孙悟空': 1, '美娜': 0, '三藏法师': 0, '猪八戒': 2, '沙悟净': 1, '蒙面人': 0, '乐神杰特': 1,
                     '破无': 2, '捕山': 2, '紫河': 1}


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
    u = BattleUnit(
        name=name,
        level=ch.Level,
        max_hp=ch.MaxHP + eb.get("hp", 0), hp=max(1, ch.CurrentHP + eb.get("hp", 0)),
        max_mp=ch.MaxMP + eb.get("mp", 0), mp=ch.CurrentMP + eb.get("mp", 0),
        sg=ch.SG,
        attack=base_atk + eb.get("atk", 0),
        defence=base_def + eb.get("def", 0),
        agile=ch.Agile,
        move=max(1, ch.Agile // 10),     # exe FUN_004a4a32: 移动力 = 敏捷 / 10 (BFS 步数)
        is_player=True,
        color=(120, 200, 230),
        sprite_key=_try_sprite_key(name),
        # 已学技能: 优先用存档角色块里解出的真实列表 (原版存档载入时), 否则按学习表推算
        known_skills=list(getattr(ch, "skills", []) or []) or _default_known_skills(name, ch.Level),
    )
    # 普攻: 武器决定普攻表项 (+0x74), 贴身项 (+0x78); 紫河按饰品预生成变身角色卡 (core.normal_attack)
    from core import normal_attack as NA
    weapon = None if ch.Hand in (0xFFFFFFFF, -1) else ch.Hand
    acc = tuple(a for a in (ch.Accessories1, ch.Accessories2) if a not in (0xFFFFFFFF, -1))
    u.attack_normal, u.attack_melee = NA.attack_ids(name, weapon, acc)
    NA.zihe_setup(u, acc)
    u.wisdom = ch.Wisdom
    u.luck = ch.Luck                       # 角色表 +0x58: 命中/闪避/暴击用的是幸运 (不是敏捷)
    u.speed = ch.Unknow_9                  # +0x5c: 每回合行动值增量 (exe FUN_004a4108)
    u.action_value = max(0, int(ch.Unknow_1) if ch.Unknow_1 < 0x80000000 else 0)   # +0x1c 行动值, 跨战斗保留
    u.unit_class = PLAYER_UNIT_CLASS.get(name, 0)
    u.equipment = tuple(e for e in (ch.Head, ch.Body, ch.Hand, ch.Accessories1, ch.Accessories2)
                        if e not in (0xFFFFFFFF, -1))
    u.save_ref = ch
    return u


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
                  color=( 80,  60,  90), sprite="CCROW00",
                  type_flags=0x10000000),          # 不触发地雷: 乌鸦怪 = 原版敌人表 烏拉 (#189..191, flags 0x14000080, 含 0x10000000; Unity 版显示名佐证)
}


def make_enemy(name: str) -> BattleUnit:
    t = ENEMY_TEMPLATES[name]
    sprite_key = f"ps_{t['sprite']}" if t.get("sprite") else None
    return BattleUnit(
        name=name,
        level=t["level"],
        max_hp=t["max_hp"], hp=t["max_hp"],
        max_mp=0, mp=0, sg=0,
        attack=t["attack"], defence=t["defence"], agile=t["agile"], speed=20,   # 占位模板: 每回合约一动
        move=t["move"],
        is_player=False,
        color=t["color"],
        exp_reward=t["exp_reward"], money_reward=t["money_reward"],
        sprite_key=sprite_key,
        type_flags=t.get("type_flags", 0),
    )


def make_enemy_by_type(etype: int) -> BattleUnit | None:
    """用原版敌人表 (assets/enemy_table.json, tools/extract_enemies.py) 的真实数值构造敌人.
    字段 2026-10-25 按 exe 消费者确认 (旧版标签错位: 把法攻当 HP 等). 缺数据返回 None."""
    from core.character_data import enemy as _enemy
    e = _enemy(etype)
    if e is None:
        return None

    def g(k: str, lo: int = 0) -> int:
        return max(lo, int(e.get(k, 0) or 0))
    hp, mp = g("hp", 1), g("mp")
    moves = [int(m) for m in e.get("moves", []) if 0 <= int(m) < 248]
    weights = [max(0, int(w)) for w in e.get("weights", [])][:len(moves)]
    return BattleUnit(
        name=e.get("name") or f"敌人#{etype}",
        level=g("level", 1),
        max_hp=hp, hp=hp,
        max_mp=mp, mp=mp, sg=0,
        attack=g("attack"), defence=g("defence"), agile=g("speed"),
        move=max(1, g("move10") // 10),           # exe FUN_004b1286: 移动力 = +0x24 / 10
        is_player=False,
        color=(210, 120, 120),
        exp_reward=g("exp"),
        money_reward=g("money"),
        sprite_key=None,
        # 招式 = 敌方招式表 (248 项) 下标 (不是玩家技能 id); 演出另做, 现在只用它配普攻音效.
        known_skills=[],
        enemy_moves=moves,
        move_weights=weights,
        type_flags=int(e.get("flags", 0)) & 0xffffffff,
        wisdom=g("wisdom"), luck=g("luck"), magic_atk=g("magic_atk"), evade=g("evade"),
        speed=g("speed"), unit_class=g("class"), enemy_type=etype,
    )
