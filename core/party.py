"""队伍 / 入队系统 (复刻原版开局与加入顺序).

原版开局主角是 **美娜** (slot 2); 后续角色按剧情加入:
  · 美娜  —— 游戏一开始就同行
  · 蒙面人 —— 第3章 五指山 · 蒙面人 (c3_masked)
  · 孙悟空 —— 第3章 五指山 · 收悟空 (c3_wukong)
  (更后面的 三藏/猪八戒/沙悟净… 等后续章节再补)

新游戏存档只激活美娜; 其余槽位为空 (MaxHP=0)。剧情 beat 完成时通过
`story.StoryState.complete` 调用 `activate_character` 把角色写入对应槽位。

注意: 这里的初始数值是**占位**(暂无原版新游戏初始化数据)。后续可从 exe 的
新游戏初始化例程提取真实 Lv/HP/MP 再替换 STARTING_STATS。
"""

from __future__ import annotations

from core.character import CHARACTER_NAMES, PLAYABLE_SLOTS, Character

# 角色名 → 存档槽位 (与 core.character.CHARACTER_NAMES 反向)
NAME_TO_SLOT: dict[str, int] = {v: k for k, v in CHARACTER_NAMES.items()
                                if k in PLAYABLE_SLOTS}

# 新游戏就同行的角色
NEW_GAME_PARTY: tuple[str, ...] = ("美娜",)

# 占位初始数值 (Lv/HP/MP/属性). 真实值待从 exe 提取。
STARTING_STATS: dict[str, dict] = {
    "美娜":   dict(MaxHP=42, MaxMP=22, Level=1, SG=10, Exp=0, nextExp=40,
                  Power=12, Wisdom=15, Agile=13, Attack=14, Defence=10, Luck=12),
    "蒙面人": dict(MaxHP=70, MaxMP=26, Level=4, SG=14, Exp=0, nextExp=120,
                  Power=18, Wisdom=10, Agile=16, Attack=22, Defence=14, Luck=10),
    "孙悟空": dict(MaxHP=35, MaxMP=16, Level=2, SG=20, Exp=115, nextExp=105,
                  Power=20, Wisdom=8,  Agile=18, Attack=24, Defence=12, Luck=14),
    "三藏法师": dict(MaxHP=38, MaxMP=30, Level=1, SG=9, Exp=0, nextExp=40,
                  Power=10, Wisdom=18, Agile=11, Attack=12, Defence=9, Luck=11),
    "猪八戒": dict(MaxHP=55, MaxMP=12, Level=2, SG=8, Exp=0, nextExp=80,
                  Power=16, Wisdom=8,  Agile=10, Attack=18, Defence=16, Luck=8),
    "沙悟净": dict(MaxHP=48, MaxMP=20, Level=2, SG=10, Exp=0, nextExp=80,
                  Power=14, Wisdom=14, Agile=12, Attack=16, Defence=13, Luck=10),
}

# 装备/Ext 默认 (UNSET)
_UNSET = 0xFFFFFFFF


def make_character(name: str) -> Character:
    """用**原版真实初始数值**构造 Character (Lv1 HP/MP/五维 + 初始装备).

    数据来自 exe 角色定义表 (core.character_data); 缺 assets 时回退旧占位.
    """
    from core import character_data
    real = character_data.make_character(name)
    if real is not None:
        return real
    s = STARTING_STATS.get(name, {})
    return Character(
        MaxHP=s.get("MaxHP", 1), CurrentHP=s.get("MaxHP", 1),
        MaxMP=s.get("MaxMP", 0), CurrentMP=s.get("MaxMP", 0),
        Level=s.get("Level", 1), SG=s.get("SG", 0),
        Unknow_1=0, Exp=s.get("Exp", 0), nextExp=s.get("nextExp", 50),
        Unknow_2=0, Unknow_3=0, Unknow_4=0, Unknow_5=0, Unknow_6=0,
        Unknow_7=0, Unknow_8=0,
        Power=s.get("Power", 10), Wisdom=s.get("Wisdom", 10),
        Agile=s.get("Agile", 10), Attack=s.get("Attack", 10),
        Defence=s.get("Defence", 10), Luck=s.get("Luck", 10),
        Unknow_9=0,
        Head=_UNSET, Body=_UNSET, Hand=_UNSET,
        Accessories1=_UNSET, Accessories2=_UNSET,
    )


def activate_character(save, name: str) -> bool:
    """把 name 加入存档 (写入其槽位). 已存在则跳过。返回是否新加入。"""
    slot = NAME_TO_SLOT.get(name)
    if slot is None or save is None:
        return False
    ch = save.characters.get(slot)
    if ch is not None and ch.MaxHP > 0:
        return False                       # 已在队
    save.characters[slot] = make_character(name)
    return True


def active_party(save) -> list[str]:
    """当前在队的角色名 (PLAYABLE_SLOTS 顺序)。无存档返回新游戏默认。"""
    if save is None:
        return list(NEW_GAME_PARTY)
    names = []
    for slot in PLAYABLE_SLOTS:
        ch = save.characters.get(slot)
        if ch is not None and ch.MaxHP > 0:
            names.append(CHARACTER_NAMES[slot])
    return names or list(NEW_GAME_PARTY)
