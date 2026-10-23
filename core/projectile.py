"""技能投射物 (think_fn 物理) — 仿原版 dispatcher fn 在 IMPACT 时调 spawn_fn 创建独立 entity.

== 原版语义 (赤雲波 为例) ==
1. caster cast seq 跑完播 IMPACT (-100), 跳到技能 dispatcher 的 case -100 分支
2. 分支调 `FUN_005044c8(spawn_x, spawn_y)` (`spawn_fn`):
   - `create_entity(think_fn=FUN_00504413)` (= 工厂)
   - 初始化位置 (z=40px 高度) + 初速度 (vz=-2px/tick 起步落下)
   - 设 atlas (edit01 = 277)
3. 投射物 entity think_fn 每帧:
   - state 0 (falling): 物理更新 → 若 z<=0 → attach 着陆爆炸 seq + 信号 -250
   - state 10 (exploding): 等 seq 跑完 → 信号 -200 (end) + destroy
4. action_obj dispatcher case -250 (IMPACT_2): 真伤害结算 + reaction + 2 个 hit-fx

== 工程化抽象 ==
- 物理: 每 tick `vz += gravity`; `z += vz`. 同样支持 vx/vy (水平投射).
- 信号: think_fn 直接调 `eng._signal(entity, SIG_IMPACT_2)` 路由给 battle 的 signal handler.
- 着陆 seq: 标准 anim_engine 字节码 (FM ops), 自动播完触发 destroy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.anim_engine.entity import SIG_END, SIG_IMPACT_2

if TYPE_CHECKING:
    from core.anim_engine.engine import Engine
    from core.anim_engine.entity import Entity


# 16.16 fixed-point 单位 (1 px = 0x10000)
FP_ONE = 0x10000

# 投射物物理常量 (粗调, 视觉合理就行; 不死磕原版字节级)
# GRAVITY 越大下落越快; 配合 initial_height 调节落地时长.
GRAVITY_PER_TICK = 0x4000           # vz 每 tick +0x4000 (16.16 = 0.25 px/tick²)

# 赤雲波 着陆爆炸 seq (atlas 277=edit01, 27 帧 ticks=1 = 1080ms 总). exe @0x00676b60 dump.
CLOUDWAVE_EXPLOSION_SEQ: list[tuple] = [
    ('fm', 277, 0, 1), ('fm', 277, 1, 1), ('fm', 277, 2, 1), ('fm', 277, 3, 1),
    ('fm', 277, 4, 1), ('fm', 277, 5, 1), ('fm', 277, 6, 1), ('fm', 277, 3, 1),
    ('fm', 277, 4, 1), ('fm', 277, 5, 1), ('fm', 277, 6, 1), ('fm', 277, 7, 1),
    ('fm', 277, 3, 1), ('fm', 277, 4, 1), ('fm', 277, 5, 1), ('fm', 277, 6, 1),
    ('fm', 277, 7, 1), ('fm', 277, 7, 1), ('fm', 277, 8, 1), ('fm', 277, 9, 1),
    ('fm', 277, 10, 1), ('fm', 277, 11, 1), ('fm', 277, 12, 1), ('fm', 277, 13, 1),
    ('fm', 277, 14, 1), ('fm', 277, 15, 1),
    ('exit',),
]


# State codes for projectile think_fn
PROJ_STATE_FLYING = 0
PROJ_STATE_EXPLODING = 10
PROJ_STATE_DONE = 20


def _sfx(battle, sound_id: int, solo: bool = False) -> None:
    """播全局 sound_id (= exe FUN_00416311 在 spawn/think 里的显式调用). 绑定表见 core.battle.exe_sounds."""
    battle.engine._emit('sound_play_solo' if solo else 'sound_play', None, sound_id)


def _cloudwave_victims(battle, caster):
    out = []
    tiles = getattr(battle, '_pending_damage_range', None)
    if tiles:
        for (x, y) in tiles:
            u = battle.q.occupant(x, y)
            if u is not None and u.alive and u.is_player != caster.is_player:
                out.append(u)
    elif caster.pending_attack_target is not None and caster.pending_attack_target.alive:
        out.append(caster.pending_attack_target)
    return out


def cloudwave_think_fn(e: "Entity", eng: "Engine") -> None:
    """赤雲波 FUN_00504413 (2026-10-22 实录 mask_21_F45221): z 640 以 32px/t 匀速落 (20t) → 落地 -250 (全敌受击 seq + 两特效)
    + 播 0xf6 + 挂 seq 0x676b60 (edit01 52t) → seq 完 再 -250 + -200 (飘字) 自毁; dispatcher 0x1e 等飘字 → 渐亮."""
    ud = e.user_data
    if 'battle' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    if e.state_code == PROJ_STATE_FLYING:
        e.z += CLOUDWAVE_VZ << 16
        if e.z >= 0:
            from core.jah_skills import _hit
            from core.anim_engine.bytecode import tuple_to_bytecode
            e.z = 0
            for v in ud['victims']:
                _hit(battle, caster, v, fx='both')
            _sfx(battle, 246)
            eng.attach_seq(e, tuple_to_bytecode(CLOUDWAVE_EXPLOSION_SEQ))
            e.state_code = PROJ_STATE_EXPLODING
    elif e.state_code == PROJ_STATE_EXPLODING:
        if not e.is_playing():
            from core.jah_skills import _hit
            for v in ud['victims']:
                _hit(battle, caster, v, fx='both')
            ud['coord'].user_data['pending'] = 0          # -200: 飘字 (SIG_IMPACT_2 → 结算, 受击/特效已由上面 -250 放)
            eng.destroy(e)


CLOUDWAVE_Z = 640
CLOUDWAVE_VZ = 32
SKY_DROP_HEIGHT_PX = 600
SKY_DROP_FLIGHT_TICKS = 24


def _compute_initial_vz(height_px: int, ticks: int, gravity: int) -> int:
    """逆推 vz_0 使物体在 ticks 个 tick 内从 -height 自由下落到 0.
       z_n = z_0 + Σ_{t=1..n} vz_t   其中  vz_t = vz_0 + t * gravity
            → z_n - z_0 = n*vz_0 + gravity * n*(n+1)/2
       想 z_n = 0, z_0 = -height (16.16): vz_0 = (height - gravity * n*(n+1)/2) / n.
    """
    total = height_px * FP_ONE
    return (total - gravity * ticks * (ticks + 1) // 2) // ticks


def spawn_cloudwave_projectile(battle, attacker, target_tile: tuple[int, int]) -> "Entity":
    """赤雲波 -100 (FUN_005044c8): 在光标格 (x, y+1) z 640 生成 edit01 (277), vz -32 匀速 (无重力)."""
    from core.sprites.base import TILE_W, TILE_H
    from core.jah_skills import _spawn_coord, _pillar_coord_think
    eng = battle.engine
    victims = _cloudwave_victims(battle, attacker)
    coord = _spawn_coord(battle, attacker, victims, _pillar_coord_think)
    coord.user_data['pending'] = 1
    tx, ty = target_tile
    e = eng.spawn(think_fn=cloudwave_think_fn)
    e.x = (tx * TILE_W + TILE_W // 2) << 16
    e.y = ((ty * TILE_H + TILE_H // 2 + 1) << 16)
    e.z = -(CLOUDWAVE_Z << 16)
    e.vx = e.vy = e.vz = 0
    e.atlas_slot, e.frame_idx = 277, 0
    e.flags |= 0x40
    e.user_data.update(kind='hit_effect', projectile=True, battle=battle, caster=attacker, victims=victims, coord=coord)
    e.state_code = PROJ_STATE_FLYING
    return e


PHOENIX_ATLAS_BY_FACING = (269, 270, 271, 272)  # UP/DN/LF/RT, exe esam03a/b/c/d
# 2026-10-22 实录 sz_17_F32270 + reverse_engineering/phoenix_decomp.txt (FUN_004fe964 spawn / 4fe717 think):
# spawn 在施法者当前位置 (x, y+1, z+32) 再按朝向偏 (上 y-24 / 下 y+24 / 左 x-32 / 右 x+32), flags 0x31 弹簧目标 = 目标敌,
# 主轴初速 +1.0 px/t, 加速度 上下 0x9999=0.6 / 左右 0xcccc=0.8 (无阻尼, 朝目标); 先挂长大 seq 0x67312c[dir] (帧 0-4 各 t4 = 25 帧)
# → 挂扑翅 seq 0x6731ec[dir] (帧 5-8 t4 循环) + 弹簧飞; 主轴越过敌格 → 钳到 (敌x, 敌y+24, 敌z+32+24), 加速度 0 (匀速)
# 继续飞到屏外 (屏幕坐标超出 ±100) → -200 (开始放火) + -205 (施法者 idle) 自毁. 播 0x100.
# 火: dispatcher 0x28 从 -200 下一 tick 起每 4 tick 一个 efock01 (291, seq 0x655e58) 在 (敌x±32, 敌y+24, z 72±32) 播 0xd7, 共 8;
# 0x32 等 8 个都播完 (-210) → 飘字 + 受击 seq (**无特效**) → 等飘字 → 渐亮 (自定义调色板 60 步 ≈ 38 tick).
PHOENIX_DIR_OFF = {0: (0, -24), 1: (0, 24), 2: (-32, 0), 3: (32, 0)}
PHOENIX_ACCEL = {0: 0x9999, 1: 0x9999, 2: 0xcccc, 3: 0xcccc}
PHOENIX_V0 = 0x10000
PHOENIX_Z = 32
PHOENIX_SNAP_OFF = 24
PHOENIX_OFFSCREEN_MARGIN = 100
PHOENIX_SCREEN = (640, 480)
EFOCK01_ATLAS = 291
EFOCK01_EXPLOSION_SEQ: list[tuple] = [
    ('fm', EFOCK01_ATLAS, 0, 1), ('fm', EFOCK01_ATLAS, 1, 1),
    ('fm', EFOCK01_ATLAS, 2, 3), ('fm', EFOCK01_ATLAS, 3, 3),
    ('fm', EFOCK01_ATLAS, 4, 3), ('fm', EFOCK01_ATLAS, 5, 4),
    ('fm', EFOCK01_ATLAS, 6, 6), ('fm', EFOCK01_ATLAS, 7, 6),
    ('exit',),
]

PHOENIX_BURST_COUNT = 8
PHOENIX_BURST_INTERVAL = 4
PHOENIX_BURST_SCATTER_PX = 32
PHOENIX_BURST_Y_OFFSET = 24
PHOENIX_BURST_Z_BASE = 72
_PHOENIX_GROW = 0
_PHOENIX_FLY = 10
_PHOENIX_EXIT = 14                  # exe state 20 (避开我们的 PROJ_DONE 20)


def _phoenix_grow_seq(atlas):
    return [('fm', atlas, f, 4) for f in range(5)] + [('exit',)]


def _phoenix_fly_seq(atlas):
    return [('fm', atlas, f, 4) for f in (5, 6, 7, 8)] + [('loop',)]


def _ember_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'ember' not in ud:
        return
    if not e.is_playing():                               # -210
        ud['coord'].user_data['pending'] -= 1
        eng.destroy(e)


def _ember_spawner_think(e: "Entity", eng: "Engine") -> None:
    """dispatcher 0x28: -200 下一 tick 起每 4 tick 一个 efock01 (共 8)."""
    from core.anim_engine.bytecode import tuple_to_bytecode
    ud = e.user_data
    if 'spawner' not in ud:
        return
    ud['tick'] += 1
    if ud['tick'] % PHOENIX_BURST_INTERVAL != 1:
        return
    battle = ud['battle']; rng = battle.rng
    b = battle.engine.spawn(think_fn=_ember_think)
    b.x = ud['tx'] + ((rng.randint(0, 63) - 32) << 16)
    b.y = ud['ty'] + (PHOENIX_BURST_Y_OFFSET << 16)
    b.z = -((PHOENIX_BURST_Z_BASE + rng.randint(0, 63) - 32) << 16)
    b.atlas_slot, b.frame_idx = EFOCK01_ATLAS, 0
    b.flags |= 0x40
    b.user_data.update(kind='hit_effect', projectile=True, ember=True, coord=ud['coord'])
    battle.engine.attach_seq(b, tuple_to_bytecode(EFOCK01_EXPLOSION_SEQ))
    _sfx(battle, 0xd7)
    ud['n'] += 1
    if ud['n'] >= PHOENIX_BURST_COUNT:
        eng.destroy(e)


def _phoenix_offscreen(battle, caster, e: "Entity") -> bool:
    view = getattr(battle, 'view_center_world', None)
    if view is None:
        from core.sprites.base import TILE_W, TILE_H
        view = (caster.x * TILE_W + TILE_W // 2, caster.y * TILE_H + TILE_H // 2)
    sx = (e.x >> 16) - (view[0] - PHOENIX_SCREEN[0] // 2)
    sy = (e.y >> 16) + (e.z >> 16) - (view[1] - PHOENIX_SCREEN[1] // 2)
    m = PHOENIX_OFFSCREEN_MARGIN
    return sx < -m or sx > PHOENIX_SCREEN[0] + m or sy < -m or sy > PHOENIX_SCREEN[1] + m


def phoenix_think_fn(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'target_x' not in ud:
        return
    battle, caster, d = ud['battle'], ud['caster'], ud['dir']
    if e.state_code == _PHOENIX_GROW:
        if not e.is_playing():
            from core.anim_engine.bytecode import tuple_to_bytecode
            battle.engine.attach_seq(e, tuple_to_bytecode(_phoenix_fly_seq(e.atlas_slot)))
            e.state_code = _PHOENIX_FLY
    elif e.state_code == _PHOENIX_FLY:
        tx, ty = ud['target_x'], ud['target_y']
        if d in (0, 1):
            ud['v'] += ud['a'] if e.y < ty else -ud['a']
            e.y += ud['v']
            passed = e.y <= ty if d == 0 else e.y >= ty
        else:
            ud['v'] += ud['a'] if e.x < tx else -ud['a']
            e.x += ud['v']
            passed = e.x <= tx if d == 2 else e.x >= tx
        if passed:
            e.x = tx
            e.y = ty + (PHOENIX_SNAP_OFF << 16)
            e.z = -((PHOENIX_Z + PHOENIX_SNAP_OFF) << 16)
            e.state_code = _PHOENIX_EXIT
    elif e.state_code == _PHOENIX_EXIT:
        if d in (0, 1):
            e.y += ud['v']
        else:
            e.x += ud['v']
        if _phoenix_offscreen(battle, caster, e):
            from core.jah_skills import _spawn_coord, _pillar_coord_think
            coord = _spawn_coord(battle, caster, ud['victims'], _pillar_coord_think)   # -200: 放火 8 个, 全完才结算
            coord.user_data['pending'] = PHOENIX_BURST_COUNT
            sp = battle.engine.spawn(think_fn=_ember_spawner_think)
            sp.flags = 0x800 | 0x10000
            sp.user_data.update(kind='ember_spawner', projectile=True, spawner=True, battle=battle, coord=coord,
                                tx=ud['target_x'], ty=ud['target_y'], tick=0, n=0)
            caster.cast_hold = False                                             # -205: 施法者 idle
            eng.destroy(e)


def spawn_phoenix_effect(battle, attacker, target_tile: tuple[int, int]) -> "Entity":
    """凤凰掌 -100: 凤凰 (esam03 按朝向) 在施法者前长大 → 弹簧飞向目标 → 越过目标后匀速飞出屏幕 → 8 个 efock01 → 结算."""
    from core.sprites.base import TILE_W, TILE_H
    from core.attack_seq import facing_to_atk_index
    from core.anim_engine.bytecode import tuple_to_bytecode
    eng = battle.engine
    d = facing_to_atk_index(attacker.facing)
    atlas = PHOENIX_ATLAS_BY_FACING[d]
    tx, ty = target_tile
    victims = []
    tiles = getattr(battle, '_pending_damage_range', None)
    for (x, y) in (tiles or [(tx, ty)]):
        u = battle.q.occupant(x, y)
        if u is not None and u.alive and u.is_player != attacker.is_player:
            victims.append(u)
    ent = attacker.entity
    ox, oy = PHOENIX_DIR_OFF[d]
    e = eng.spawn(think_fn=phoenix_think_fn)
    e.x = ((attacker.x * TILE_W + TILE_W // 2 + ox) << 16) + (ent.x if ent is not None else 0)
    e.y = ((attacker.y * TILE_H + TILE_H // 2 + 1 + oy) << 16) + (ent.y if ent is not None else 0)
    e.z = -(PHOENIX_Z << 16)
    e.atlas_slot, e.frame_idx = atlas, 0
    e.flags |= 0x40
    e.user_data.update(kind='hit_effect', projectile=True, battle=battle, caster=attacker, dir=d, victims=victims,
                       target_x=(tx * TILE_W + TILE_W // 2) << 16, target_y=(ty * TILE_H + TILE_H // 2) << 16,
                       v=PHOENIX_V0, a=PHOENIX_ACCEL[d])
    e.state_code = _PHOENIX_GROW
    eng.attach_seq(e, tuple_to_bytecode(_phoenix_grow_seq(atlas)))
    _sfx(battle, 256)                  # exe FUN_004fe964 spawn 凤凰播 0x100
    return e


# =========================================================================
# 火龍斬 0x22 — exe @0x504ad2 spawn + @0x504a77 think_fn + @0x676d38 effect seq
# =========================================================================
# 无物理 (无 z 落地), 落 cursor → 播放 16 帧火龍 atlas 278 → seq 完 signal IMPACT_2 → damage.
HUOLONG_EFFECT_SEQ: list[tuple] = [
    ('fm', 278, 0, 1), ('sound', 327, 0x0411), ('fm', 278, 1, 1), ('fm', 278, 2, 1),
    ('sound', 221, 0x0411), ('fm', 278, 3, 1),      # exe 序列 tick1 播 0x147, tick4 播 0xdd (两条同 tick 只算 1 次)
    ('fm', 278, 4, 1), ('fm', 278, 5, 1), ('fm', 278, 6, 1), ('fm', 278, 7, 1),
    ('fm', 278, 8, 1), ('fm', 278, 9, 1), ('fm', 278, 10, 1), ('fm', 278, 11, 1),
    ('fm', 278, 12, 1), ('fm', 278, 13, 1), ('fm', 278, 14, 1), ('fm', 278, 15, 1),
    ('exit',),
]


def huolong_think_fn(e: "Entity", eng: "Engine") -> None:
    """火龍斬 FUN_00504a77 (实录 mask_22_F90788): 光标格 (x, y+1) 播 seq 0x676d38 (278 帧 0-15, 32t) → 完 -200:
    全敌飘字 + 受击 seq (无特效) + 播 0xbd; dispatcher 0x1e 等飘字落定 → 施法者 idle → 渐亮."""
    if e.state_code == PROJ_STATE_EXPLODING and not e.is_playing():
        e.user_data['coord'].user_data['pending'] = 0
        eng.destroy(e)
        e.state_code = PROJ_STATE_DONE


def spawn_huolong_effect(battle, attacker, target_tile: tuple[int, int]) -> "Entity":
    """spawn 火龍斬 effect (无物理, 直接 cursor 上 attach 16 帧动画).
    Effect seq 完成时 think_fn 发 SIG_IMPACT_2 → 结算伤害.
    """
    from core.sprites.base import TILE_W, TILE_H
    from core.anim_engine.bytecode import tuple_to_bytecode
    from core.jah_skills import _spawn_coord, _pillar_coord_think
    eng = battle.engine
    coord = _spawn_coord(battle, attacker, _cloudwave_victims(battle, attacker), _pillar_coord_think)
    coord.user_data['pending'] = 1

    tx, ty = target_tile
    e = eng.spawn(think_fn=huolong_think_fn)
    e.x = (tx * TILE_W + TILE_W // 2) * FP_ONE
    e.y = (ty * TILE_H + TILE_H // 2 + 1) * FP_ONE
    e.z = 0
    e.vx = e.vy = e.vz = 0
    e.atlas_slot = 278
    e.frame_idx = 0
    e.flags |= 0x40
    e.user_data.update(kind='hit_effect', projectile=True, coord=coord)
    e.state_code = PROJ_STATE_EXPLODING       # 直接到 seq-playing 阶段
    eng.attach_seq(e, tuple_to_bytecode(HUOLONG_EFFECT_SEQ))
    return e


# =========================================================================
# 破天舞 0x23 — exe @0x504f27 (spawn_fn A) + @0x504eaa (think_fn scatter) +
#               @0x0050524f (spawn_fn B) + @0x00505140 (think_fn secondary)
#               @0x655eac (POTIAN_TRAJ_SEQ atlas 292) +
#               @0x676de8 (POTIAN_SECONDARY_SEQ atlas 279)
# =========================================================================
# 原版完整流程 (per dispatcher @0x5052aa):
#   case 10:  per victim spawn 1 "secondary" entity (think_fn FUN_00505140) playing
#             POTIAN_SECONDARY_SEQ (atlas 279, 9 帧). 每帧 ticks 5/4/3/3/3/3/3/3/3 = 29 ticks.
#   case -150: 当 第一个 secondary 完, caster 走 cdit1_g0 trajectory (大斩) + sound 0x118
#              (这里我们简化: 跳过 caster 移动动画, 直接进 scatter+trajectory 阶段)
#   case -100: per victim spawn 2 scatter (atlas 279, frames 9/10, 随机 vx/vy 朝 victim 收敛
#              物理) + 1 trajectory entity (atlas 292, POTIAN_TRAJ_SEQ 12 帧)
#   case -160: 每个 trajectory 完 → damage + hit reaction; counters 归零 → 结束
#
# 我们的实现走 coordinator 状态机:
#   PHASE_SECONDARY: spawn N secondary 完跑 29 ticks
#   PHASE_SCATTER:   spawn 2N scatter + N trajectory, 跑 ~36 ticks (trajectory 总长 12 帧 × 3 avg)
#   PHASE_DAMAGE:    发 SIG_IMPACT_2 → battle 走默认伤害路径 (用 _pending_damage_range)
#
# 真实物理 (FUN_004c3211 mode 0x31): "toward target" 模式
#   每 tick: 如果 entity.x < target_x → vx += step; 否则 vx -= step. 然后 x += vx.
#   = "spring" 般往目标收敛 + 初始随机速度 = 散射后回旋.
# 天字: 生长 (帧 0-8) 后**停在帧 8 保持**, 直到挥刀 impact 才被斩开销毁 (exe: secondary
# entity 长成后 idle, dispatcher -100 时才销毁 + spawn 两半). 故末尾长 hold 帧 8, 不 exit.
POTIAN_SECONDARY_HOLD = 600
POTIAN_SECONDARY_SEQ: list[tuple] = [
    ('fm', 279, 0, 5), ('fm', 279, 1, 4), ('fm', 279, 2, 3), ('fm', 279, 3, 3),
    ('fm', 279, 4, 3), ('fm', 279, 5, 3), ('fm', 279, 6, 3), ('fm', 279, 7, 3),
    ('fm', 279, 8, POTIAN_SECONDARY_HOLD),
]

# cdit1_g0 dash + strike seq (exe @0x6767d0, 4 方向). dispatcher case -150 第一次时
# attach 这个到 caster.entity. 包含 7 帧前突 + 12 tick 蓄力 + 3 帧斩 + IMPACT + 3 帧弹回 + END.
# 'jump' / 'impact' / 'end' 各自路由到 anim_engine SIG, coord 拦截 IMPACT 切 PHASE_SCATTER.
CDIT1_G0_TABLE: list[list[tuple]] = [
    # UP
    [
        ('move', 0, -1, 0), ('fm', 19, 0, 3),
        ('move', 0, -1, 0), ('fm', 19, 1, 3),
        ('move', 0, -1, 0), ('fm', 19, 2, 3),
        ('move', 0, -1, 0), ('fm', 19, 3, 3),
        ('move', 0, -1, 0), ('fm', 19, 4, 3),
        ('move', 0, -1, 0), ('fm', 19, 5, 3),
        ('move', 0, -1, 0), ('fm', 19, 6, 12),
        ('move', 0, -6, 0),
        ('jump', -1000), ('jump', -1001),   # exe seq 蓄力后信号: 破天舞 dispatcher -1001 播挥刀音 0x105
        ('fm', 19, 7, 2), ('move', 0, -6, 0),
        ('fm', 19, 8, 3), ('move', 0, -6, 0),
        ('impact',),
        ('fm', 19, 9, 3),
        ('fm', 19, 10, 3),
        ('fm', 19, 11, 15), ('move', 0, 25, 0),
        ('fm', 19, 0, 0),
        ('end',),
    ],
    # DN
    [
        ('move', 0, 1, 0), ('fm', 19, 12, 3),
        ('move', 0, 1, 0), ('fm', 19, 13, 3),
        ('move', 0, 1, 0), ('fm', 19, 14, 3),
        ('move', 0, 1, 0), ('fm', 19, 15, 3),
        ('move', 0, 1, 0), ('fm', 19, 16, 3),
        ('move', 0, 1, 0), ('fm', 19, 17, 3),
        ('move', 0, 1, 0), ('fm', 19, 18, 12),
        ('move', 0, 6, 0),
        ('jump', -1000), ('jump', -1001),   # exe seq 蓄力后信号: 破天舞 dispatcher -1001 播挥刀音 0x105
        ('fm', 19, 19, 2), ('move', 0, 6, 0),
        ('fm', 19, 20, 3), ('move', 0, 6, 0),
        ('impact',),
        ('fm', 19, 21, 3),
        ('fm', 19, 22, 3),
        ('fm', 19, 23, 15), ('move', 0, -25, 0),
        ('fm', 19, 12, 0),
        ('end',),
    ],
    # LF
    [
        ('move', -2, 0, 0), ('fm', 19, 24, 3),
        ('move', -2, 0, 0), ('fm', 19, 25, 3),
        ('move', -2, 0, 0), ('fm', 19, 26, 3),
        ('move', -2, 0, 0), ('fm', 19, 27, 3),
        ('move', -2, 0, 0), ('fm', 19, 28, 3),
        ('move', -2, 0, 0), ('fm', 19, 29, 3),
        ('move', -2, 0, 0), ('fm', 19, 30, 12),
        ('move', -8, 0, 0),
        ('jump', -1000), ('jump', -1001),   # exe seq 蓄力后信号: 破天舞 dispatcher -1001 播挥刀音 0x105
        ('fm', 19, 31, 2), ('move', -8, 0, 0),
        ('fm', 19, 32, 3), ('move', -8, 0, 0),
        ('impact',),
        ('fm', 19, 33, 3),
        ('fm', 19, 34, 3),
        ('fm', 19, 35, 15), ('move', 38, 0, 0),
        ('fm', 19, 24, 0),
        ('end',),
    ],
    # RT
    [
        ('move', 2, 0, 0), ('fm', 19, 36, 3),
        ('move', 2, 0, 0), ('fm', 19, 37, 3),
        ('move', 2, 0, 0), ('fm', 19, 38, 3),
        ('move', 2, 0, 0), ('fm', 19, 39, 3),
        ('move', 2, 0, 0), ('fm', 19, 40, 3),
        ('move', 2, 0, 0), ('fm', 19, 41, 3),
        ('move', 2, 0, 0), ('fm', 19, 42, 12),
        ('move', 8, 0, 0),
        ('jump', -1000), ('jump', -1001),   # exe seq 蓄力后信号: 破天舞 dispatcher -1001 播挥刀音 0x105
        ('fm', 19, 43, 2), ('move', 8, 0, 0),
        ('fm', 19, 44, 3), ('move', 8, 0, 0),
        ('impact',),
        ('fm', 19, 45, 3),
        ('fm', 19, 46, 3),
        ('fm', 19, 47, 15), ('move', -38, 0, 0),
        ('fm', 19, 36, 0),
        ('end',),
    ],
]

POTIAN_TRAJ_SEQ: list[tuple] = [
    ('fm', 292, 0, 1), ('fm', 292, 1, 1), ('fm', 292, 2, 2), ('fm', 292, 3, 2),
    ('fm', 292, 4, 2), ('fm', 292, 3, 2), ('fm', 292, 5, 3), ('fm', 292, 6, 4),
    ('fm', 292, 7, 5), ('fm', 292, 8, 5), ('fm', 292, 9, 5), ('fm', 292, 10, 5),
    ('exit',),
]
SECONDARY_PHASE_TICKS = 39      # 实录 mask_23: 天字 seq 0x676de8 (帧 0-8) 完 -150 → 施法者挥刀, 共 39 tick
# scatter (天字斩开两半) 寿命: exe FUN_00504eaa state0 漂移到内部 tick>0x20(32), state1 闪烁到 >0x30(48).
SCATTER_DRIFT_TICKS = 32
SCATTER_BLINK_TICKS = 16
SCATTER_PHASE_TICKS = SCATTER_DRIFT_TICKS + SCATTER_BLINK_TICKS   # coordinator 等 scatter 跑完再结算
SCATTER_SPLIT_VX = FP_ONE               # FUN_00504f27: vx = ∓1, vy = +1 px/tick 匀速 ((rand&0x3ff)>>10 恒 0 → +1), 无加速度
POTIAN_FX_Y_OFF = 600                   # 天字/半片 生在 (x, y+600, z 600) = 画在敌格但排序最前
POTIAN_EXPLODE_Y_PX = 36                 # 爆炸/天字/斩开 抬到敌人 sprite 中心 (像素, 脚上方)

# Coordinator state codes (复用 PROJ_STATE_* 命名空间)
_POTIAN_PHASE_SECONDARY = 30        # spawn N secondaries, 等 29 ticks
_POTIAN_PHASE_CASTER_DASH = 31      # caster 跑 cdit1_g0 (前突+蓄力+斩), 等 IMPACT 信号
_POTIAN_PHASE_SCATTER = 32          # spawn 2 scatter + 1 trajectory per victim, 等 38 ticks
_POTIAN_PHASE_DAMAGE = 33           # 发 SIG_IMPACT_2 → 默认伤害路径


def potian_passive_effect_think(e: "Entity", eng: "Engine") -> None:
    """trajectory effect: seq 完即销毁, 无副作用."""
    if e.state_code == PROJ_STATE_EXPLODING and not e.is_playing():
        eng.destroy(e)
        e.state_code = PROJ_STATE_DONE


def potian_secondary_think(e: "Entity", eng: "Engine") -> None:
    """天字: 生长后停在帧 8 持续显示, 不自毁. 由 coordinator 在斩开阶段统一销毁."""
    pass


def potian_scatter_think(e: "Entity", eng: "Engine") -> None:
    """天字被斩开的两个半片 (atlas 279 帧 9/10): 轻微漂移分开 → 后段闪烁 → 消失.
    exe FUN_00504eaa: state0 飞行到内部 tick>0x20, state1 每 tick toggle 可见位(闪) 到 >0x30 销毁."""
    if e.state_code != PROJ_STATE_EXPLODING:
        return
    t = e.user_data.get('scatter_tick', 0) + 1
    e.user_data['scatter_tick'] = t
    e.x += e.vx
    e.y += e.vy                                          # 直线匀速 (无重力)
    if t <= SCATTER_DRIFT_TICKS:
        e.user_data['projectile'] = True
    elif t <= SCATTER_DRIFT_TICKS + SCATTER_BLINK_TICKS:
        e.user_data['projectile'] = (t % 2 == 0)        # 后段闪烁 (渲染按 projectile 标志)
    else:
        eng.destroy(e)
        e.state_code = PROJ_STATE_DONE


def potian_coordinator_think(e: "Entity", eng: "Engine") -> None:
    """编排 4 阶段: secondary → caster_dash (cdit1_g0) → scatter+trajectory → SIG_IMPACT_2.
    user_data 存 victim 坐标列表 + battle 引用 + caster 引用."""
    if e.state_code == _POTIAN_PHASE_SECONDARY:
        e.user_data['phase_ticks'] = e.user_data.get('phase_ticks', 0) + 1
        if e.user_data['phase_ticks'] >= SECONDARY_PHASE_TICKS:
            # _potian_enter_caster_dash 内部自己设 state (CASTER_DASH 或 fallback 直 SCATTER)
            _potian_enter_caster_dash(e, eng)
    elif e.state_code == _POTIAN_PHASE_CASTER_DASH:
        # PHASE_CASTER_DASH: 等 caster cdit1_g0 跑到 'impact' op. impact 信号
        # 经 tactics._on_anim_signal 拦截 → 调 coord.user_data['on_caster_impact'].
        # 这里 think_fn 啥都不干, 只是不让 coord 死.
        pass
    elif e.state_code == _POTIAN_PHASE_SCATTER:
        e.user_data['phase_ticks'] = e.user_data.get('phase_ticks', 0) + 1
        if e.user_data['phase_ticks'] >= SCATTER_PHASE_TICKS:
            # 撤销 caster 标记 → 让 tactics 之后正常处理.
            caster = e.user_data.get('caster')
            if caster is not None and caster.pending_caster_coord is e:
                caster.pending_caster_coord = None
            eng._signal(e, SIG_IMPACT_2)            # → 伤害结算 (suppress_hit_fx 生效, 不放红刺/斩击)
            if caster is not None:
                caster.suppress_hit_fx = False       # 结算后恢复, 不影响后续普攻
            eng._signal(e, SIG_END)
            eng.destroy(e)
            e.state_code = _POTIAN_PHASE_DAMAGE


def _potian_enter_caster_dash(coord: "Entity", eng: "Engine") -> None:
    """SECONDARY 完 → 进 CASTER_DASH. attach cdit1_g0[caster_facing] 到 caster.entity,
    标记 coord 给 tactics 拦截 IMPACT/END 信号."""
    from core.anim_engine.bytecode import tuple_to_bytecode
    from core.reaction_seq import facing_to_seq_index
    caster = coord.user_data.get('caster')
    if caster is None or caster.entity is None:
        # caster 没了 (测试 stub?) → 直接跳到 SCATTER
        if caster is not None:
            caster.cast_anim_key = None
        _potian_spawn_scatter_phase(coord, eng)
        coord.user_data['phase_ticks'] = 0
        coord.state_code = _POTIAN_PHASE_SCATTER
        return
    # 天字长成 → 解除施法姿, 开始挥刀
    caster.cast_anim_key = None
    # 标 coord, 让 tactics._on_anim_signal 知道 caster 在 potian dash 期间, 把 IMPACT/END 转发到 coord
    caster.pending_caster_coord = coord
    coord.user_data['on_caster_impact'] = _on_caster_impact
    coord.state_code = _POTIAN_PHASE_CASTER_DASH

    dir_idx = facing_to_seq_index(caster.facing)
    eng.attach_seq(caster.entity, tuple_to_bytecode(CDIT1_G0_TABLE[dir_idx]))


def _on_caster_impact(coord: "Entity", eng: "Engine") -> None:
    """caster cdit1_g0 跑到 'impact' op → tactics 调这里. spawn scatter+trajectory + 切 PHASE_SCATTER."""
    if coord.state_code != _POTIAN_PHASE_CASTER_DASH:
        return
    _potian_spawn_scatter_phase(coord, eng)
    coord.user_data['phase_ticks'] = 0
    coord.state_code = _POTIAN_PHASE_SCATTER


def _spawn_potian_secondary(battle, tile_xy: tuple[int, int]) -> "Entity":
    """victim 头顶的 "魔法准备" effect (atlas 279, 9 帧)."""
    from core.sprites.base import TILE_W, TILE_H
    from core.anim_engine.bytecode import tuple_to_bytecode
    eng = battle.engine
    e = eng.spawn(think_fn=potian_secondary_think)
    tx, ty = tile_xy
    e.x = (tx * TILE_W + TILE_W // 2) * FP_ONE
    e.y = (ty * TILE_H + TILE_H // 2 + POTIAN_FX_Y_OFF) * FP_ONE
    e.z = -POTIAN_FX_Y_OFF * FP_ONE
    e.atlas_slot = 279
    e.frame_idx = 0
    e.flags |= 0x40
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.state_code = PROJ_STATE_EXPLODING
    eng.attach_seq(e, tuple_to_bytecode(POTIAN_SECONDARY_SEQ))
    return e


def _spawn_potian_scatter_one(battle, victim_tile: tuple[int, int],
                              vx: int, vy: int, frame_idx: int) -> "Entity":
    """天字被斩开的一个半片 (atlas 279 frame 9 或 10): 在天字位置生成 + 漂移分开 (静态帧, 无 seq)."""
    from core.sprites.base import TILE_W, TILE_H
    eng = battle.engine
    tx, ty = victim_tile
    e = eng.spawn(think_fn=potian_scatter_think)
    e.x = (tx * TILE_W + TILE_W // 2) * FP_ONE
    e.y = (ty * TILE_H + TILE_H // 2 + POTIAN_FX_Y_OFF) * FP_ONE
    e.z = -POTIAN_FX_Y_OFF * FP_ONE
    e.vx = vx
    e.vy = vy
    e.vz = 0
    e.atlas_slot = 279
    e.frame_idx = frame_idx
    e.flags |= 0x40
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True       # 静态帧靠 projectile 标志渲染 (无 seq)
    e.user_data['scatter_tick'] = 0
    e.state_code = PROJ_STATE_EXPLODING
    return e


def _spawn_potian_trajectory(battle, victim_tile: tuple[int, int]) -> "Entity":
    """trajectory: atlas 292 12 帧 在 victim 头顶播放 (主要视觉)."""
    from core.sprites.base import TILE_W, TILE_H
    from core.anim_engine.bytecode import tuple_to_bytecode
    eng = battle.engine
    e = eng.spawn(think_fn=potian_passive_effect_think)
    tx, ty = victim_tile
    rng = battle.rng                                      # FUN_00504f27 → FUN_004d0d7b: (x+rand%12-6, y+24, z 72+rand&15-8)
    e.x = (tx * TILE_W + TILE_W // 2 + rng.randint(0, 11) - 6) * FP_ONE
    e.y = (ty * TILE_H + TILE_H // 2 + 24) * FP_ONE
    e.z = -(72 + rng.randint(0, 15) - 8) * FP_ONE
    e.atlas_slot = 292
    e.frame_idx = 0
    e.flags |= 0x40
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.state_code = PROJ_STATE_EXPLODING
    eng.attach_seq(e, tuple_to_bytecode(POTIAN_TRAJ_SEQ))
    return e


def _potian_spawn_scatter_phase(coord: "Entity", eng: "Engine") -> None:
    """coordinator 进 PHASE_SCATTER 时调 (= 挥刀 impact): 销毁天字 + per victim spawn 2 半片 + 1 trajectory."""
    battle = coord.user_data['battle']
    victims = coord.user_data['victim_tiles']
    # 天字被斩开: 销毁 secondary 天字实体 (即刻被两半替换, 无缝衔接)
    for sec in coord.user_data.get('secondaries', []):
        if sec.state_code != PROJ_STATE_DONE:
            eng.destroy(sec)
            sec.state_code = PROJ_STATE_DONE
    for vt in victims:
        # 天字斩成两半: 帧 9 左下、帧 10 右下, 沿 ~45° 斜下直线匀速分开 (|vx|=|vy|, 无重力)
        _spawn_potian_scatter_one(battle, vt, -SCATTER_SPLIT_VX, SCATTER_SPLIT_VX, frame_idx=9)
        _spawn_potian_scatter_one(battle, vt, +SCATTER_SPLIT_VX, SCATTER_SPLIT_VX, frame_idx=10)
        # 1 个 trajectory (atlas 292) = 斩击/爆炸特效
        _spawn_potian_trajectory(battle, vt)


def spawn_potian_effects(battle, attacker, target_tile: tuple[int, int]) -> "Entity":
    """spawn 破天舞 完整编排 — 严格还原 exe @0x5052aa dispatcher 多阶段流程.
    1. 在 3×3 damage 范围内每个 victim 头顶 spawn secondary effect (atlas 279, 9 帧)
    2. SECONDARY_PHASE_TICKS 后 spawn 2 scatter (随机散+向 victim 收敛物理) + 1 trajectory (atlas 292) per victim
    3. SCATTER_PHASE_TICKS 后发 SIG_IMPACT_2 → battle 默认伤害路径结算 _pending_damage_range
    返回 coordinator entity (= 主控 effect entity)."""
    # 找 3×3 范围里的 victim (= enemy units)
    cx, cy = target_tile
    victims: list[tuple[int, int]] = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            x, y = cx + dx, cy + dy
            if not battle.map.in_bounds(x, y):
                continue
            occ = battle.q.occupant(x, y)
            if occ is not None and occ.alive and occ.is_player != attacker.is_player:
                victims.append((x, y))

    # 如果没有 victim 在 cursor 范围 (= 空地施法), 在 cursor 本身 spawn 占位 victim_tile
    # 让动画有处可放. battle 那边 dmg_tiles 空 → 没扣血, 但视觉照样跑.
    if not victims:
        victims = [target_tile]

    eng = battle.engine

    # Per victim 立即 spawn 天字 secondary (生长后保持, 直到斩开)
    secondaries = [_spawn_potian_secondary(battle, vt) for vt in victims]

    # Coordinator: 无 atlas / 无 seq, 只跑 think_fn 推进阶段计时.
    coord = eng.spawn(think_fn=potian_coordinator_think)
    coord.x = (target_tile[0] * 24 + 12) * FP_ONE  # cursor (TILE_W=24 默认)
    coord.y = (target_tile[1] * 24 + 12) * FP_ONE
    coord.z = 0
    # 保留 spawn 设的 0x800 (pool alive bit, 否则 engine.tick 跳过 think_fn) + 0x10000
    # (has-think-fn), 但不加 0x40 (visible) — coordinator 不渲染.
    coord.flags = 0x800 | 0x10000
    coord.user_data['kind'] = 'potian_coordinator'
    coord.user_data['projectile'] = True   # 让 units_animating 看到, 防回合提前结束
    coord.user_data['battle'] = battle
    coord.user_data['caster'] = attacker
    coord.user_data['victim_tiles'] = victims
    coord.user_data['secondaries'] = secondaries
    coord.user_data['phase_ticks'] = 0
    # 天字生长期间施法者播施法姿 = ps_ atlas 2 (ps_CDIT100 → ps_CDIT102) 的 col0→col1 起手后定格;
    # 挥刀时清除. 重置 idle 计时让 0→1 起手从头开始.
    if attacker.sprite_key:
        attacker.cast_anim_key = attacker.sprite_key[:-1] + '2'
        attacker.anim.idle_time_ms = 0
    # 破天舞命中不放 ef010/et00 受击特效 (视觉只有天字斩开+爆炸); 结算后清除
    attacker.suppress_hit_fx = True
    coord.state_code = _POTIAN_PHASE_SECONDARY
    _sfx(battle, 280)                        # exe FUN_005052aa case -100: 天字 spawn 完播 0x118
    return coord
