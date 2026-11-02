"""战斗中使用道具 (exe BTLdoPlayer case 3: 按道具表 0x695514 + id*0x4c 取控制器, 2026-11-01 逆向 + 原版实录).

流程 (与技能同一入口): 十字菜单 ← 道具 → 选道具 → 瞄准 (动作模板 64: 自己 + 面前一格, 光标默认自己) → Enter.
确认时 (FUN_004a6efe act==3) 结算数值 (core.battle.energy.battle_item, 工作 HP/MP 当场改), 演出由控制器跑完后结束回合.

控制器 (每个道具一个, 这里实现已录像的两类):
  HP 回复药 299 / 300 / 301 (FUN_004ede17 / 4ee28f / 4ee83d):
    case 0: 使用者挂 seq 670798[dir] (ps+2: 上 0,1 / 下 4,5 / 左 9,8 / 右 12,13 各 6t → impact), 清 0x10000 (停在末帧).
    -100: 每个目标挂 seq 670818 (ps+2 帧 6,7 各 6t → -500), 清 0x10000; FUN_004ed8b0 在目标头顶生成道具图标
          (fm 233, 帧 = 0 / 1 / 2): z+64, 每 t 升 1px 32t, 再闪烁 32t → 回调生成闪光粒子; 播 0x115. → 0x14.
    闪光 (FUN_004edc86 / 4ee0fe / 4ee576): 8 / 16 / 16+8 个绕目标的光点 (FUN_004ed96c, 同乐神杰特 強力慢曲但不撒粒子):
          起始角随机, 每个相隔 1/8 · 1/16 圈; seq 6561a4 从随机前 4 帧起; z 每 t +1, 角速 +0x20 至 0x1000;
          z > 80 → 换 seq 6720cc (同样随机起帧), 下落 1.5px/t, 角速随机减至 ≥0x100, 半径每 t +1/+0.75;
          落地自毁; 最后一个 (0x40000) 换段时播 0xca、落地给控制器发 -200. 生成时播 0xc9.
    -200: 目标回待机 (|= 0x10000) + 回复白字 (FUN_004d074e). 0x14: 图标/数字计数归零 → 自毁 (回合结束).
  复活 308 強力針灸 (FUN_004f1685):
    case 0: 同上挂使用者 seq. -100: 目标挂 seq 6708cc (ps+4 帧 13 = 躺地), FUN_004f161e 在目标 (+12, +12, z+60) 生成复活图标
          (seq 670860: fm 233 帧 9, 两次 -200 + 0x10f 音), 图标 seq 播完后每 t 升 1px 闪烁 64t → -300 自毁.
    -200: 目标挂 seq 6708d8 (躺地抖动). -300: 目标挂 seq 670904 (爬起 ps+4 13,12,5,4,3 各 8t) → 0x14.
    0x14: 爬起播完 → 挂 6709b8[dir] (转身) → 0x1e. 0x1e: 播完 → 目标回待机, 控制器自毁.
其它道具 (MP 药 / 仙桃 / 解毒等, 各有自己的控制器, 尚未录像): 先用回复药那套演出 (图标帧 0, 8 个光点), 数字照实际回复量.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.anim_engine.bytecode import tuple_to_bytecode
from core.jet_skills import (FP, MAG_SEQ, SPARKLE_FALL_SEQ, REVIVE_UP_SEQ, REVIVE_TURN_SEQS, _attach_unit_seq, _dir,
                             _fx, _orbit, _pos, _rand, _set_z, _sfx)

if TYPE_CHECKING:
    from core.anim_engine.engine import Engine
    from core.anim_engine.entity import Entity

ITEM_TEMPLATE = 64                  # BattleRules.PatternId(item) / ACTION_TEMPLATES[64]: 瞄准 = 自己 + 面前一格, 作用 = 光标一格
REVIVE_ITEMS = (0x134,)             # 強力針灸 (说明「回復無法戰鬥的同伴」); 0x132 天桃 另有控制器, 未录
ICON = 233                          # 道具图标 fm (帧 = 道具图标号)

USER_SEQS = [[('idle', 2, a, 6), ('idle', 2, b, 6), ('impact',), ('exit',)] for a, b in ((0, 1), (4, 5), (9, 8), (12, 13))]  # 670798
TARGET_SEQ = [('idle', 2, 6, 6), ('idle', 2, 7, 6), ('jump', -500), ('exit',)]                                             # 670818
LIE_SEQ = [('idle', 4, 13, 0), ('exit',)]                                                                                  # 6708cc
SHAKE_SEQ = [('idle', 4, 13, 0), ('move', 0, 6, 2), ('move', 0, 2, 2), ('move', 0, -8, 0), ('exit',)]                       # 6708d8
REVIVE_ICON_SEQ = [('fm', ICON, 9, 0), ('move', 0, 0, 32), ('move', -6, 6, 1), ('sound', 271, 0x0411), ('jump', -200),               # 670860
                   ('move', -6, 6, 8), ('move', 12, -12, 2), ('move', 0, 0, 32), ('move', -6, 6, 1), ('sound', 271, 0x0411),
                   ('jump', -200), ('move', -6, 6, 8), ('move', 12, -12, 2), ('exit',)]

SFX_USE = 0x115
SFX_SPARKLE = 0xc9
SFX_SPARKLE_FALL = 0xca
SIG_SETTLE = -200
SIG_RISE = -300
END_WAIT = 17

# 回复药: 道具 → (图标帧, 光点组 [(个数, rx, ry, 相邻角距)])
HEAL_STYLE = {
    0x12b: (0, ((8, 0x20, 0x18, 0x2000),)),                                # 恢復藥 FUN_004edc86
    0x12c: (1, ((16, 0x20, 0x18, 0x1000),)),                               # 良藥 FUN_004ee0fe
    0x12d: (2, ((16, 0x20, 0x18, 0x1000), (8, 0x18, 0x12, 0x2000))),       # 優藥 FUN_004ee576
}


def _start_at_random_op(battle, e: "Entity", seq) -> None:
    """exe: 挂 seq 后 seq 偏移 += 操作长度 × rand%4 (从前 4 帧中随机一帧开始)."""
    op = len(tuple_to_bytecode([seq[0]]))
    battle.engine.attach_seq(e, tuple_to_bytecode(seq))
    e.offset += op * (_rand(battle) % 4)


def _hold(battle, unit, seq) -> None:
    """挂 seq 并停在末帧 (清 0x10000: 不回待机)."""
    _attach_unit_seq(battle, unit, seq)
    unit.cast_hold = True


def _seq_done(unit) -> bool:
    e = unit.entity
    return e is None or not (e.flags & 0x20000)


# ---------------- 入口 ----------------
def start(battle, user, item_id: int, targets: list, values: dict) -> None:
    """确认后: 建控制器, 使用者挂起手 seq. values: id(目标) → battle_item 结果 (已结算)."""
    coord = battle.engine.spawn(think_fn=_coord_think)
    coord.flags = 0x800 | 0x10000
    coord.user_data.update(kind='item_coord', projectile=True, item=True, battle=battle, user=user, item_id=item_id,
                           targets=targets, values=values, state=10, live=0, digits=0,
                           revive=item_id in REVIVE_ITEMS)
    coord.user_data['on_caster_signal'] = lambda sig: _on_signal(coord, sig, None)
    user.pending_caster_coord = coord
    if coord.user_data['revive']:
        for t in targets:                      # 确认时已复活 (工作 HP), 画面仍躺着直到爬起
            _hold(battle, t, LIE_SEQ)
    _hold(battle, user, USER_SEQS[_dir(user)])


def _on_signal(coord, sig: int, source) -> None:
    ud = coord.user_data
    battle = ud['battle']
    if ud['revive']:
        _revive_signal(coord, sig)
        return
    if sig == -100:
        frame, groups = HEAL_STYLE.get(ud['item_id'], HEAL_STYLE[0x12b])
        for t in ud['targets']:
            # exe 怪癖 (同 jet_skills._hold_pose, 实录自用只停在帧 6): -100 由使用者自己的 seq 发出, 给自己换 seq 后
            # jump op 又把偏移 +4 → 只播首帧就结束
            _hold(battle, t, [TARGET_SEQ[0], ('exit',)] if t is ud['user'] else TARGET_SEQ)
            _spawn_icon(battle, coord, t, frame, groups)
            ud['live'] += 1
        _sfx(battle, SFX_USE)
        ud['state'] = 0x14
    elif sig == SIG_SETTLE and source is not None:
        _settle(coord, source)


def _settle(coord, t) -> None:
    """-200: 目标回待机 + 回复白字 (FUN_004d074e)."""
    from core.battle.combat import push_damage_event
    from core.battle.data import DamageEvent
    ud = coord.user_data
    t.cast_hold = False
    res = ud['values'].get(id(t), {})
    if res.get('hp'):
        t.shown_hp_override = None
        push_damage_event(ud['battle'], t, DamageEvent(res['hp'], t.hp, t.x, t.y, heal=True))
    ud['live'] -= 1


def _coord_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'item' not in ud:
        return
    battle, user = ud['battle'], ud['user']
    if ud['revive']:
        if ud['state'] == 0x14 and all(_seq_done(t) for t in ud['targets']):
            for t in ud['targets']:
                _attach_unit_seq(battle, t, REVIVE_TURN_SEQS[_dir(t)])
            ud['state'] = 0x1e
        elif ud['state'] == 0x1e and all(_seq_done(t) for t in ud['targets']):
            for t in ud['targets']:
                t.cast_hold = False
            _finish(e, eng)
        return
    if ud['state'] == 0x14 and ud['live'] <= 0 and getattr(battle, 'float_pending', 0) <= 0:
        _finish(e, eng)


def _finish(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    battle, user = ud['battle'], ud['user']
    eng.destroy(e)
    user.pending_caster_coord = None
    battle.post_attack_anim(user)
    battle._spawn_wait(END_WAIT)        # 原版实录: 控制器结束后再过 17t 才轮到下一单位 (回复 +270→+287, 复活 +223→+240)


# ---------------- 回复药: 头顶图标 + 光点 ----------------
def _spawn_icon(battle, coord, t, frame: int, groups) -> None:
    """FUN_004ed8b0: 目标 (x, y+1, z+64) 道具图标, 弹簧 z 轴 vz = 1px/t (az 0 → 匀速升)."""
    x, y = _pos(t)
    _fx(battle, _icon_think, x, y + FP, 64 * FP, None, atlas=ICON, frame=frame, icon=True, battle=battle, coord=coord,
        target=t, groups=groups, age=0)


def _icon_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004ed820: 升 32t; 再闪烁 (0x40 每 t 翻) 升 32t → 回调生成光点, 自毁."""
    ud = e.user_data
    if 'icon' not in ud:
        return
    tick = ud['age']                    # exe +0x144: think 之后才加 1 (首次 think 为 0)
    ud['age'] += 1
    if tick > 0x20:
        e.flags ^= 0x40
    _set_z(e, ud['ez'] + FP)
    if tick == 0x40:
        _spawn_sparkles(ud['battle'], ud['coord'], ud['target'], ud['groups'])
        eng.destroy(e)


def _spawn_sparkles(battle, coord, t, groups) -> None:
    """FUN_004edc86 / 4ee0fe / 4ee576: 绕目标的光点, 最后一个负责 -200."""
    cx, cy = _pos(t)
    phi = ((_rand(battle) & 0x3ff) << 16) >> 10
    last = None
    for count, rx, ry, step in groups:
        for _ in range(count):
            e = _fx(battle, _sparkle_think, cx, cy, 0, None, atlas=MAG_SEQ[0][1], frame=MAG_SEQ[0][2], sparkle=True,
                    battle=battle, coord=coord, target=t, cx=cx, cy=cy, rx=rx, ry=ry, phi=phi & 0xffff, spd=0x400,
                    state=0, lead=False)
            _orbit(e)
            _start_at_random_op(battle, e, MAG_SEQ)
            phi = (phi + step) & 0xffff
            last = e
    last.user_data['lead'] = True
    _sfx(battle, SFX_SPARKLE)


def _sparkle_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004ed96c."""
    ud = e.user_data
    if 'sparkle' not in ud:
        return
    battle = ud['battle']
    if ud['state'] == 0:
        _set_z(e, ud['ez'] + FP)
        ud['spd'] = min(ud['spd'] + 0x20, 0x1000)
        ud['phi'] = (ud['phi'] + ud['spd']) & 0xffff
        _orbit(e)
        if ud['ez'] > 0x500000:
            ud['r16x'], ud['r16y'] = ud['rx'] << 16, ud['ry'] << 16
            _start_at_random_op(battle, e, SPARKLE_FALL_SEQ)
            ud['state'] = 10
            if ud['lead']:
                _sfx(battle, SFX_SPARKLE_FALL)
    else:
        _set_z(e, ud['ez'] - 0x18000)
        if _rand(battle) & 1:
            ud['spd'] = max(ud['spd'] - 0x80, 0x100)
        ud['phi'] = (ud['phi'] + ud['spd']) & 0xffff
        ud['r16x'] += FP
        ud['r16y'] += 0xc000
        ud['rx'], ud['ry'] = ud['r16x'] >> 16, ud['r16y'] >> 16
        _orbit(e)
        if ud['ez'] < 1:
            if ud['lead']:
                _on_signal(ud['coord'], SIG_SETTLE, ud['target'])
            eng.destroy(e)


# ---------------- 复活 ----------------
def _revive_signal(coord, sig: int) -> None:
    ud = coord.user_data
    battle = ud['battle']
    if sig == -100:
        for t in ud['targets']:
            _hold(battle, t, LIE_SEQ)
            x, y = _pos(t)
            icon = _fx(battle, _revive_icon_think, x + 12 * FP, y + 12 * FP, 60 * FP, REVIVE_ICON_SEQ, ricon=True,
                       battle=battle, coord=coord, state=0, age=0)
            icon.user_data['on_signal'] = lambda _e, s: _revive_signal(coord, s)
    elif sig == SIG_SETTLE:
        for t in ud['targets']:
            _hold(battle, t, SHAKE_SEQ)
    elif sig == SIG_RISE:
        for t in ud['targets']:
            _hold(battle, t, REVIVE_UP_SEQ)
        ud['state'] = 0x14


def _revive_icon_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004f1570: seq 播完后每 t 升 1px 并闪烁 64t → -300, 自毁."""
    ud = e.user_data
    if 'ricon' not in ud:
        return
    if ud['state'] == 0:
        if not (e.flags & 0x20000):
            ud['state'] = 10
        return
    ud['age'] += 1
    _set_z(e, ud['ez'] + FP)
    e.flags ^= 0x40
    if ud['age'] >= 0x40:
        _revive_signal(ud['coord'], SIG_RISE)
        eng.destroy(e)
