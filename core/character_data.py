"""角色真实数据 (新游戏初始数值 / 成长 / 经验) + 敌人真实数值.

数据源: FlyingSB.exe 静态逆向, 由 tools 导出到 assets/:
  · tools/extract_characters.py → assets/characters_table.json
      - characters: 16 条角色定义 (Lv1 初始 HP/MP/五维 + 初始装备)
      - growth_rows / exp_table
  · tools/extract_enemies.py    → assets/enemy_table.json

缺 assets 时, 各函数返回 None / 空, 调用方回退到旧占位 (CI/单测可跑).
"""
from __future__ import annotations

import json
from pathlib import Path

from core.character import UNSET, Character

ROOT = Path(__file__).resolve().parent.parent
_CHAR_FILE = ROOT / "assets" / "characters_table.json"
_ENEMY_FILE = ROOT / "assets" / "enemy_table.json"
_SKILL_FILE = ROOT / "assets" / "skill_learn.json"

_char_cache: dict | None = None
_enemy_cache: dict | None = None
_skill_cache: dict | None = None

MAX_LEVEL = 99

# 简体角色名 → 角色定义表记录号 (exe 里是繁体; 孙悟空有 3 条, 取带装备的那条)
NAME_TO_RECORD: dict[str, int] = {
    "孙悟空": 1, "美娜": 3, "三藏法师": 4, "猪八戒": 5, "沙悟净": 6,
    "蒙面人": 8, "乐神杰特": 9, "破无": 10, "捕山": 11, "紫河": 12,
}


def _chars() -> dict:
    global _char_cache
    if _char_cache is None:
        try:
            _char_cache = json.loads(_CHAR_FILE.read_text(encoding="utf-8"))
        except Exception:
            _char_cache = {}
    return _char_cache


def _enemies() -> dict:
    global _enemy_cache
    if _enemy_cache is None:
        try:
            _enemy_cache = json.loads(
                _ENEMY_FILE.read_text(encoding="utf-8")).get("enemies", {})
        except Exception:
            _enemy_cache = {}
    return _enemy_cache


def records() -> list[dict]:
    return _chars().get("characters", [])


def record_for(name: str) -> dict | None:
    k = NAME_TO_RECORD.get(name)
    recs = records()
    if k is not None and k < len(recs):
        return recs[k]
    # 退化: 按名匹配 (简繁无关, 用包含)
    for r in recs:
        if r.get("name") == name:
            return r
    return None


def exp_table() -> list[int]:
    return _chars().get("exp_table", [])


def exp_needed(level: int) -> int:
    """升到 level+1 的**累计**经验阈值 (exe 表 0x642670[level]; 0 = 满级). 注意不是"这一级要多少"."""
    t = exp_table()
    if level < 1 or level >= len(t) or level >= MAX_LEVEL:
        return 0
    return int(t[level])


def starting_stats(name: str) -> dict | None:
    """新游戏初始数值 (含裸装基础攻/防/运 + 初始装备). 缺数据返回 None."""
    rec = record_for(name)
    if rec is None:
        return None
    f = rec["fields"]

    def eq(v: int) -> int:
        return UNSET if v is None or v < 0 else v

    return {
        "MaxHP": f.get("MaxHP", 1), "MaxMP": f.get("MaxMP", 0),
        "Level": f.get("Level", 1) or 1, "SG": f.get("SG", 0),
        "Exp": f.get("Exp", 0), "nextExp": f.get("nextExp", 0),
        "Power": f.get("Power", 10), "Wisdom": f.get("Wisdom", 10),
        "Agile": f.get("Agile", 10), "Attack": f.get("Attack", 10),
        "Defence": f.get("Defence", 10), "Luck": f.get("Luck", 10),
        # 裸装基础攻/防/运 (battle 用基础 + 装备加成; 见 battle/setup.py)
        "base_atk": f.get("Unknow_5", 0), "base_def": f.get("Unknow_6", 0),
        "base_luck": f.get("Unknow_7", 0),
        "Head": eq(f.get("Head", UNSET)), "Body": eq(f.get("Body", UNSET)),
        "Hand": eq(f.get("Hand", UNSET)),
        "Accessories1": eq(f.get("Accessories1", UNSET)),
        "Accessories2": eq(f.get("Accessories2", UNSET)),
    }


def make_character(name: str) -> Character | None:
    """用原版真实初始数值构造 Character (HP/MP 满)."""
    s = starting_stats(name)
    if s is None:
        return None
    return Character(
        MaxHP=s["MaxHP"], CurrentHP=s["MaxHP"],
        MaxMP=s["MaxMP"], CurrentMP=s["MaxMP"],
        Level=s["Level"], SG=s["SG"] if s["SG"] != UNSET else 0,
        Unknow_1=0, Exp=s["Exp"], nextExp=s["nextExp"],
        Unknow_2=0, Unknow_3=0, Unknow_4=0,
        Unknow_5=s["base_atk"], Unknow_6=s["base_def"], Unknow_7=s["base_luck"],
        Unknow_8=0,
        Power=s["Power"], Wisdom=s["Wisdom"], Agile=s["Agile"],
        Attack=s["Attack"], Defence=s["Defence"], Luck=s["Luck"],
        Unknow_9=0,
        Head=s["Head"], Body=s["Body"], Hand=s["Hand"],
        Accessories1=s["Accessories1"], Accessories2=s["Accessories2"],
    )


def growth_gains(name: str, level: int) -> dict[str, int]:
    """升到 `level` 时的成长增量 (来自成长行: 最大HP / 最大MP / 基础攻 / 基础防)."""
    rec = record_for(name)
    if rec is None or level < 1:
        return {}
    rows = _chars().get("growth_rows", {})
    row_ids = rec.get("growth_rows", [])
    keys = ["MaxHP", "MaxMP", "base_atk", "base_def"]
    out: dict[str, int] = {}
    for i, rid in enumerate(row_ids):
        if rid < 0:
            continue
        row = rows.get(str(rid), [])
        if 0 <= level < len(row):
            v = int(row[level])
            if v:
                out[keys[i]] = out.get(keys[i], 0) + v
    return out


def level_up(ch: Character, name: str, new_level: int) -> None:
    """把成长增量应用到角色 (升到 new_level); 最大 HP/MP 成长时同步回满."""
    g = growth_gains(name, new_level)
    if not g:
        return
    ch.MaxHP += g.get("MaxHP", 0)
    ch.MaxMP += g.get("MaxMP", 0)
    ch.Unknow_5 += g.get("base_atk", 0)      # 裸装基础攻击
    ch.Unknow_6 += g.get("base_def", 0)      # 裸装基础防御
    ch.Attack += g.get("base_atk", 0)        # 最终值同步
    ch.Defence += g.get("base_def", 0)
    ch.Level = new_level
    ch.CurrentHP = ch.MaxHP                  # 原版升级即回满 (0x4ac2ba: MaxHP→CurHP)
    ch.CurrentMP = ch.MaxMP


def add_exp(ch: Character, name: str, amount: int) -> list[int]:
    """exe FUN_004a5e0b: Exp 是累计值, 达到阈值表[等级] → **只升一级** (多出的截到 阈值[新等级] - 1),
    nextExp = 阈值[等级] - Exp; 99 级封顶. 返回升到的等级列表 ([] 或 [新等级])."""
    if amount <= 0:
        return []
    total = ch.Exp + amount
    if ch.Level >= MAX_LEVEL:
        ch.Exp, ch.nextExp = total, 0
        return []
    need = exp_needed(ch.Level)
    if need <= 0 or total < need:
        ch.Exp, ch.nextExp = total, max(0, need - total)
        return []
    new = ch.Level + 1
    cap = exp_needed(new)
    if cap > 0 and total >= cap:
        total = cap - 1
    level_up(ch, name, new)
    ch.Level = new
    ch.Exp = total
    ch.nextExp = 0 if new >= MAX_LEVEL else max(0, exp_needed(new) - total)
    return [new]


# ---------------- 技能学习 (VA 0x64216C; 见 tools/extract_skill_learn.py) ----------------
# 角色定义表记录号 → 简体角色名 (记录 12/14/15 也是紫河; 7 = 迪特, 不可玩)
RECORD_NAME = ["<gap>", "孙悟空", "孙悟空", "美娜", "三藏法师", "猪八戒", "沙悟净",
               "迪特", "蒙面人", "乐神杰特", "破无", "捕山", "紫河", "紫河", "紫河", "紫河"]

# **靠剧情学到的技能** (学习表里没有/为空, 由剧情事件授予):
#   沙悟净: 剧情里向一位忍者 NPC 学会 斗转星移(0x1E) / 返荷杖(0x1F) —— 入队后即可用.
STORY_LEARNED: dict[str, list[int]] = {
    "沙悟净": [0x1E, 0x1F],
}


def _skills() -> dict:
    global _skill_cache
    if _skill_cache is None:
        try:
            _skill_cache = json.loads(
                _SKILL_FILE.read_text(encoding="utf-8")).get("records", {})
        except Exception:
            _skill_cache = {}
    return _skill_cache


def _skill_entry(name: str) -> dict | None:
    """该角色的学习表记录 (同一角色名可能有多条定义: 取**有学习数据**的那条)."""
    recs = _skills()
    rec = NAME_TO_RECORD.get(name)
    if rec is not None and recs.get(str(rec), {}).get("learn"):
        return recs[str(rec)]
    for k, v in recs.items():
        if v.get("learn") and RECORD_NAME[int(k)] == name:
            return v
    return None


def skill_learn_table(name: str) -> list[tuple[int, int]]:
    """(等级, 技能id) 列表 (已把池下标换算成全局技能 id). 无数据返回 []."""
    from core.skills import CHARACTER_SKILL_POOL
    pool = CHARACTER_SKILL_POOL.get(name)
    entry = _skill_entry(name)
    if not pool or not entry:
        return []
    out = []
    for lv, idx in entry.get("learn", []):
        if 0 <= idx < len(pool):
            out.append((int(lv), pool[idx]))
    return out


def starting_skills(name: str) -> list[int]:
    """开局就会的技能 = 角色定义表 extra[3..12] 里列出的 (原版语义).

    实证: 存档角色块的同一位置 (extra[3..12]) 就是「已学技能列表」,
    悟空(0..9)/美娜(10..18) 与等级学习表完全吻合; 定义表里只列**初始**那几个
    (美娜 = [10] 小回复)。故不再用「未出现在学习表里的池下标」当开局技能
    (那个规则会误把 美娜 的 19 召唤精灵 当成开局技能)。
    """
    rec = record_for(name)
    if rec is None:
        return []
    return [int(s) for s in rec.get("initial_skills", [])]


def story_skills(name: str) -> list[int]:
    """该角色**靠剧情 (拜师/事件) 学会**的技能 —— 入队后即可用 (见 STORY_LEARNED)."""
    return list(STORY_LEARNED.get(name, ()))


def learned_skills(name: str, level: int) -> list[int]:
    """该角色在 `level` 级已学会的全部技能 id = 开局技能 + 等级达标的表项."""
    from core.skills import CHARACTER_SKILL_POOL
    pool = CHARACTER_SKILL_POOL.get(name)
    if not pool:
        return []
    known = set(starting_skills(name))
    for lv, skill in skill_learn_table(name):
        if lv <= level:
            known.add(skill)
    known.update(story_skills(name))     # 剧情学到的 (入队后可用)
    return sorted(known)


# ---------------- 敌人 ----------------
def enemy(etype: int) -> dict | None:
    return _enemies().get(str(etype))


def enemy_count() -> int:
    return len(_enemies())


# ---------------- 敌方招式 ----------------
_ENEMY_ACTIONS: dict | None = None


def enemy_action(move_id: int) -> dict | None:
    """敌方招式表 (assets/enemy_actions.json, tools/extract_enemy_actions.py; exe 0x692f54 stride 0x20):
    param_a = 威力 (+4), flags (+8: 0x800000 物理 / 0x4000 计方位 / 0x8000 计属性 / 0x10 可反击 / 0xf000000 类别 /
    0x1f00 附带异常), p3 = 出招扣敌 MP (+0xc)."""
    global _ENEMY_ACTIONS
    if _ENEMY_ACTIONS is None:
        import json
        p = ROOT / "assets" / "enemy_actions.json"
        try:
            _ENEMY_ACTIONS = json.loads(p.read_text(encoding="utf-8")).get("actions", {})
        except (OSError, ValueError):
            _ENEMY_ACTIONS = {}
    return _ENEMY_ACTIONS.get(str(move_id))
