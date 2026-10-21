"""紫河 9 技能演出 (skill_id 0x39..0x41), 2026-10-20 按 exe 逆向 (Ghidra, dispatcher 0x50cd9a..0x50f9c1).

共同点: 施法 seq 表 @0x679948 (4 方向, mode1 槽 106 → 紫河 g0 atlas cjah0_g0=34, 2 帧 5+12 tick, 然后 IMPACT);
IMPACT (-100) 时 dispatcher 对每个 victim spawn 演出 entity, 演出里 -250 = 受击 (reaction + 标准命中特效 + 音),
-200 = 结算 (伤害 / MP). 我们: IMPACT → SKILL_IMPACT_SPAWN → 这里 spawn 一个 coordinator (不渲染) + 各 victim
的演出 entity; 全部演完 coordinator 发 SIG_IMPACT_2 (→ tactics 结算 _pending_damage_range 里所有敌人) + SIG_END.
结算是一次性的 (exe 每敌各自 -200 时刻略有先后, 这里统一在最后), MP 类技能走 combat 的 SKILL_MP_DRAIN 分支.

逐技能 (exe 真值):
  0x39 流星冰鑽  FUN_004d7c8e/4d7c45/4d7b6b/4d788d/4d77e6: 每敌 8 颗 ds_ice(232) 冰钻从施法者身前 (随机 ±8/±2px,
       高 80px) 飞向敌人 (高 48px), 间隔 (8-n)*4 tick 递减 (4,32,56,76,92,104,112,116); 竖向 24px/t 横向 32px/t;
       seq 帧 3,2,1,0,5,6,7,4,8 (上下) / ...,4,11 (左右) 各 1t 后飞; 每颗 spawn 播 206, 命中播 189+受击+特效; 末颗结算.
  0x3a 冰柱擎天  FUN_0050ced7/50ce70/50cdaf: 每敌头上冰柱 ejaha01(284) 帧 6-11 (1t); 每 20t 受击 (189);
       t=80 (首敌播 174) 结算 + 6 碎冰 (FUN_004d6dc3) 消失. 施放播 238.
  0x3b 化精大法  FUN_0050d6f6/50d480/50d3ef: 每敌一颗 ejaha02(285) 0/1 闪烁光球, 在施法者头上 (高 92px) 悬 60t,
       再以 32px/t (横) / 24px/t (竖) 飞向敌人 (高 32px); 到达: MP 清零结算 + 受击 (特效×2 + 301). 施放播 300.
  0x3c 冰河醉雨  FUN_004d72b1/4d728e/4d71ce: 每敌 100t 内每 2t 一颗小冰锥 (FUN_004d6f6a, =青龙), 每 20t 受击;
       t=128 大冰锥 (FUN_004d70fc) 落地结算. (青龙神兽的雨, 无神兽)
  0x3d 吸精大法  FUN_0050e529/50e375/50e256/50e12a/50de1d: 每敌一颗光球在敌人头上 (高 92px), 前 40t 每 2t 从周围
       (±32..63, ±24..47 px, 高 0-63) 冒一粒 e00(247) 光粒 (4 套三帧循环之一) 每 tick 升 2px 到 92px 再以 8/6px 飞向球; t>86 播 293, 球以 8px/t 飞向施法者; 到达后 32 粒光粒 (高 92px, 每 tick 降 1px) 在施法者
       周围 60t 后以 8/6px 聚拢, 再等 64t: MP 吸取结算 + 敌受击 (197) + 施法者头上飘回 MP 数. 施放播 294.
  0x3e 化精為氣  FUN_0050ee16/50eb21/50eab0/50ea66: 自身: ejaha05(286) 帧 7,6,0-5,7 (1t) + 302; 状态位 0x80000
       (下次受击伤害转 MP, 一次性, 见 core.battle.status.ST_HUAJING).
  0x3f 冰柱冰身  FUN_0050efc2/50ef5b/50ee2b: 每敌 ejaha01 帧 0-5 冰柱困住; t>80 (首敌 174) 柱隐 + 受击 + 6 碎冰;
       t>100 受击 + 结算. 施放播 238.
  0x40 修羅勾魂  FUN_0050f5c0/50f50e/50f4bc/50f458/50f3fd: 首敌头顶 500px 高落下一块 ejaha07(287) 帧 18 大冰
       (48px/t), 播 214; 落地播 291 + 原地播 ejaha07 帧 0-17 (3t); 播完全敌受击 + 结算.
  0x41 冰龍升天  FUN_0050f9c1/50f959/50f8fe: 施法者脚下 ejaha08(288) 0-15 (1t, tick1 播 257) 冰龙; 播完每敌一根
       大冰锥 (FUN_004d70fc, 174) 落地结算.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.anim_engine.bytecode import tuple_to_bytecode
from core.anim_engine.entity import SIG_IMPACT_2, SIG_END

if TYPE_CHECKING:
    from core.anim_engine.engine import Engine
    from core.anim_engine.entity import Entity

FP = 65536
JAH_CAST_ATLAS = 34                 # cjah0_g0 (exe mode1 槽 106 → 紫河形态 0 的 g0)
DS_ICE = 232
EJAHA01, EJAHA02, EJAHA05, EJAHA07, EJAHA08 = 284, 285, 286, 287, 288
E00 = 247                           # 光粒 (吸精)

SFX_ICE_DRILL = 206                 # 0xce 流星冰钻每颗
SFX_HIT = 189                       # 0xbd 命中
SFX_ICE_BIG = 174                   # 0xae 大冰锥/冰柱碎
SFX_PILLAR_CAST = 238               # 0xee 冰柱擎天/冰柱冰身 施放
SFX_HUAJING_CAST = 300              # 0x12c 化精大法 施放
SFX_HUAJING_HIT = 301               # 0x12d 化精大法 命中
SFX_XIJING_CAST = 294               # 0x126 吸精 施放
SFX_XIJING_DEPART = 293             # 0x125 吸精 光球起飞
SFX_XIJING_HIT = 197                # 0xc5 吸精 结算
SFX_HUAQI = 302                     # 0x12e 化精為氣
SFX_XIULUO_SPAWN = 214              # 0xd6 修羅 大冰 spawn
SFX_XIULUO_LAND = 291               # 0x123 修羅 落地

# 施法 seq (exe @0x679948, 4 方向): 紫河 g0 帧 (2,3)/(6,7)/(10,11)/(14,15), 5+12 tick, IMPACT, EXIT
SKILL_JAH_CAST: list[list[tuple]] = [
    [('fm', JAH_CAST_ATLAS, b, 5), ('fm', JAH_CAST_ATLAS, b + 1, 12), ('impact',), ('exit',)]
    for b in (2, 6, 10, 14)
]
# ds_ice 冰钻 seq (exe @0x656c18 上下 / @0x656bbc 左右)
DRILL_SEQ_UD = [('fm', DS_ICE, f, 1) for f in (3, 2, 1, 0, 5, 6, 7, 4, 8)] + [('exit',)]
DRILL_SEQ_LR = [('fm', DS_ICE, f, 1) for f in (3, 2, 1, 0, 5, 6, 7, 4, 11)] + [('exit',)]
PILLAR_UP_SEQ = [('fm', EJAHA01, f, 1) for f in range(6, 12)] + [('exit',)]      # @0x679958
PILLAR_TRAP_SEQ = [('fm', EJAHA01, f, 1) for f in range(0, 6)] + [('exit',)]     # @0x679a24
HUAQI_SEQ = [('fm', EJAHA05, f, 1) for f in (7, 6, 0, 1, 2, 3, 4, 5, 7)] + [('exit',)]   # @0x6799c8
XIULUO_LAND_SEQ = [('fm', EJAHA07, f, 3) for f in range(18)] + [('exit',)]       # @0x679a64
DRAGON_SEQ = ([('fm', EJAHA08, 0, 1), ('sound', 257, 0x0411)]
              + [('fm', EJAHA08, f, 1) for f in range(1, 16)] + [('exit',)])     # @0x679b1c

DRILL_COUNT = 8
DRILL_SCHEDULE = (4, 32, 56, 76, 92, 104, 112, 116)   # FUN_004d7b6b: 首 4t, 之后 +(8-n)*4
DRILL_START_Z = 80                  # 0x4fffff ≈ 80px
DRILL_TARGET_Z = 48                 # 0x300000
DRILL_SPEED_V, DRILL_SPEED_H = 24, 32
PILLAR_UP_HIT_INTERVAL = 20
PILLAR_UP_END = 80
PILLAR_TRAP_HIDE = 81               # >0x50
PILLAR_TRAP_END = 101               # >100
ORB_Z = 92                          # 0x5c0000
ORB_HOLD = 60                       # 化精 球悬停 0x3c
ORB_SPEED_H, ORB_SPEED_V = 32, 24
ORB_TARGET_Z = 32
XIJING_PARTICLE_TICKS = 40
XIJING_DEPART = 87                  # >0x56
XIJING_SPEED_H, XIJING_SPEED_V = 8, 6
XIJING_BURST_N = 32
XIJING_BURST_FALL = 60              # 光粒下落 0x3b 后聚拢 (每 tick -1px)
XIJING_PARTICLE_RISE = 2            # 敌侧光粒每 tick 升 2px (0x20000) 直到 92px
PARTICLE_FRAME_SETS = ((30, 31, 32), (33, 34, 35), (36, 37, 38), (39, 40, 41))   # e00, PTR_DAT_00656abc[rand&3] 循环段
XIJING_SETTLE = 64                  # 0x40
RAIN_TICKS = 100
RAIN_INTERVAL = 2
RAIN_REACT_INTERVAL = 20
RAIN_BIG_AT = 128
XIULUO_HEIGHT = 500                 # 0x1f40000
XIULUO_VZ = 48
CONE_LAND_TICKS = 12                # 大冰锥 500px / 48px/t ≈ 11t, 多等 1


# ------------------------------------------------------------------ helpers
def _sfx(battle, sid: int, solo: bool = False) -> None:
    battle.engine._emit('sound_play_solo' if solo else 'sound_play', None, sid)


def _ground(unit) -> tuple[int, int]:
    from core.sprites.base import TILE_W, TILE_H
    return ((unit.x * TILE_W + TILE_W // 2) * FP, (unit.y * TILE_H + TILE_H // 2) * FP)


def _victims(battle, attacker) -> list:
    out = []
    tiles = getattr(battle, '_pending_damage_range', None)
    if tiles:
        for (x, y) in tiles:
            t = battle.q.occupant(x, y)
            if t is not None and t.alive and t.is_player != attacker.is_player:
                out.append(t)
    else:
        t = attacker.pending_attack_target
        if t is not None and t.alive:
            out.append(t)
    return out


def _hit(battle, caster, victim, fx: bool = True, sound: int | None = None) -> None:
    """exe -250: 受击反应 (范围技不转向) + 标准 2 命中特效 + 音."""
    from core.battle import combat
    if not victim.alive:
        return
    combat.set_reaction(victim, "hit", None)
    if fx:
        combat._emit_hit_effect(battle, caster, victim)
    if sound is not None:
        _sfx(battle, sound)


HUAJING_HIT_FX2 = [('fm', 215, 8, 4), ('fm', 215, 9, 4), ('exit',)]   # @0x655ad0 (et00 帧 8-9), 化精 -250 的第 2 特效


def _hit_huajing(battle, caster, victim) -> None:
    """化精大法 -250 (FUN_0050d6f6): 受击 + 方向 starburst (655c10[dir]) + **et00 8-9** (&DAT_00655ad0, 代替普通的 655b18 红刺) + 301."""
    from core.battle import combat
    from core.hit_effect_seq import HIT_EFFECT_JITTER_PX, HIT_EFFECT_Y_BASELINE_PX
    from core.sprites.base import TILE_W, TILE_H
    if not victim.alive:
        return
    combat.set_reaction(victim, "hit", None)
    spec = combat.hit_effect_specs(victim, caster.name)[0]
    cx = victim.x * TILE_W + TILE_W // 2
    cy = victim.y * TILE_H + TILE_H // 2
    ox = battle.rng.randint(-HIT_EFFECT_JITTER_PX, HIT_EFFECT_JITTER_PX)
    oy = battle.rng.randint(-HIT_EFFECT_JITTER_PX, HIT_EFFECT_JITTER_PX) - HIT_EFFECT_Y_BASELINE_PX
    combat._spawn_effect_entity(battle, cx + ox, cy + oy, spec)
    combat._spawn_skill_extra_effect(battle, cx, cy - HIT_EFFECT_Y_BASELINE_PX, HUAJING_HIT_FX2)
    _sfx(battle, SFX_HUAJING_HIT)


def _shatter(battle, x, y) -> None:
    from core.son_transform import _spawn_ice_shatter
    _spawn_ice_shatter(battle, x, y, big=True)         # 6 块 (exe 调 6 次 FUN_004d6dc3)


def _spawn_coord(battle, caster, victims, think_fn) -> "Entity":
    e = battle.engine.spawn(think_fn=think_fn)
    e.flags = 0x800 | 0x10000                            # alive + think, 不渲染
    e.user_data.update(kind='jah_coord', projectile=True, battle=battle, caster=caster,
                       victims=list(victims), tick=0, pending=len(victims), done=False)
    return e


def _coord_finish(e: "Entity", eng: "Engine") -> None:
    if e.user_data.get('done'):
        return
    e.user_data['done'] = True
    eng._signal(e, SIG_IMPACT_2)
    eng._signal(e, SIG_END)
    eng.destroy(e)


def _fx_entity(battle, think_fn, x, y, z_px: int = 0, atlas: int | None = None, frame: int = 0) -> "Entity":
    e = battle.engine.spawn(think_fn=think_fn)
    e.x, e.y, e.z = x, y, -(z_px * FP)
    e.vx = e.vy = e.vz = 0
    if atlas is not None:
        e.atlas_slot, e.frame_idx = atlas, frame
    e.flags |= 0x40
    e.user_data.update(kind='hit_effect', projectile=True, battle=battle, tick=0)
    return e


def _aim_axis(e: "Entity", tx, ty, tz_px: int, axis: str, speed: int) -> None:
    """exe 投射物速度设定 (FUN_004d788d / 50d480 / 50e375): **主轴定速** ±speed px/tick (符号朝目标),
    其它轴 = 位移 / (主轴位移 / speed) (整除, 至少 1), 即按主轴到达 tick 数等分. 到达判定见 _fly."""
    dx, dy, dz = tx - e.x, ty - e.y, -(tz_px * FP) - e.z
    major = dx if axis == 'x' else dy
    steps = max(1, abs(major) // (speed * FP))
    sign = 1 if major >= 0 else -1
    e.vx, e.vy, e.vz = dx // steps, dy // steps, dz // steps
    if axis == 'x':
        e.vx = sign * speed * FP
    else:
        e.vy = sign * speed * FP
    e.user_data.update(fly_axis=axis, fly_target=(tx, ty, -(tz_px * FP)), fly_steps=int(steps))


def _aim(e: "Entity", tx, ty, tz_px: int, speed_h: int, speed_v: int) -> None:
    """主轴 = |dx|>|dy| ? x : y (exe FUN_0050d480/50e375/50df5a 用 abs 比较), 速度 speed_h / speed_v."""
    dx, dy = tx - e.x, ty - e.y
    if abs(dx) >= abs(dy):
        _aim_axis(e, tx, ty, tz_px, 'x', speed_h)
    else:
        _aim_axis(e, tx, ty, tz_px, 'y', speed_v)


def _fly(e: "Entity") -> bool:
    """按 _aim 的速度走一步 (exe FUN_004cdbc2: 每轴独立走, 越过目标即钳到目标). 主轴到达返回 True."""
    ud = e.user_data
    tx, ty, tz = ud['fly_target']
    e.x += e.vx
    e.y += e.vy
    e.z += e.vz
    ud['fly_steps'] -= 1
    if ud['fly_axis'] == 'x':
        done = (e.vx >= 0 and e.x >= tx) or (e.vx < 0 and e.x <= tx)
    else:
        done = (e.vy >= 0 and e.y >= ty) or (e.vy < 0 and e.y <= ty)
    if done or ud['fly_steps'] <= 0:
        e.x, e.y, e.z = tx, ty, tz
        return True
    return False


# ------------------------------------------------------------------ 0x39 流星冰鑽
def _drill_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'drill' not in ud:
        return
    if e.state_code == 0:
        if not e.is_playing():
            e.state_code = 10
    elif e.state_code == 10 and _fly(e):
        battle, caster, v = ud['battle'], ud['caster'], ud['victim']
        _hit(battle, caster, v, sound=SFX_HIT)
        if ud['last']:
            ud['coord'].user_data['pending'] -= 1
        eng.destroy(e)


def _spawn_drill(battle, caster, victim, coord, last: bool) -> None:
    from core.attack_seq import facing_to_atk_index
    rng = battle.rng
    cx, cy = _ground(caster)
    e = _fx_entity(battle, _drill_think,
                   cx + ((rng.randint(0, 15) - 8) * FP), cy + ((rng.randint(0, 7) - 2) * FP),
                   DRILL_START_Z, DS_ICE, 3)
    d = facing_to_atk_index(caster.facing)
    vx, vy = _ground(victim)
    _aim_axis(e, vx, vy, DRILL_TARGET_Z, 'y' if d < 2 else 'x', DRILL_SPEED_V if d < 2 else DRILL_SPEED_H)
    e.user_data.update(drill=True, caster=caster, victim=victim, coord=coord, last=last)
    battle.engine.attach_seq(e, tuple_to_bytecode(DRILL_SEQ_UD if d < 2 else DRILL_SEQ_LR))
    _sfx(battle, SFX_ICE_DRILL)


def _drill_coord_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'victims' not in ud:
        return
    t = ud['tick']
    ud['tick'] += 1
    if t in DRILL_SCHEDULE:
        n = DRILL_SCHEDULE.index(t)
        for v in ud['victims']:
            if v.alive:
                _spawn_drill(ud['battle'], ud['caster'], v, e, last=(n == DRILL_COUNT - 1))
            elif n == DRILL_COUNT - 1:
                ud['pending'] -= 1
    if t > DRILL_SCHEDULE[-1] and ud['pending'] <= 0:
        _coord_finish(e, eng)


def spawn_ice_drill(battle, attacker, target_tile) -> "Entity":
    return _spawn_coord(battle, attacker, _victims(battle, attacker), _drill_coord_think)


# ------------------------------------------------------------------ 0x3a 冰柱擎天
def _pillar_up_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'pillar' not in ud:
        return
    battle, caster, v = ud['battle'], ud['caster'], ud['victim']
    t = ud['tick']
    ud['tick'] += 1
    if t % PILLAR_UP_HIT_INTERVAL == 0 and t <= PILLAR_UP_END:
        _hit(battle, caster, v, sound=SFX_HIT)          # t=0,20,40,60,80 (80 与结算同 tick)
    if t == PILLAR_UP_END:
        if ud['first']:
            _sfx(battle, SFX_ICE_BIG)
        _shatter(battle, e.x, e.y)
        ud['coord'].user_data['pending'] -= 1
        eng.destroy(e)


def _pillar_coord_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'victims' not in ud:
        return
    ud['tick'] += 1
    if ud['pending'] <= 0 and ud['tick'] > 2:
        _coord_finish(e, eng)


def spawn_ice_pillar_up(battle, attacker, target_tile) -> "Entity":
    victims = _victims(battle, attacker)
    coord = _spawn_coord(battle, attacker, victims, _pillar_coord_think)
    for i, v in enumerate(victims):
        x, y = _ground(v)
        p = _fx_entity(battle, _pillar_up_think, x, y + FP, 0, EJAHA01, 6)
        p.user_data.update(pillar=True, caster=attacker, victim=v, coord=coord, first=(i == 0))
        battle.engine.attach_seq(p, tuple_to_bytecode(PILLAR_UP_SEQ))
    _sfx(battle, SFX_PILLAR_CAST)
    return coord


# ------------------------------------------------------------------ 0x3b 化精大法
def _orb_flicker(e: "Entity") -> None:
    e.frame_idx = e.user_data['tick'] & 1            # ejaha02 帧 0/1 循环 (exe seq loop)


def _huajing_orb_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'orb' not in ud:
        return
    _orb_flicker(e)
    ud['tick'] += 1
    if e.state_code == 0:
        if ud['tick'] >= ORB_HOLD:
            vx, vy = _ground(ud['victim'])
            _aim(e, vx, vy + FP, ORB_TARGET_Z, ORB_SPEED_H, ORB_SPEED_V)
            e.state_code = 10
    elif e.state_code == 10 and _fly(e):
        _hit_huajing(ud['battle'], ud['caster'], ud['victim'])
        ud['coord'].user_data['pending'] -= 1
        eng.destroy(e)


def spawn_huajing(battle, attacker, target_tile) -> "Entity":
    victims = _victims(battle, attacker)
    coord = _spawn_coord(battle, attacker, victims, _pillar_coord_think)
    cx, cy = _ground(attacker)
    for v in victims:
        o = _fx_entity(battle, _huajing_orb_think, cx, cy + FP, ORB_Z, EJAHA02, 0)
        o.user_data.update(orb=True, caster=attacker, victim=v, coord=coord)
    _sfx(battle, SFX_HUAJING_CAST)
    return coord


# ------------------------------------------------------------------ 0x3c 冰河醉雨
def _rain_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'rain' not in ud:
        return
    from core.son_transform import (_spawn_ice_cone, EICE_CONE_SMALL, EICE_CONE_BIG,
                                    ICE_SHARD_HEIGHT, ICE_CONE_HEIGHT)
    battle, caster, v = ud['battle'], ud['caster'], ud['victim']
    t = ud['tick']
    ud['tick'] += 1
    rng = battle.rng
    vx, vy = _ground(v)
    if t < RAIN_TICKS and t % RAIN_INTERVAL == 0:
        _spawn_ice_cone(battle, vx + (rng.randint(-28, 28) * FP), vy + (rng.randint(-8, 16) * FP),
                        ICE_SHARD_HEIGHT + rng.randint(0, 30), EICE_CONE_SMALL[rng.randint(0, 3)], big=False)
    if t < RAIN_TICKS and t % RAIN_REACT_INTERVAL == 0:
        _hit(battle, caster, v)
    if t == RAIN_BIG_AT:
        _spawn_ice_cone(battle, vx, vy + (4 * FP), ICE_CONE_HEIGHT, EICE_CONE_BIG[rng.randint(0, 2)], big=True)
    if t >= RAIN_BIG_AT + CONE_LAND_TICKS:
        _hit(battle, caster, v, fx=False)
        ud['coord'].user_data['pending'] -= 1
        eng.destroy(e)


def spawn_ice_rain(battle, attacker, target_tile) -> "Entity":
    victims = _victims(battle, attacker)
    coord = _spawn_coord(battle, attacker, victims, _pillar_coord_think)
    for v in victims:
        r = battle.engine.spawn(think_fn=_rain_think)
        r.flags = 0x800 | 0x10000
        r.user_data.update(kind='jah_rain', projectile=True, rain=True, battle=battle,
                           caster=attacker, victim=v, coord=coord, tick=0)
    return coord


# ------------------------------------------------------------------ 0x3d 吸精大法
def _particle_think(e: "Entity", eng: "Engine") -> None:
    """光粒 (exe FUN_0050df5a 敌侧 / FUN_0050dc59 施法者侧): 先竖向漂 (升到 92px / 降 60 tick),
    再按主轴 8px·副轴 6px 飞向目标 (x,y), z 不变; 到达即灭. 帧: e00 三帧 1 tick 循环."""
    ud = e.user_data
    if 'particle' not in ud:
        return
    ud['tick'] += 1
    e.frame_idx = ud['frames'][ud['tick'] % 3]
    if e.state_code == 0:
        if ud['rise']:
            e.z -= XIJING_PARTICLE_RISE * FP
            ready = e.z <= -(ORB_Z * FP)
            if ready:
                e.z = -(ORB_Z * FP)
        else:
            e.z += FP                                   # 降 1px/tick
            ready = ud['tick'] > XIJING_BURST_FALL - 1
        if ready:
            tx, ty = ud['target']
            _aim(e, tx, ty, -e.z // FP, XIJING_SPEED_H, XIJING_SPEED_V)
            e.state_code = 10
    elif e.state_code == 10 and _fly(e):
        eng.destroy(e)


def _spawn_particle(battle, cx, cy, target_xy, rise: bool) -> None:
    """随机落点: x ±(32..63) px, y ±(24..47) px (exe rand&0x1f+0x20 / rand%0x18+0x18, 符号各随机)."""
    rng = battle.rng
    ox = (rng.randint(0, 31) + 32) * (1 if rng.randint(0, 1) else -1)
    oy = (rng.randint(0, 23) + 24) * (1 if rng.randint(0, 1) else -1)
    z0 = rng.randint(0, 63) if rise else ORB_Z
    p = _fx_entity(battle, _particle_think, cx + ox * FP, cy + oy * FP, z0, E00, 30)
    p.user_data.update(particle=True, target=target_xy, rise=rise,
                       frames=PARTICLE_FRAME_SETS[rng.randint(0, 3)])


def _xijing_orb_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'orb' not in ud:
        return
    battle, caster, v = ud['battle'], ud['caster'], ud['victim']
    _orb_flicker(e)
    ud['tick'] += 1
    t = ud['tick']
    if e.state_code == 0:
        if t < XIJING_PARTICLE_TICKS and t & 1:
            vx, vy = _ground(v)
            _spawn_particle(battle, vx, vy, (vx, vy), rise=True)      # 飞向敌人脚下坐标 (= 光球 x,y)
        if t > XIJING_DEPART:
            _sfx(battle, SFX_XIJING_DEPART)
            cx, cy = _ground(caster)
            _aim(e, cx, cy + FP, ORB_Z, XIJING_SPEED_H, XIJING_SPEED_V)
            e.state_code = 10
    elif e.state_code == 10:
        if _fly(e):
            cx, cy = _ground(caster)
            for _ in range(XIJING_BURST_N):
                _spawn_particle(battle, cx, cy, (cx, cy), rise=False)
            ud['settle_at'] = t + XIJING_SETTLE
            e.state_code = 20
    elif e.state_code == 20 and t >= ud['settle_at']:
        _hit(battle, caster, v, sound=SFX_XIJING_HIT)
        ud['coord'].user_data['pending'] -= 1
        eng.destroy(e)


def spawn_xijing(battle, attacker, target_tile) -> "Entity":
    victims = _victims(battle, attacker)
    coord = _spawn_coord(battle, attacker, victims, _pillar_coord_think)
    for v in victims:
        vx, vy = _ground(v)
        o = _fx_entity(battle, _xijing_orb_think, vx, vy + FP, ORB_Z, EJAHA02, 0)
        o.user_data.update(orb=True, caster=attacker, victim=v, coord=coord)
    _sfx(battle, SFX_XIJING_CAST)
    return coord


# ------------------------------------------------------------------ 0x3e 化精為氣 (自身)
def _huaqi_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'huaqi' not in ud:
        return
    if not e.is_playing():
        ud['coord'].user_data['pending'] -= 1
        eng.destroy(e)


def spawn_huaqi(battle, attacker, target_tile) -> "Entity":
    # 目标 = 我方 (自己); 状态位由 combat 的状态技能分支加, 这里只演出
    coord = _spawn_coord(battle, attacker, [attacker], _pillar_coord_think)
    x, y = _ground(attacker)
    f = _fx_entity(battle, _huaqi_think, x, y + FP, 0, EJAHA05, 7)
    f.user_data.update(huaqi=True, coord=coord)
    battle.engine.attach_seq(f, tuple_to_bytecode(HUAQI_SEQ))
    _sfx(battle, SFX_HUAQI)
    return coord


# ------------------------------------------------------------------ 0x3f 冰柱冰身
def _pillar_trap_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'pillar' not in ud:
        return
    battle, caster, v = ud['battle'], ud['caster'], ud['victim']
    ud['tick'] += 1
    t = ud['tick']
    if e.state_code == 0:
        if not e.is_playing():
            e.state_code = 10
    elif e.state_code == 10 and t > PILLAR_TRAP_HIDE - 1:
        if ud['first']:
            _sfx(battle, SFX_ICE_BIG)
        e.flags &= ~0x40                                  # 柱子隐去
        _hit(battle, caster, v, fx=False)
        _shatter(battle, e.x, e.y)
        e.state_code = 20
    elif e.state_code == 20 and t > PILLAR_TRAP_END - 1:
        _hit(battle, caster, v, fx=False)
        ud['coord'].user_data['pending'] -= 1
        eng.destroy(e)


def spawn_ice_pillar_trap(battle, attacker, target_tile) -> "Entity":
    victims = _victims(battle, attacker)
    coord = _spawn_coord(battle, attacker, victims, _pillar_coord_think)
    for i, v in enumerate(victims):
        x, y = _ground(v)
        p = _fx_entity(battle, _pillar_trap_think, x, y + FP, 0, EJAHA01, 0)
        p.user_data.update(pillar=True, caster=attacker, victim=v, coord=coord, first=(i == 0))
        battle.engine.attach_seq(p, tuple_to_bytecode(PILLAR_TRAP_SEQ))
    _sfx(battle, SFX_PILLAR_CAST)
    return coord


# ------------------------------------------------------------------ 0x40 修羅勾魂
def _xiuluo_land_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'land' not in ud:
        return
    if not e.is_playing():
        battle, caster = ud['battle'], ud['caster']
        for v in ud['victims']:
            _hit(battle, caster, v, fx=False)
        ud['coord'].user_data['pending'] = 0
        eng.destroy(e)


def _xiuluo_block_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'block' not in ud:
        return
    e.z += XIULUO_VZ * FP
    if e.z >= 0:
        e.z = 0
        battle = ud['battle']
        land = _fx_entity(battle, _xiuluo_land_think, e.x, e.y, 0, EJAHA07, 0)
        land.user_data.update(land=True, caster=ud['caster'], victims=ud['victims'], coord=ud['coord'])
        battle.engine.attach_seq(land, tuple_to_bytecode(XIULUO_LAND_SEQ))
        _sfx(battle, SFX_XIULUO_LAND)
        eng.destroy(e)


def spawn_xiuluo(battle, attacker, target_tile) -> "Entity":
    victims = _victims(battle, attacker)
    coord = _spawn_coord(battle, attacker, victims, _pillar_coord_think)
    coord.user_data['pending'] = 1
    if not victims:
        coord.user_data['pending'] = 0
        return coord
    x, y = _ground(victims[0])
    b = _fx_entity(battle, _xiuluo_block_think, x, y + FP, XIULUO_HEIGHT, EJAHA07, 18)
    b.user_data.update(block=True, caster=attacker, victims=victims, coord=coord)
    _sfx(battle, SFX_XIULUO_SPAWN)
    return coord


# ------------------------------------------------------------------ 0x41 冰龍升天
def _dragon_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'dragon' not in ud:
        return
    if e.state_code == 0:
        if not e.is_playing():
            from core.son_transform import _spawn_ice_cone, EICE_CONE_BIG, ICE_CONE_HEIGHT
            battle = ud['battle']
            for v in ud['victims']:
                vx, vy = _ground(v)
                _spawn_ice_cone(battle, vx, vy + (4 * FP), ICE_CONE_HEIGHT,
                                EICE_CONE_BIG[battle.rng.randint(0, 2)], big=True)
            ud['land_at'] = ud['tick'] + CONE_LAND_TICKS
            e.flags &= ~0x40
            e.state_code = 10
    elif e.state_code == 10 and ud['tick'] >= ud['land_at']:
        for v in ud['victims']:
            _hit(ud['battle'], ud['caster'], v, fx=False)
        ud['coord'].user_data['pending'] = 0
        eng.destroy(e)
    ud['tick'] += 1


def spawn_ice_dragon(battle, attacker, target_tile) -> "Entity":
    victims = _victims(battle, attacker)
    coord = _spawn_coord(battle, attacker, victims, _pillar_coord_think)
    coord.user_data['pending'] = 1
    x, y = _ground(attacker)
    d = _fx_entity(battle, _dragon_think, x, y + FP, 0, EJAHA08, 0)
    d.user_data.update(dragon=True, caster=attacker, victims=victims, coord=coord)
    battle.engine.attach_seq(d, tuple_to_bytecode(DRAGON_SEQ))
    return coord


JAH_IMPACT_SPAWN = {
    0x39: spawn_ice_drill, 0x3a: spawn_ice_pillar_up, 0x3b: spawn_huajing, 0x3c: spawn_ice_rain,
    0x3d: spawn_xijing, 0x3e: spawn_huaqi, 0x3f: spawn_ice_pillar_trap, 0x40: spawn_xiuluo,
    0x41: spawn_ice_dragon,
}
