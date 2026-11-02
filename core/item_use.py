"""战斗中使用道具 (exe BTLdoPlayer case 3: 按道具表 0x695514 + id*0x4c 取控制器, 2026-11-01 逆向 + 原版实录).

流程 (与技能同一入口): 十字菜单 ← 道具 → 选道具 → 瞄准 (动作模板按道具, item_template; 光标默认同技能) → Enter.
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
2026-11-02 按 exe 逆向补齐其余道具 (未经原版实录校准):
  回复药模板 (同 299 的控制器, 只换图标帧 / 光点 / -100 音 / 白字): MP 药 302 / 303 / 304 (FUN_004eefcf / 4ef447 / 4ef9f5, 光点
    FUN_004eee3e / 4ef2b6 / 4ef72e + think 4eeb24 = 回复药光点但升段用 6720cc、落段用 6561a4, 0xf2, MP 白字);
    仙桃 305 / 天桃 306 (FUN_004f01cd / 4f0b02, 光点 FUN_004f0011 / 4f07e9 + think 4efcdc / 4f04b4 = 每组每 4 个之一上升时撒粒子
    FUN_004d4819, 0x149, HP 白字; 天桃对倒地者先复活, -200 恢复待机 think);
    肌肉恢復膏 313 / 興奮劑 314 / 夢夢777 316 / 萬靈丹 317 (FUN_004f2509 / 4f27ad / 4f2a61 / 4f2f7d; -100 音 0x14a / 0x115):
    光环 FUN_004f2379 (0x112) / 4f2ded (0x116): 8 个 ds_mag03 绕目标 z96 (角速 +0x20 至 0x1000), age%8==0 且 <64 时甩出一粒
    羽毛 (FUN_004f2131 / 4f206f: 定角, 半径每 t +角速·32/+角速·24 (16.16), z -1, 64t); age>96 → 末个 -200 (回待机, 无白字).
  解毒劑 310 (FUN_004f1981): -100 目标 670818 + 图标帧 11 (FUN_004f18d1 / 4f1839, 同回复药图标), 0x14b; 图标 64t 后 0xca +
    美娜 療毒 控制体 (FUN_004f9b3e / 4f9ade, 24t 每 t 一粒闪光, 0xca) → -200 目标回待机.
  鬧鐘 311 (FUN_004f1d63): -100 目标挂 6709e0 (ps+3 16/12 循环), 目标 z+80 闹钟 (FUN_004f1cfe / 4f1bd9, seq 6709c8, 0x110):
    64t 每 t 随机抖 (绘制偏移 x -8..7, y 0..7); 之后停帧 -200 (目标回待机, 停 0x110), 每 t 升 1px 闪烁 64t → -300 结束.
  法式親吻 312 (FUN_004f1f82): -100 目标 670a14 (ps+3 帧 16 40t), (x, y+1, z+50) 唇印 (FUN_004f1f21 / 4f1e66, seq 6709f8 含 0x124):
    seq 完后每 t 升 1px 闪烁 64t → -300 (目标回待机, 结束).
  魔法的白粉 307 (FUN_004f12b1): -100 使用者头顶图标帧 8 (FUN_004f11f7 / 4f1167, 0x113) 64t → -150: 全部目标挂 670854 (ps+3 帧 12)
    + 白粉 (FUN_004f0f29(5) / 4f0df6, 0x114): 使用者格为中心菱形半径 5 每格 3 粒, 从使用者 z80 匀速 6t 飞到格内随机点 z96,
    再每 t 落 0.5px 并随机抖 ±1px 96t; 末粒 -200 → 全部目标回待机 + HP 白字.
  煙霧彈 309 / 雙光 315: 控制器一上来就自毁; 战斗结算无效果 → 用不出去.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.anim_engine.bytecode import tuple_to_bytecode
from core.jet_skills import (FP, MAG_SEQ, SPARKLE_FALL_SEQ, REVIVE_UP_SEQ, REVIVE_TURN_SEQS, _attach_unit_seq, _dir,
                             _fx, _orbit, _pos, _rand, _set_z, _sfx)

if TYPE_CHECKING:
    from core.anim_engine.engine import Engine
    from core.anim_engine.entity import Entity

ITEM_TEMPLATE = 64                  # ACTION_TEMPLATES[64]: 瞄准 = 自己 + 面前一格, 作用 = 光标一格
# exe FUN_004a4f94 菜单结果 5: 0x133 魔法的白粉 → 0x1a (光标只在自己, 作用 = 周围一大片); 0x134 強力針灸 / 0x137 鬧鐘 / 0x139 肌肉恢復膏
# → 0 (只有面前一格); 其余 0x40
ITEM_TEMPLATES = {0x133: 0x1A, 0x134: 0, 0x137: 0, 0x139: 0}


def item_template(item: int) -> int:
    """道具的瞄准动作模板 (exe FUN_004a4f94 case 5)."""
    return ITEM_TEMPLATES.get(item, ITEM_TEMPLATE)

REVIVE_ITEMS = (0x134,)             # 強力針灸 的复活演出 (天桃也复活, 但走回复药模板)
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

G8 = ((8, 0x20, 0x18, 0x2000),)
G16 = ((16, 0x20, 0x18, 0x1000),)
G24 = ((16, 0x20, 0x18, 0x1000), (8, 0x18, 0x12, 0x2000))
# 回复药模板: 道具 → (图标帧, 光点类, 光点组 [(个数, rx, ry, 相邻角距)] / 光环音, -100 音, 白字 'hp'/'mp'/None)
#   光点类 heal = FUN_004ed96c (升 6561a4 → 落 6720cc), mp = FUN_004eeb24 (升 6720cc → 落 6561a4), peach = heal + 撒粒子,
#   ring = FUN_004f2230 (z96 光环 + 甩羽毛)
POTIONS = {
    0x12b: (0, 'heal', G8, 0x115, 'hp'),         # 恢復藥 FUN_004edc86
    0x12c: (1, 'heal', G16, 0x115, 'hp'),        # 良藥 FUN_004ee0fe
    0x12d: (2, 'heal', G24, 0x115, 'hp'),        # 優藥 FUN_004ee576
    0x12e: (3, 'mp', G8, 0xf2, 'mp'),            # 藥草 FUN_004eee3e
    0x12f: (4, 'mp', G16, 0xf2, 'mp'),           # 良藥 (MP) FUN_004ef2b6
    0x130: (5, 'mp', G24, 0xf2, 'mp'),           # 優藥 (MP) FUN_004ef72e
    0x131: (6, 'peach', G16, 0x149, 'hp'),       # 仙桃 FUN_004f0011
    0x132: (7, 'peach', G24, 0x149, 'hp'),       # 天桃 FUN_004f07e9
    0x139: (0x10, 'ring', 0x112, 0x14a, None),   # 肌肉恢復膏 FUN_004f2379
    0x13a: (0x11, 'ring', 0x112, 0x115, None),   # 興奮劑
    0x13c: (0x12, 'ring', 0x112, 0x115, None),   # 夢夢777
    0x13d: (0x13, 'ring', 0x116, 0x115, None),   # 萬靈丹 FUN_004f2ded
}
ANTIDOTE, ALARM, KISS, POWDER = 0x136, 0x137, 0x138, 0x133
ANTIDOTE_ICON, POWDER_ICON = 0xb, 8
POWDER_TARGET_SEQ = [('idle', 3, 12, 1), ('exit',)]                                       # 670854
ALARM_TARGET_SEQ = [('idle', 3, 16, 1), ('idle', 3, 12, 1), ('loop',)]                    # 6709e0
ALARM_SEQ = [('fm', ICON, 12, 1), ('fm', ICON, 13, 1), ('loop',)]                         # 6709c8
KISS_TARGET_SEQ = [('idle', 3, 16, 40), ('exit',)]                                        # 670a14
# 自用怪癖 (实录 312 自用): -100 由使用者自己的 seq 发出, 换上 670a14 后 jump op 的偏移推进跳过了它的 EXIT,
# 40t 后接着执行紧随其后的 .data (0x670a20 起另一段攻击 seq: 上移 12 / 槽 0 帧 0 ×5 每帧 3t 各下移 1 / 再上移 12 → -1000, -100
# (= 第二个唇印, 落在上移 20px 处), -105, 帧 1..3, 下移 24, -110, EXIT); 首个唇印 -300 时控制器结束并让使用者回待机.
KISS_SELF_SEQ = ([('idle', 3, 16, 40), ('move', 0, -12, 0, 1)] + [('fm', 0, 0, 3), ('move', 0, 1, 0, 0)] * 4 +
                 [('fm', 0, 0, 3), ('move', 0, -12, 0, 0), ('jump', -1000), ('impact',), ('jump', -105), ('fm', 0, 1, 3),
                  ('fm', 0, 2, 3), ('fm', 0, 3, 5), ('move', 0, 24, 0, 0), ('fm', 0, 0, 0), ('end',), ('exit',)])
KISS_SEQ = [('sound', 292, 0x0411), ('fm', ICON, 15, 40), ('fm', ICON, 14, 1), ('exit',)]  # 6709f8
POWDER_SEQ = [('fm', 247, f, 2) for f in (36, 31, 38, 28)] + [('loop',)]                  # 670828
SIG_POWDER = -150


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
    for t in targets:                          # 确认时已复活 (工作 HP), 画面仍躺着直到 -100 (天桃) / 爬起 (強力針灸)
        if values.get(id(t), {}).get('revived'):
            _hold(battle, t, LIE_SEQ)
    _hold(battle, user, USER_SEQS[_dir(user)])


def _on_signal(coord, sig: int, source) -> None:
    ud = coord.user_data
    if 'item' not in ud:                       # 控制器已结束 (鬧鐘 / 法式親吻 -300 即自毁; 之后的信号原版也没人收)
        return
    battle = ud['battle']
    item = ud['item_id']
    if ud['revive']:
        _revive_signal(coord, sig)
        return
    if item in (ALARM, KISS):
        _status_signal(coord, sig)
        return
    if item == POWDER:
        _powder_signal(coord, sig)
        return
    if sig == -100:
        frame, kind, groups, sfx, _ = POTIONS.get(item, POTIONS[0x12b]) if item != ANTIDOTE else (ANTIDOTE_ICON, 'cure', None, 0x14b, None)
        for t in ud['targets']:
            _hold_receive(battle, ud, t)
            _spawn_icon(battle, coord, t, frame, kind, groups)
            ud['live'] += 1
        _sfx(battle, sfx)
        ud['state'] = 0x14
    elif sig == SIG_SETTLE and source is not None:
        _settle(coord, source)


def _hold_receive(battle, ud, t) -> None:
    """-100: 目标挂接受姿 670818. exe 怪癖 (同 jet_skills._hold_pose, 实录自用只停在帧 6): -100 由使用者自己的 seq 发出,
    给自己换 seq 后 jump op 又把偏移 +4 → 只播首帧就结束."""
    _hold(battle, t, [TARGET_SEQ[0], ('exit',)] if t is ud['user'] else TARGET_SEQ)


def _settle(coord, t) -> None:
    """-200: 目标回待机 + 回复白字 (FUN_004d074e: HP 药 0x7d80c0 / MP 药 0x7d80c4; 光环类无白字)."""
    ud = coord.user_data
    t.cast_hold = False
    digit = POTIONS.get(ud['item_id'], (None,) * 5)[4]
    if digit:
        _digit(ud['battle'], t, ud['values'].get(id(t), {}), digit)
    ud['live'] -= 1


def _digit(battle, t, res: dict, kind: str) -> None:
    from core.battle.combat import push_damage_event
    from core.battle.data import DamageEvent
    if kind == 'hp':
        t.shown_hp_override = None
        push_damage_event(battle, t, DamageEvent(res.get('hp', 0), t.hp, t.x, t.y, heal=True))
    else:
        push_damage_event(battle, t, DamageEvent(res.get('mp', 0), t.mp, t.x, t.y, heal=True, mp=True))


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
def _spawn_icon(battle, coord, t, frame: int, kind: str, groups) -> None:
    """FUN_004ed8b0 / 4f18d1 / 4f11f7: 目标 (x, y+1, z+64) 道具图标, 弹簧 z 轴 vz = 1px/t (az 0 → 匀速升)."""
    x, y = _pos(t)
    _fx(battle, _icon_think, x, y + FP, 64 * FP, None, atlas=ICON, frame=frame, icon=True, battle=battle, coord=coord,
        target=t, ikind=kind, groups=groups, age=0)


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
        battle, coord, t, kind = ud['battle'], ud['coord'], ud['target'], ud['ikind']
        if kind == 'ring':
            _spawn_ring(battle, coord, t, ud['groups'])
        elif kind == 'cure':                         # 解毒劑 FUN_004f1839: 0xca + 美娜 療毒 控制体 (FUN_004f9b3e, 24t)
            _sfx(battle, SFX_SPARKLE_FALL)
            _spawn_cure_ctrl(battle, coord, t)
            coord.user_data['live'] -= 1
        elif kind == 'powder':                       # 魔法的白粉 FUN_004f1167: -150 → 白粉
            _powder_signal(coord, SIG_POWDER)
        else:
            _spawn_sparkles(battle, coord, t, kind, ud['groups'])
        eng.destroy(e)


def _spawn_sparkles(battle, coord, t, kind: str, groups) -> None:
    """FUN_004edc86 / 4ee0fe / 4ee576 (heal), 4eee3e / 4ef2b6 / 4ef72e (mp), 4f0011 / 4f07e9 (peach): 绕目标的光点,
    最后一个负责 -200. peach 每组第 0, 4, 8.. 个上升时撒粒子."""
    from core.jet_skills import _spawn_rise
    cx, cy = _pos(t)
    phi = ((_rand(battle) & 0x3ff) << 16) >> 10
    rise, fall = (SPARKLE_FALL_SEQ, MAG_SEQ) if kind == 'mp' else (MAG_SEQ, SPARKLE_FALL_SEQ)
    last = None
    born = []
    for count, rx, ry, step in groups:
        for k in range(count):
            e = _fx(battle, _sparkle_think, cx, cy, 0, None, atlas=rise[0][1], frame=rise[0][2], sparkle=True,
                    battle=battle, coord=coord, target=t, cx=cx, cy=cy, rx=rx, ry=ry, phi=phi & 0xffff, spd=0x400,
                    state=0, lead=False, fall=fall, emit=kind == 'peach' and k % 4 == 0, rise_fx=_spawn_rise)
            _orbit(e)
            _start_at_random_op(battle, e, rise)
            phi = (phi + step) & 0xffff
            last = e
            born.append(e)
    last.user_data['lead'] = True
    _sfx(battle, SFX_SPARKLE)
    for e in born:                       # 池序在图标之后 → 出生当 tick 就 think (实录 299 / 302: 首帧 z=1, 活 134t)
        _sparkle_think(e, battle.engine)


def _sparkle_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004ed96c / 4eeb24 / 4efcdc / 4f04b4 (同一套运动, 只差两段 seq 与是否撒粒子)."""
    ud = e.user_data
    if 'sparkle' not in ud:
        return
    battle = ud['battle']
    if ud['state'] == 0:
        _set_z(e, ud['ez'] + FP)
        ud['spd'] = min(ud['spd'] + 0x20, 0x1000)
        ud['phi'] = (ud['phi'] + ud['spd']) & 0xffff
        _orbit(e)
        if ud['emit']:
            ud['rise_fx'](battle, e)
        if ud['ez'] > 0x500000:
            ud['r16x'], ud['r16y'] = ud['rx'] << 16, ud['ry'] << 16
            _start_at_random_op(battle, e, ud['fall'])
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


# ---------------- 光环 (肌肉恢復膏 / 興奮劑 / 夢夢777 / 萬靈丹) ----------------
def _spawn_ring(battle, coord, t, sfx: int) -> None:
    """FUN_004f2379 / 4f2ded: 8 个 ds_mag03 绕目标 z96, 末个负责 -200."""
    cx, cy = _pos(t)
    phi = ((_rand(battle) & 0x3ff) << 16) >> 10
    last = None
    born = []
    for _ in range(8):
        e = _fx(battle, _ring_think, cx, cy, 0x600000, None, atlas=MAG_SEQ[0][1], frame=MAG_SEQ[0][2], ring=True,
                battle=battle, coord=coord, target=t, cx=cx, cy=cy, rx=0x20, ry=0x18, phi=phi & 0xffff, spd=0x400,
                age=0, lead=False)
        _orbit(e)
        _start_at_random_op(battle, e, MAG_SEQ)
        phi = (phi + 0x2000) & 0xffff
        last = e
        born.append(e)
    last.user_data['lead'] = True
    _sfx(battle, sfx)
    for e in born:                       # 同回复药光点: 出生当 tick 就 think
        _ring_think(e, battle.engine)


def _ring_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004f2230: 角速 +0x20 至 0x1000; age%8==0 且 <64 甩一粒羽毛; age>96 → 末个 -200, 灭."""
    ud = e.user_data
    if 'ring' not in ud:
        return
    battle = ud['battle']
    tick = ud['age']
    ud['age'] += 1
    ud['spd'] = min(ud['spd'] + 0x20, 0x1000)
    ud['phi'] = (ud['phi'] + ud['spd']) & 0xffff
    _orbit(e)
    if tick % 8 == 0 and tick < 0x40:
        _spawn_flake(battle, ud['target'], ud['phi'], ud['spd'])
    if tick > 0x60:
        if ud['lead']:
            _on_signal(ud['coord'], SIG_SETTLE, ud['target'])
        eng.destroy(e)


def _spawn_flake(battle, t, phi: int, spd: int) -> None:
    """FUN_004f2131: 目标处 z96 定角羽毛 (seq 656abc[rand&3]), 半径 32/24 起每 t +角速·32 / +角速·24 (16.16)."""
    from core.jet_skills import FEATHER_SEQS
    cx, cy = _pos(t)
    e = _fx(battle, _flake_think, cx, cy, 0x600000, None, flake=True, cx=cx, cy=cy, rx=0x18, ry=0, phi=phi,
            r16x=0x200000, r16y=0x180000, vrx=spd << 5, vry=spd * 0x18, age=0)
    _orbit(e)
    battle.engine.attach_seq(e, tuple_to_bytecode(FEATHER_SEQS[_rand(battle) & 3]))
    _flake_think(e, battle.engine)       # 池序在光环之后 → 出生当 tick 就 think


def _flake_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004f206f: z -1; 半径 = 16.16 累加; 64t 后灭."""
    ud = e.user_data
    if 'flake' not in ud:
        return
    tick = ud['age']
    ud['age'] += 1
    _set_z(e, ud['ez'] - FP)
    ud['rx'], ud['ry'] = ud['r16x'] >> 16, ud['r16y'] >> 16
    ud['r16x'] += ud['vrx']
    ud['r16y'] += ud['vry']
    _orbit(e)
    if tick > 0x40:
        eng.destroy(e)


# ---------------- 解毒劑: 美娜 療毒 控制体 ----------------
def _spawn_cure_ctrl(battle, coord, t) -> None:
    """FUN_004f9b3e(目标, 24): core.mina_skills 療毒 控制体 (24t 每 t 一粒闪光; 第 24t 目标回待机), 0xca."""
    from core.mina_skills import _cure_ctrl_think
    e = battle.engine.spawn(think_fn=_cure_ctrl_think)
    e.flags = 0x800 | 0x10000
    e.user_data.update(kind='item_cure', projectile=True, cure_ctrl=True, battle=battle, coord=coord, target=t, age=0,
                       n=0x18)
    coord.user_data['live'] += 1
    _sfx(battle, SFX_SPARKLE_FALL)
    _cure_ctrl_think(e, battle.engine)   # 池序在图标之后 → 出生当 tick 就 think (实录 310: 控制体活 24t)


# ---------------- 鬧鐘 / 法式親吻 ----------------
def _status_signal(coord, sig: int) -> None:
    """FUN_004f1d63 (鬧鐘) / 4f1f82 (法式親吻): 只对首个目标."""
    from core.mina_skills import _unit_z
    ud = coord.user_data
    battle = ud['battle']
    t = ud['targets'][0]
    if sig == -100:
        x, y = _pos(t)
        z = _unit_z(t)
        if ud['item_id'] == ALARM:
            _hold(battle, t, ALARM_TARGET_SEQ)
            _fx(battle, _alarm_think, x, y, z + 0x500000, ALARM_SEQ, alarm=True, battle=battle, coord=coord, target=t,
                state=0, age=0, end=-1, jx=0, jy=0)
            _sfx(battle, 0x110)
        else:
            _hold(battle, t, KISS_SELF_SEQ if t is ud['user'] else KISS_TARGET_SEQ)
            _fx(battle, _kiss_think, x, y + FP, z + 0x320000, KISS_SEQ, kiss=True, battle=battle, coord=coord,
                target=t, state=0, age=0, end=-1)
        ud['live'] += 1
        ud['state'] = 0x14
    elif sig == SIG_SETTLE:                        # 鬧鐘: 目标回待机 (法式親吻的 -200 控制器不收)
        if ud['item_id'] == ALARM:
            _to_idle(t)
    elif sig == SIG_RISE:                          # 控制器自毁 (FUN_004c4a6f), 法式親吻 先让目标回待机
        if ud['item_id'] == KISS:
            _to_idle(t)
        _finish(coord, battle.engine)


def _to_idle(t) -> None:
    """目标 |= 0x10000 且清 0x20000 (停掉 seq, 回待机; 待机 think 让实体回到格上)."""
    t.cast_hold = False
    if t.entity is not None:
        t.entity.flags &= ~0x20000
        t.entity.x = t.entity.y = 0


def _alarm_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004f1bd9: 64t 每 t 随机抖 (绘制偏移 +0x20 / +0x24); 之后停帧, -200, 停 0x110; 每 t 升 1px 闪烁 64t → -300."""
    from core.jet_skills import _sfx_stop
    ud = e.user_data
    if 'alarm' not in ud:
        return
    battle = ud['battle']
    tick = ud['age']
    ud['age'] += 1
    if ud['state'] == 0:
        ud['jx'] = (_rand(battle) & 15) * FP - 0x80000
        ud['jy'] = (_rand(battle) & 7) << 16
        if tick == 0x40:
            ud['jx'] = ud['jy'] = 0
            ud['end'] = tick + 0x40
            e.flags &= ~0x20000
            _on_signal(ud['coord'], SIG_SETTLE, None)
            ud['state'] = 10
            _sfx_stop(battle, 0x110)
    else:
        _set_z(e, ud['ez'] + FP)
        e.flags ^= 0x40
        if tick == ud['end']:
            _on_signal(ud['coord'], SIG_RISE, None)
            eng.destroy(e)


def _kiss_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004f1e66: seq 播完 → 每 t 升 1px 闪烁 64t → -300."""
    ud = e.user_data
    if 'kiss' not in ud:
        return
    tick = ud['age']
    ud['age'] += 1
    if ud['state'] == 0:
        if not (e.flags & 0x20000):
            ud['end'] = tick + 0x40
            _on_signal(ud['coord'], SIG_SETTLE, None)
            ud['state'] = 10
    else:
        _set_z(e, ud['ez'] + FP)
        e.flags ^= 0x40
        if tick == ud['end']:
            _on_signal(ud['coord'], SIG_RISE, None)
            eng.destroy(e)


# ---------------- 魔法的白粉 ----------------
def _powder_signal(coord, sig: int) -> None:
    """FUN_004f12b1: -100 使用者头顶图标 (0x113); -150 全部目标挂 670854 + 白粉; -200 全部目标回待机 + HP 白字."""
    ud = coord.user_data
    battle, user = ud['battle'], ud['user']
    if sig == -100:
        _spawn_icon(battle, coord, user, POWDER_ICON, 'powder', None)
        _sfx(battle, 0x113)
        ud['live'] += 1
        ud['state'] = 0x14
    elif sig == SIG_POWDER:
        for t in ud['targets']:
            _hold(battle, t, POWDER_TARGET_SEQ)
        _spawn_powder(battle, coord, user, 5)
    elif sig == SIG_SETTLE:
        for t in ud['targets']:
            t.cast_hold = False
            _digit(battle, t, ud['values'].get(id(t), {}), 'hp')
        ud['live'] -= 1


def _spawn_powder(battle, coord, user, radius: int) -> None:
    """FUN_004f0f29: 使用者格为中心菱形 (|dx|+|dy| <= r) 每格 3 粒, 从使用者 z80 匀速 6t 飞到格内随机点 z96; 0x114."""
    from core.sprites.base import TILE_W, TILE_H
    ux, uy = _pos(user)
    last = None
    born = []
    for dy in range(-radius, radius + 1):
        span = radius - abs(dy)
        for dx in range(-span, span + 1):
            for _ in range(3):
                tx = (user.x + dx) * TILE_W * FP + (_rand(battle) & 0x3f) * FP
                ty = (user.y + dy) * TILE_H * FP + (_rand(battle) % 0x30) * FP
                tz = 0x600000
                z0 = 0x500000
                e = _fx(battle, _powder_think, ux, uy, z0, None, powder=True, battle=battle, coord=coord, state=0, age=0,
                        end=-1, lead=False, tx=tx, ty=ty, tz=tz, m=0x71,
                        vx=_tdiv(tx - ux, 6), vy=_tdiv(ty - uy, 6), vz=_tdiv(tz - z0, 6), ax=0, ay=0, az=0)
                _start_at_random_op(battle, e, POWDER_SEQ)
                last = e
                born.append(e)
    last.user_data['lead'] = True
    _sfx(battle, 0x114)
    for e in born:                       # 池序在图标之后 → 出生当 tick 就 think (实录 307: 首帧 z=82, 活 102t)
        _powder_think(e, battle.engine)


def _tdiv(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def _powder_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004f0df6: 匀速飞到落点 (FUN_004cdbc2, 越过即钳); 到齐 → z 每 t -0.5 (mode 0x41) 并随机抖 ±1px, 96t 后灭 (末粒 -200)."""
    from core.mina_skills import _cdbc2
    ud = e.user_data
    if 'powder' not in ud:
        return
    battle = ud['battle']
    tick = ud['age']
    ud['age'] += 1
    if ud['state'] == 0:
        if _cdbc2(e):
            ud['end'] = tick + 0x60
            ud['state'] = 10
    else:
        e.x += -FP + _tdiv((_rand(battle) % 2000) << 16, 1000)
        e.y += -FP + _tdiv((_rand(battle) % 2000) << 16, 1000)
        _set_z(e, ud['ez'] - 0x8000)
        if tick == ud['end']:
            if ud['lead']:
                _on_signal(ud['coord'], SIG_SETTLE, None)
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
