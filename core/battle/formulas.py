"""战斗数值公式 — 照 exe 伤害结算函数 FUN_004a6efe 逐分支搬 (2026-10-25 逆向, reverse_engineering/fn_4a6efe.txt,
dmg_helpers.txt). 随机数 rand()%n 用 battle.rng.randrange(n) 代替 (序列不同, 分布相同).

属性来源: 玩家 = 角色表 (幸运 +0x58 / 智力 +0x48 / 等级 +0x14 / 攻防 +0x50/+0x54); 敌人 = 敌人表 (tools/extract_enemies.py).
标志字: 玩家 = 状态字 A (status_bits); 敌人 = 实例 flags (= 敌人表 flags | 状态位).

方位 (FUN_004a6462): 攻击者相对目标朝向的位置 → 0 正面 .. 2 侧面 .. 4 正背后 (21×21 表 0x642800), 目标睡眠/痲痺 → 4.
  只有带 0x4000 标志的招式/普攻才计方位. 命中加成 [0,8,15,23,30] (FUN_004a654a), 伤害倍率 [100,110,120,135,150]% (FUN_004a6580).
属性 (FUN_004a663b): flags & 0xf000000 → 0..4, 5×5 表 → 50 / 100 / 170 %. 玩家属性字 (0x689d54) 全为 0 → 实际只有敌招之间有效.
相性 (FUN_004a6e0d): flags & 0x3000: 0x2000 = +10 (幸運進行曲), 0x1000 = -10 (咀咒); 返回 攻方 - 守方, 加到命中/暴击.
随机浮动: 物理 80..119% (rand%40+80), 法术 90..109% (rand%20+90). 伤害上限 9999 (FUN_004a6ee4).
范围衰减 w (0..15, 8 = 满额): 伤害格 pattern 字节高 4 位 (core.skill_patterns.strike_falloff), 伤害 × w / 8.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.battle.data import BattleUnit

DMG_CAP = 9999
DIR_HIT = (0, 8, 15, 23, 30)
DIR_DMG = (100, 110, 120, 135, 150)
# exe 0x642800: 行 = 相对纵向 r+10, 列 = 相对横向 c+10 (已按目标朝向旋转, 目标面朝 r<0 方向)
_DIR_ROWS = ('111110000000000011111', '111111000000000111111', '111111000000000111111', '111111100000001111111',
             '111111100000001111111', '111111110000011111111', '221111110000011111122', '222211111000111112222',
             '222222111000111222222', '222222221101122222222', '222222222202222222222', '222222223343322222222',
             '222222333343333222222', '222233333444333332222', '223333333444333333322', '333333334444433333333',
             '333333334444433333333', '333333344444443333333', '333333344444443333333', '333333444444444333333',
             '333333444444444333333')
# FUN_004a663b: 攻方属性行 × 守方属性列 → 0/1/2 → 50/100/170 %
_ELEM = ((1, 1, 1, 1, 1), (1, 1, 2, 1, 0), (1, 0, 1, 2, 1), (1, 1, 0, 1, 2), (1, 2, 1, 0, 1))
_ELEM_PCT = (50, 100, 170)
_ELEM_IDX = {0x1000000: 1, 0x2000000: 2, 0x4000000: 3, 0x8000000: 4}
SLEEP, PARALYSIS = 0x200, 0x800
F_PHYSICAL, F_DIR, F_ELEM, F_COUNTERABLE = 0x800000, 0x4000, 0x8000, 0x10
ST_SAMBA, ST_GUARD = 0x10000, 0x20000            # 強力森巴 (伤害 ×1.5) / 強力防禦 (受物理伤害 ×65%)
NAYIN_TYPES = (9, 10)                            # 那印: 不装备 0x15c 打不中
NAYIN_ITEM = 0x15C


def _rand(battle, n: int) -> int:
    return battle.rng.randrange(n)


def _div(a: int, b: int) -> int:
    """C 整数除法 (向 0 取整)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def flags_of(u: "BattleUnit") -> int:
    """exe 的"状态/类型字": 玩家 = 状态字 A; 敌人 = 实例 flags (类型 flags | 状态位)."""
    bits = getattr(u, 'status_bits', 0)
    return bits if u.is_player else (int(getattr(u, 'type_flags', 0)) | bits)


def elem_flags(u: "BattleUnit") -> int:
    """属性字: 玩家 = 角色记录 +4 (0x689d54, 原版全 0); 敌人 = 实例 flags."""
    return 0 if u.is_player else flags_of(u)


def element_mult(att: int, dfn: int) -> int:
    return _ELEM_PCT[_ELEM[_ELEM_IDX.get(att & 0xf000000, 0)][_ELEM_IDX.get(dfn & 0xf000000, 0)]]


def _aff(f: int) -> int:
    f &= 0x3000
    return 10 if f == 0x2000 else (-10 if f == 0x1000 else 0)


def affinity(att: "BattleUnit", dfn: "BattleUnit") -> int:
    return _aff(flags_of(att)) - _aff(flags_of(dfn))


def dir_index(att: "BattleUnit", dfn: "BattleUnit") -> int:
    """FUN_004a6462 + 睡眠/痲痺 → 4."""
    if flags_of(dfn) & (SLEEP | PARALYSIS):
        return 4
    dx, dy = dfn.x - att.x, dfn.y - att.y
    if abs(dx) >= 11 or abs(dy) >= 11:
        return 0
    f = {(0, -1): 0, (0, 1): 1, (-1, 0): 2, (1, 0): 3}.get(tuple(dfn.facing), 1)
    c, r = ((-dx, -dy), (dx, dy), (dy, -dx), (-dy, dx))[f]
    return int(_DIR_ROWS[r + 10][c + 10])


def _has_equip(u: "BattleUnit", item: int) -> bool:
    return item in getattr(u, 'equipment', ())


@dataclass
class Outcome:
    hit: bool = True
    crit: bool = False
    dmg: int = 0
    magic: bool = False
    reflect: int = 0          # 返荷时攻击者受到的伤害 (exe local_250)
    dir: int = 0
    status_chance: int = 0    # 命中后附带异常的掷骰百分比 (FUN_004a69e7 第 3 参)
    roll: int = 0             # 命中骰 (rand%101); 反击判定复用它 (exe local_e0 / local_240)


def _phys_roll(battle, base: int, lo: int = 80) -> int:
    if base < 5:
        base = _rand(battle, 5) + 1
    return _div(base * (_rand(battle, 40) + lo), 100)


def _finish(dmg: int, dir_i: int, crit: bool, falloff: int, samba: bool) -> int:
    if samba:
        dmg = _div(dmg * 150, 100)
    dmg = _div(dmg * DIR_DMG[dir_i], 100)
    if crit:
        dmg <<= 1
    return max(0, min(DMG_CAP, _div(dmg * falloff, 8)))


def player_normal(battle, p: "BattleUnit", e: "BattleUnit", entry_flags: int, falloff: int = 8) -> Outcome:
    """玩家普攻 → 敌人 (FUN_004a6efe act==1)."""
    d = dir_index(p, e) if entry_flags & F_DIR else 0
    aff = affinity(p, e)
    chance = DIR_HIT[d] + 80 - e.evade + p.luck - e.luck + aff + _div(p.level, 3)
    chance = max(10, min(90, chance))
    roll = _rand(battle, 101)
    hit = roll < chance
    if getattr(e, 'enemy_type', -1) in NAYIN_TYPES and not _has_equip(p, NAYIN_ITEM):
        hit = False
    out = Outcome(hit=hit, dir=d, status_chance=23, roll=roll)
    if not hit:
        return out
    out.crit = _rand(battle, 101) < (p.luck + 5 - e.luck + p.level + aff) - e.level
    base = p.attack - e.defence
    elem = element_mult(elem_flags(p), elem_flags(e)) if entry_flags & F_ELEM else 100
    dmg = _div(_phys_roll(battle, base) * elem, 100)
    out.dmg = _finish(dmg, d, out.crit, falloff, bool(flags_of(p) & ST_SAMBA))
    return out


def player_skill(battle, p: "BattleUnit", e: "BattleUnit", sid: int, falloff: int = 8) -> Outcome:
    """玩家攻击技能 → 敌人 (act==2 case 0). 法术 (无 0x800000) 必中无暴击; 物理同普攻但防御减半、命中 40..100."""
    from core.skill_table import SKILL_TABLE
    flags, power = SKILL_TABLE[sid][0], SKILL_TABLE[sid][1]
    d = dir_index(p, e) if flags & F_DIR else 0
    if not flags & F_PHYSICAL:
        if sid == 0x40 and flags_of(e) & 0x20:          # 修羅勾魂 打 boss: 威力 10
            power = 10
        bonus = max(0, _div((p.wisdom - e.wisdom) * power, 200))
        dmg = _div((power + p.level * 2) * (_rand(battle, 20) + 90), 100) + bonus
        mult = 100
        ef = flags_of(e)
        if sid == 1 and ef & 0x1000000:                 # 青龍
            mult = 0
        elif sid == 2 and ef & 0x4000000:               # 白虎
            mult = 0
        elif sid == 5 and ef & 0x2000000:               # 朱雀
            mult = 0
        elif sid == 6 and ef & 0x4000000:               # 玄武
            mult = 50
        elif sid == 0xc and ef & 0x100000:              # 聖水 对 0x100000 (亡灵?) 10..17.99 倍
            mult = _rand(battle, 800) + 1000
        elif sid not in (1, 2, 5, 6, 0xc) and flags & F_ELEM:
            mult = element_mult(elem_flags(p), elem_flags(e))
        dmg = _div(_div(dmg * mult, 100) * falloff, 8)
        return Outcome(hit=True, magic=True, dmg=max(0, min(DMG_CAP, dmg, e.hp)), dir=d)
    aff = affinity(p, e)
    roll = _rand(battle, 101)
    chance = max(40, min(100, DIR_HIT[d] + 90 - e.evade + p.luck + aff - e.luck))
    hit = roll < chance
    if getattr(e, 'enemy_type', -1) in NAYIN_TYPES and not _has_equip(p, NAYIN_ITEM):
        hit = False
    out = Outcome(hit=hit, dir=d, status_chance=10)
    if not hit:
        return out
    out.crit = _rand(battle, 101) < (p.luck + 5 - e.luck + aff + p.level) - e.level
    base = p.attack - _div(e.defence, 2)
    elem = element_mult(elem_flags(p), elem_flags(e)) if flags & F_ELEM else 100
    dmg = _div(_div(_phys_roll(battle, base) * power, 100) * elem, 100)
    out.dmg = _finish(dmg, d, out.crit, falloff, bool(flags_of(p) & ST_SAMBA))
    return out


def enemy_move(move_id: int) -> dict:
    """敌方招式表 (0x692f54 stride 0x20): power (+4) / flags (+8) / mp_cost (+0xc)."""
    from core.character_data import enemy_action
    a = enemy_action(move_id) or {}
    return dict(power=int(a.get('param_a', 100) or 0), flags=int(a.get('flags', F_PHYSICAL | F_DIR | F_COUNTERABLE)),
                mp_cost=int(a.get('p3', 0) or 0))


def enemy_attack(battle, e: "BattleUnit", p: "BattleUnit", move_id: int | None, falloff: int = 8) -> Outcome:
    """敌招 (类别 0 = 伤害) → 玩家 (FUN_004a6efe 敌方分支 case 0)."""
    from core.battle.status import ST_FANHE
    mv = enemy_move(move_id) if move_id is not None else dict(power=100, flags=F_PHYSICAL | F_DIR | F_COUNTERABLE,
                                                              mp_cost=0)
    flags, power = mv['flags'], mv['power']
    physical = bool(flags & F_PHYSICAL)
    d = dir_index(e, p) if flags & F_DIR else 0
    aff = affinity(e, p)
    chance = max(10, min(90, DIR_HIT[d] + 80 - p.luck + e.luck + aff))
    roll = _rand(battle, 101)
    reflect = bool(flags_of(p) & ST_FANHE)
    out = Outcome(hit=reflect or not physical or roll < chance, magic=not physical, dir=d, status_chance=10, roll=roll)
    if not out.hit:
        return out
    out.crit = _rand(battle, 101) < ((5 - p.luck) + e.luck - p.level) + aff + e.level
    elem = element_mult(elem_flags(e), elem_flags(p)) if flags & F_ELEM else 100
    if not physical:
        out.reflect = e.magic_atk
        dmg = _div((e.magic_atk + e.wisdom - p.wisdom) * power * (_rand(battle, 20) + 90), 10000)
    else:
        base = e.attack - _div(p.defence, 2)
        if base < 5:
            base = _rand(battle, 5) + 1
        out.reflect = e.attack
        dmg = _div(base * (_rand(battle, 40) + 80), 100)
        if flags_of(p) & ST_GUARD:
            dmg = _div(dmg * 65, 100)
    dmg = _div(_div(dmg * elem, 100) * DIR_DMG[d], 100)
    if out.crit:
        dmg <<= 1
        out.reflect <<= 1
    out.dmg = max(0, min(DMG_CAP, _div(dmg * falloff, 8)))
    out.reflect = max(0, min(DMG_CAP, _div(out.reflect * falloff, 8)))
    return out


def heal_amount(battle, caster: "BattleUnit", sid: int, falloff: int = 8) -> int:
    """回复技能 (act==2 case 1, flags 0x40): 法术型 威力×(rand%20+90)/100 + 智力×威力/100;
    物理型 (0x800000, 生命之火/回復豬彈) 攻击×(rand%20+90)/100; ×衰减/8 (调用方再按上限截)."""
    from core.skill_table import SKILL_TABLE
    flags, power = SKILL_TABLE[sid][0], SKILL_TABLE[sid][1]
    if flags & F_PHYSICAL:
        amt = _div(caster.attack * (_rand(battle, 20) + 90), 100)
    else:
        amt = _div(power * (_rand(battle, 20) + 90), 100) + _div(caster.wisdom * power, 100)
    return min(DMG_CAP, max(0, _div(amt * falloff, 8)))


def mp_drain(battle, caster: "BattleUnit", e: "BattleUnit", sid: int, falloff: int = 8) -> int:
    """化精大法 0x3b / 吸精大法 0x3d (act==2 case 3): k = 威力 + (智力 - 敌智力)/2, 量 = 敌 MaxMP × k / 100;
    boss (0x20) → 化精 25 / 吸精 5; 吸精再 ≤ 施法者 MaxMP/4 且 ≤ 敌当前 MP. (exe 此处不乘衰减.)"""
    from core.skill_table import SKILL_TABLE
    k = SKILL_TABLE[sid][1] + _div(caster.wisdom - e.wisdom, 2)
    amt = max(0, _div(e.max_mp * k, 100))
    boss = bool(flags_of(e) & 0x20)
    if sid == 0x3b:
        return 25 if boss else amt
    if boss:
        amt = 5
    return max(0, min(amt, _div(caster.max_mp, 4), e.mp))


def seal_chance(caster: "BattleUnit", e: "BattleUnit", sid: int) -> int:
    """封魔 0x10 (→沉默) / 0x25 (→痲痺) 的成功率 (act==2 case 2); boss 免疫由调用方判."""
    from core.skill_table import SKILL_TABLE
    power = SKILL_TABLE[sid][1]
    c = power + _div(caster.wisdom - e.wisdom, 2) + (power + caster.luck - e.luck) + affinity(caster, e)
    return max(10, min(90, c))
