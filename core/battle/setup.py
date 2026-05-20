"""战场单位 / 敌人模板的构造函数.

unit_from_character: 存档角色 → BattleUnit (从 Character 字段映射, 用 Unknow_5/6 当基础攻防)
make_enemy:          ENEMY_TEMPLATES 表 → BattleUnit
"""

from __future__ import annotations

from core.character import Character
from core.battle.data import BattleUnit


def _try_sprite_key(name: str) -> str | None:
    from core.character_sprites import CHARACTER_SPRITES, sprite_resource
    return sprite_resource(name) if name in CHARACTER_SPRITES else None


def unit_from_character(name: str, ch: Character) -> BattleUnit:
    """把存档里的角色转换成战场单位.

    存档里的 Attack/Defence 含装备加成数值很大 (1142, 358), 直接用会一击秒杀.
    Unknow_5 / Unknow_6 看起来是基础攻防 (17/18 这种合理值), 战棋平衡用这两个.
    """
    base_atk = ch.Unknow_5 if ch.Unknow_5 > 0 else max(10, ch.Power)
    base_def = ch.Unknow_6 if ch.Unknow_6 > 0 else max(5, ch.Wisdom // 2)
    return BattleUnit(
        name=name,
        level=ch.Level,
        max_hp=ch.MaxHP, hp=max(1, ch.CurrentHP),
        max_mp=ch.MaxMP, mp=ch.CurrentMP,
        sg=ch.SG,
        attack=base_atk, defence=base_def, agile=ch.Agile,
        move=max(2, ch.Agile // 25),     # 99/25 ≈ 3, 49/25 ≈ 1 → max(2, .)
        is_player=True,
        color=(120, 200, 230),
        sprite_key=_try_sprite_key(name),
        known_skills=_default_known_skills(name),
    )


def _default_known_skills(name: str) -> list[int]:
    """默认技能 = 该角色潜在技能池全集 (= 模拟满级解锁). 等接 level-up 解锁系统再改."""
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
