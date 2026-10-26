"""玩家普攻 (2026-10-24 逆向; 数据 core/normal_attack_data.py 由 tools/extract_normal_attacks.py 从 exe 生成).

1. **武器决定普攻**: exe 普攻表 @0x68ab90 96 项 (每角色一组 8 项 = 8 把武器). 装备 (FUN_0042a9ae 槽 2) 写
   角色表 +0x74 = 武器的普攻 idx (道具表 +0x695510); 武器不是远程 (可装备位 & 0x430 = 八戒/破无/捕山) 才同时写
   +0x78. 特例: 武器类型 0x10 (光劍) → 美娜 94 / 蒙面人 95; 类型 0x20 (莫亞刀) + 饰品 0xd5 → 0x36.
   每项: 瞄准模板 (= ACTION_TEMPLATES 同号, 0 = 面前一格), DOIT_melee seq 表 + 命中特效 + 挥击/命中音,
   flags 低位附带异常 (0x100 毒 0x200 睡 0x400 沉默 0x800 痲痺 0x1000 咀咒, 0x2000 = 五选一; 命中 23% 掷骰).
2. **贴身切近战**: 开普攻 (FUN_004a47d3) 时 FUN_004a463b 查上下左右: 有可打敌人 (无 睡/痲痺/倒地) → 用 +0x78
   (远程角色 = 91 八戒 / 92 破无 / 93 捕山 近身项, 范围只有面前 1 格), 否则 +0x74. 移动阶段预览用 +0x74.
3. **紫河变身**: 开战 FUN_004a0493(形态) 生成角色卡 13+形态: HP/MaxHP ×(f+3)/2, MP 0 (不能施法), 力量 ×(f+3)/2,
   智力 ×(4-f)/3, 敏捷 +10(f+1), 攻击 ×(f+4)·4/3, 防御 ×(f+3)/2, 幸运 ×(5-f)/3, 普攻 88+f. 形态: 无套 0 /
   變身套 0x129 → 1 / 完全變身套 0x12a → 2. 滿的保溫瓶 0x144: 开战闪 31t 变身保持整场; 否则被类型标志
   0x2000000 的敌人打中未死 → 下个行动结束闪 31t 变身 (FUN_004a0753), 轮到她时闪 31t 变回 (FUN_004a078a).
   变身后是另一张角色卡: HP 池独立 (开战时按形态缩放的值), 变回后人形 HP 照旧.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from core.normal_attack_data import ATTACK_ENTRIES, SEQ_TABLES, WEAPON_ATTACK

if TYPE_CHECKING:
    from core.battle.data import BattleUnit

CHAR_GROUP = {'孙悟空': 2, '美娜': 3, '三藏法师': 4, '猪八戒': 5, '沙悟净': 6, '蒙面人': 8, '乐神杰特': 9,
              '破无': 10, '捕山': 11, '紫河': 12}
RANGED_MELEE = {'猪八戒': 91, '破无': 92, '捕山': 93}          # 远程角色 +0x78 初值 (武器带 0x430 不覆盖)
ZIHE_FORM_ATTACK = 88                                         # 紫河形态 f 普攻 = 88 + f
ZIHE_SUITS = {0x129: 1, 0x12a: 2}
ZIHE_THERMOS = 0x144
ZIHE_TRIGGER_FLAG = 0x2000000                                 # 敌人类型标志: 打中紫河 → 变身
FLICKER_MASK = 0xdeed5221                                     # 变身闪烁: 第 i tick (0..30) 位 i → 显示新形态
FLICKER_TICKS = 31
STATUS_CHANCE = 23                                            # FUN_004a69e7(..., 0x17)
STATUS_BITS = (0x100, 0x200, 0x400, 0x800, 0x1000)
STATUS_ROUNDS = {0x100: 4, 0x200: 3, 0x400: 3, 0x800: 2, 0x1000: 3}   # FUN_004a6ac4 计数
NO_MELEE_STATUS = 0x200 | 0x800                               # FUN_004a463b: 睡/痲痺 (0x600a00 含倒地) 的敌人不算贴身


class AttackEntry(NamedTuple):
    idx: int
    group: int
    flags: int
    template: int
    fn: int
    kind: str                 # 'doit' / 'custom' (远程/紫河第三形态, 另做) / 'none'
    seq_table: int | None
    fx: str | None            # 'starburst' / 'oval' / 'claw'
    swing: tuple | None       # (挥击音, seq 信号)
    hit: tuple | None         # (命中音, 登记信号; 0 = 攻击开始)

    @property
    def ranged(self) -> bool:
        return bool(self.flags & 0x0002)


def entry(idx: int) -> AttackEntry:
    return AttackEntry(idx, *ATTACK_ENTRIES[idx])


def group_base(name: str) -> int | None:
    g = CHAR_GROUP.get(name)
    return None if g is None else (g - 2) * 8


def attack_ids(name: str, weapon: int | None, accessories=()) -> tuple[int | None, int | None]:
    """(+0x74 普攻, +0x78 贴身普攻). 无武器 → 本组第 0 项 (空手等)."""
    base = group_base(name)
    if base is None:
        return None, None
    normal = base
    melee = RANGED_MELEE.get(name, base)
    w = WEAPON_ATTACK.get(weapon) if weapon is not None else None
    if w is not None:
        atk, wtype, mask = w
        normal = atk
        if not mask & 0x430:
            melee = atk
        if wtype == 0x10 and name in ('美娜', '蒙面人'):
            normal = melee = 94 if name == '美娜' else 95
        elif wtype == 0x20 and 0xd5 in accessories:
            normal = melee = 0x36
    return normal, melee


def melee_target_adjacent(battle, u: "BattleUnit") -> bool:
    """FUN_004a463b: 上下左右有可攻击的敌人 (活着, 无睡眠/痲痺)."""
    from core.battle.status import has_status
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        o = battle.q.occupant(u.x + dx, u.y + dy)
        if o is None or not o.alive or o.is_player == u.is_player:
            continue
        if any(has_status(o, b) for b in (0x200, 0x800)):
            continue
        return True
    return False


def current_attack(battle, u: "BattleUnit", aiming: bool = True) -> int | None:
    """开普攻时用哪项: 贴身 → +0x78, 否则 +0x74. aiming=False (移动阶段预览) 恒用 +0x74."""
    if u.attack_normal is None:
        return None
    if aiming and u.attack_melee is not None and melee_target_adjacent(battle, u):
        return u.attack_melee
    return u.attack_normal


def seq_for(idx: int, facing: tuple[int, int]) -> list[tuple] | None:
    from core.attack_seq import facing_to_atk_index
    e = entry(idx)
    if e.kind != 'doit' or e.seq_table is None:
        return None
    return SEQ_TABLES[e.seq_table][facing_to_atk_index(facing)]


def roll_status(battle, attacker: "BattleUnit", victim: "BattleUnit", chance: int = STATUS_CHANCE) -> int | None:
    """FUN_004a69e7(招式 flags, 目标 flags 字, chance): 命中后 chance% 附带异常 (普攻 23, 物理技能/敌招 10).
    种类 = flags & 0x1f00 (0x2000 = 五选一); 免疫 = 目标 flags 字 **低 5 位** (exe `kind & ~victim_flags`,
    敌人 = 敌人表 flags, 如 0x2000029 免疫中毒 1 / 痲痺 8). 返回状态位或 None."""
    if not victim.alive:
        return None
    sid = getattr(attacker, 'pending_skill_id', None)
    if attacker.is_player:
        if sid is not None:
            from core.skill_table import SKILL_TABLE
            fl = SKILL_TABLE[sid][0] if sid in SKILL_TABLE else 0
        else:
            idx = getattr(attacker, 'attack_cur', None)
            if idx is None:
                return None
            fl = entry(idx).flags
    else:
        from core.battle.formulas import enemy_move
        move = getattr(attacker, 'pending_enemy_move', None) or (attacker.enemy_moves or [None])[0]
        if move is None:
            return None
        fl = enemy_move(move)['flags']
    if battle.rng.randrange(100) >= chance:
        return None
    kind = (1 << battle.rng.randrange(5)) if fl & 0x2000 else (fl & 0x1f00) >> 8
    from core.battle.formulas import flags_of
    kind &= ~flags_of(victim) & 0x1f
    if kind not in (1, 2, 4, 8, 16):
        return None
    bit = kind << 8
    from core.battle.status import apply_status
    apply_status(victim, bit, STATUS_ROUNDS[bit])
    battle._log(f"{victim.name} 中了 {bit:#x} 异常 ({STATUS_ROUNDS[bit]} 回合)")
    return bit


# ---------------- 紫河变身 ----------------
def zihe_form(accessories) -> int:
    for a in accessories:
        if a in ZIHE_SUITS:
            return ZIHE_SUITS[a]
    return 0


def zihe_beast_stats(u: "BattleUnit", f: int) -> dict:
    """FUN_004a0493: 以开战时人形属性按形态缩放 (C 整数除法)."""
    return dict(max_hp=u.max_hp * (f + 3) // 2, hp=u.hp * (f + 3) // 2, max_mp=0, mp=0,
                attack=u.attack * (f + 4) * 4 // 3, defence=u.defence * (f + 3) // 2, agile=u.agile + (f + 1) * 10,
                attack_normal=ZIHE_FORM_ATTACK + f, attack_melee=ZIHE_FORM_ATTACK + f,
                sprite_key=f"ps_CJAH{f + 1}00")


ZIHE_SWAP_FIELDS = ('max_hp', 'hp', 'max_mp', 'mp', 'attack', 'defence', 'agile', 'attack_normal', 'attack_melee',
                    'sprite_key')


def zihe_setup(u: "BattleUnit", accessories) -> None:
    """开战: 记下形态/保温瓶, 预生成兽形角色卡."""
    if u.name != '紫河':
        return
    f = zihe_form(accessories)
    u.zihe = dict(form=f, thermos=ZIHE_THERMOS in accessories, transformed=False, pending=False,
                  beast=zihe_beast_stats(u, f), human=None)


def zihe_switch(u: "BattleUnit", to_beast: bool) -> None:
    """FUN_004a0753 / 4a078a: 换角色卡 (两套 HP 池各自保留)."""
    z = getattr(u, 'zihe', None)
    if z is None or z['transformed'] == to_beast:
        return
    cur = {k: getattr(u, k) for k in ZIHE_SWAP_FIELDS}
    other = z['beast'] if to_beast else z['human']
    if to_beast:
        z['human'] = cur
    else:
        z['beast'] = cur
    for k, v in other.items():
        setattr(u, k, v)
    z['transformed'] = to_beast
    u.flicker = dict(t=0, other=cur['sprite_key'], to=u.sprite_key)


def flicker_sprite(u: "BattleUnit") -> str | None:
    """闪烁期间这一 tick 显示的 sprite (位为 1 → 新形态)."""
    fl = getattr(u, 'flicker', None)
    if not fl:
        return None
    return fl['to'] if (FLICKER_MASK >> min(fl['t'], 31)) & 1 else fl['other']
