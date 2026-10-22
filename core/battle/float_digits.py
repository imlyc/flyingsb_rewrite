"""伤害/回复飘字 = 原版数字实体 (2026-10-22 反编译 reverse_engineering/float_decomp.txt + icedragon_decomp.txt, 实录校准).

伤害 FUN_004d05d8(敌, 值): 生成 spawner 实体 (FUN_004d0488): 字符串 = "%d" (值<0 → 0x3a,0x3b,0x3c,0x3c = MISS),
  x0 = 敌格中心 - 位数×5px, 每 tick 计数, **奇数 tick 出一位** (slot 214 sbtlfont, 帧 = 字符-0x23 → 红行 13..22 / MISS 23,24,25,25),
  位 i 在 x0 + i×10px, y = 敌 y + 400px, z = 428 (屏幕 = y - z ⇒ 敌 y - 28), flags 0x41 (FUN_004c3211 z 轴无阻尼弹簧, 目标 z 0,
  加速度 1.5px/t² ⇒ 重力), vz = +16px/t; 末位带 0x40000 + 受击单位指针, 出完 spawner 自毁.
数字 FUN_004d0330: state 0 上抛 (vz 16, 重力 1.5) 落回 z<424 → z=424, vz=8 → state 1 再弹一次 → z<424 → state 2
  (末位此刻给受击单位发 -20 = dispatcher 的飘字计数 -1) 停 32 tick → state 3 每 tick XOR 可见 32 tick → 消失. 共 ≈ 20+10+32+32.
回复 FUN_004d074e(单位, 值): 全部位**一起**生成 (FUN_004d06b0), 帧 = 字符-0x30 (白行 0..9 / MISS 10,11,12,12), y = 单位 y + 404,
  z = 488, vz = -0.5px/t **无加速度** (+0x180 未设) → z<460 (56t) 进 state 1 (末位发 -20) → 每 tick 闪, z<448 (再 24t) 消失.
我们: z 取负为高 (渲染 sy = y + z - ay), 内部按 exe 数值算 ez 再换算. battle.float_pending = exe dispatcher +0x3e 计数
(每发 +1, 末位到 state 2 时 -1); battle.float_events 收 ('flash', unit) (首位进闪烁, 场景用来触发死亡动画) / ('settled', unit).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.sprites.base import TILE_W, TILE_H

if TYPE_CHECKING:
    from core.anim_engine.engine import Engine
    from core.anim_engine.entity import Entity

FP = 1 << 16
DIGIT_ATLAS = 214                     # fm 全局槽 214 = sbtlfont
DIGIT_STRIDE_PX = 10
DMG_CHAR_BASE = 0x23                  # 伤害: 帧 = 字符码 - 0x23 (红行)
HEAL_CHAR_BASE = 0x30                 # 回复: 帧 = 字符码 - 0x30 (白行)
MISS_CHARS = (0x3a, 0x3b, 0x3c, 0x3c)

DMG_Y_OFF = 400 * FP                  # +0x1900000
DMG_Z0 = 0x1ac0000                    # 428
DMG_Z_FLOOR = 0x1a80000               # 424: state 0/1 落回判据 (z <) 与落定后的 z (实录 z 范围 424..505)
DMG_VZ0 = 0x100000                    # 16 px/t
DMG_VZ1 = 0x80000                     # 8 px/t
DMG_GRAVITY = 0x18000                 # 1.5 px/t² (+0x180, 弹簧目标 z=0 ⇒ 恒向下)
DMG_HOLD_TICKS = 0x20
DMG_BLINK_TICKS = 0x20
DMG_FLASH_STATE = 3

HEAL_Y_OFF = 0x1940000                # 404
HEAL_Z0 = 0x1e80000                   # 488
HEAL_VZ = -0x8000                     # -0.5 px/t
HEAL_Z_SETTLE = 0x1cc0000             # 460
HEAL_Z_END = 0x1c00000                # 448
HEAL_FLASH_STATE = 1


def _chars(value: int | None, base: int) -> list[int]:
    if value is None:
        return [c - base for c in MISS_CHARS]
    return [ord(c) - base for c in str(int(value))]


def _notify(battle, kind: str, unit) -> None:
    evs = getattr(battle, 'float_events', None)
    if evs is not None:
        evs.append((kind, unit))


def _settle(battle, unit, counts: bool) -> None:
    if counts:
        battle.float_pending = max(0, getattr(battle, 'float_pending', 0) - 1)
    _notify(battle, 'settled', unit)


def _set_z(e: "Entity", y_off: int) -> None:
    e.z = -(e.user_data['ez'] - y_off)


def _digit_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004d0330."""
    ud = e.user_data
    if 'digit' not in ud:
        return
    battle = ud['battle']
    st = e.state_code
    if st in (0, 1):
        ud['vz'] -= DMG_GRAVITY                       # FUN_004c3211 flag 0x41: z ≥ 目标 0 ⇒ vz -= 加速度
        ud['ez'] += ud['vz']
        if ud['ez'] < DMG_Z_FLOOR:
            ud['ez'] = DMG_Z_FLOOR
            if st == 0:
                ud['vz'] = DMG_VZ1
                e.state_code = 1
            else:
                e.state_code = 2
                ud['until'] = ud['tick'] + DMG_HOLD_TICKS
                if ud.get('last'):
                    _settle(battle, ud['unit'], ud['counts'])
        _set_z(e, DMG_Y_OFF)
    elif st == 2:
        if ud['tick'] == ud['until']:
            e.state_code = 3
            ud['until'] = ud['tick'] + DMG_BLINK_TICKS
            if ud.get('first'):
                _notify(battle, 'flash', ud['unit'])
    elif st == 3:
        e.flags ^= 0x40
        if ud['tick'] == ud['until']:
            eng.destroy(e)
            return
    ud['tick'] += 1


def _spawn_digit(battle, frame: int, x: int, y: int, unit, first: bool, last: bool, counts: bool) -> "Entity":
    e = battle.engine.spawn(think_fn=_digit_think)
    e.atlas_slot, e.frame_idx = DIGIT_ATLAS, frame
    e.flags |= 0x40
    e.x, e.y = x, y
    e.vx = e.vy = e.vz = 0
    e.user_data.update(kind='hit_effect', draw_order=100, digit=True, float=True,
                       battle=battle, unit=unit, first=first, last=last, counts=counts, tick=0,
                       ez=DMG_Z0, vz=DMG_VZ0, settle_state=2)
    _digit_think(e, battle.engine)        # exe 池序: 数字下标 > spawner, 出生当 tick 就 think 一次 (实录首帧 z=442, state 0 共 20 帧)
    return e


def _spawner_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004d0488: 每奇数 tick 出一位, 出完自毁."""
    ud = e.user_data
    if 'spawner' not in ud:
        return
    ud['tick'] += 1
    if ud['tick'] & 1:
        i = ud['idx']
        chars = ud['chars']
        _spawn_digit(ud['battle'], chars[i], ud['x0'] + i * DIGIT_STRIDE_PX * FP, ud['y'], ud['unit'],
                     first=(i == 0), last=(i == len(chars) - 1), counts=ud['counts'])
        ud['idx'] = i + 1
        if ud['idx'] >= len(chars):
            eng.destroy(e)


def _heal_digit_think(e: "Entity", eng: "Engine") -> None:
    """FUN_004d06b0: 匀速下落; z<460 进 state 1 (末位 -20); state 1 每 tick 闪, z<448 消失."""
    ud = e.user_data
    if 'heal_digit' not in ud:
        return
    battle = ud['battle']
    ud['ez'] += HEAL_VZ
    _set_z(e, HEAL_Y_OFF)
    if e.state_code == 0:
        if ud['ez'] < HEAL_Z_SETTLE:
            e.state_code = 1
            if ud.get('last'):
                _settle(battle, ud['unit'], ud['counts'])
            if ud.get('first'):
                _notify(battle, 'flash', ud['unit'])
    else:
        e.flags ^= 0x40
        if ud['ez'] < HEAL_Z_END:
            eng.destroy(e)
            return
    ud['tick'] += 1


def _unit_px(unit) -> tuple[int, int]:
    return (unit.x * TILE_W + TILE_W // 2) * FP, (unit.y * TILE_H + TILE_H // 2) * FP


def spawn_float(battle, unit, value: int | None, heal: bool = False, counts: bool = True) -> None:
    """value=None ⇒ MISS. heal ⇒ 白字一起下落 (回复/MP 回复), 否则红字逐位弹跳 (伤害/MISS/MP 吸取).
    counts: 计入 float_pending (exe +0x3e 每次 -200 只 +1; 吸精 -200 同时出敌红字 + 施法者白字, 白字的 -20 不被等 → counts=False)."""
    eng = getattr(battle, 'engine', None)
    if eng is None or unit is None:
        return
    base = HEAL_CHAR_BASE if heal else DMG_CHAR_BASE
    chars = _chars(value, base)
    cx, cy = _unit_px(unit)
    x0 = cx - len(chars) * 5 * FP
    if counts:
        battle.float_pending = getattr(battle, 'float_pending', 0) + 1
    if heal:
        for i, fr in enumerate(chars):
            e = eng.spawn(think_fn=_heal_digit_think)
            e.atlas_slot, e.frame_idx = DIGIT_ATLAS, fr
            e.flags |= 0x40
            e.x, e.y = x0 + i * DIGIT_STRIDE_PX * FP, cy
            e.vx = e.vy = e.vz = 0
            e.user_data.update(kind='hit_effect', draw_order=100, heal_digit=True, float=True,
                               battle=battle, unit=unit, first=(i == 0), last=(i == len(chars) - 1),
                               counts=counts, tick=0, ez=HEAL_Z0, settle_state=1)
            _heal_digit_think(e, eng)     # 出生当 tick 先走一步 (实录首帧 z=487, state 0 共 56 帧)
        return
    s = eng.spawn(think_fn=_spawner_think)
    s.flags = 0x800 | 0x10000                         # 不渲染
    s.user_data.update(kind='float_spawner', float=True, spawner=True, battle=battle,
                       unit=unit, chars=chars, idx=0, tick=0, x0=x0, y=cy, counts=counts)


def floats_animating(battle) -> bool:
    """还有飘字没"落定" (= exe +0x3e 计数 > 0: 末位数字未进停留/闪烁态). 回合切换/输入门控用."""
    return getattr(battle, 'float_pending', 0) > 0


def floats_flashing_done(battle) -> bool:
    """所有飘字都已进闪烁 (或消失)."""
    eng = getattr(battle, 'engine', None)
    if eng is None:
        return True
    for e in eng.entities:
        if not (e.flags & 0x800) or not e.user_data.get('float'):
            continue
        if e.user_data.get('spawner'):
            return False
        if e.state_code < (DMG_FLASH_STATE if e.user_data.get('digit') else HEAL_FLASH_STATE):
            return False
    return True
