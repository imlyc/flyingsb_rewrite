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


def cloudwave_think_fn(e: "Entity", eng: "Engine") -> None:
    """赤雲波 投射物 think_fn (= exe FUN_00504413 简化版).
    state 0: 抛物线物理 (vx+vy 水平匀速, vz 重力下落). z<=0 时落地, 切到爆炸状态.
    state 10: 等爆炸 seq 跑完, 信号 SIG_END + destroy.
    """
    if e.state_code == PROJ_STATE_FLYING:
        # 水平匀速 + 垂直重力
        e.x += e.vx
        e.y += e.vy
        e.vz += GRAVITY_PER_TICK
        e.z += e.vz
        if e.z >= 0:
            # 落地: 钳 z=0, 发 IMPACT_2 (= 让 battle signal handler 结算伤害)
            e.z = 0
            e.vx = e.vy = e.vz = 0
            eng._signal(e, SIG_IMPACT_2)
            # 挂着陆爆炸 seq
            from core.anim_engine.bytecode import tuple_to_bytecode
            eng.attach_seq(e, tuple_to_bytecode(CLOUDWAVE_EXPLOSION_SEQ))
            e.state_code = PROJ_STATE_EXPLODING
    elif e.state_code == PROJ_STATE_EXPLODING:
        # seq 跑完 (= playing flag 落下) → 收
        if not e.is_playing():
            eng._signal(e, SIG_END)
            eng.destroy(e)
            e.state_code = PROJ_STATE_DONE


# 投射物初始高度 (= 离 defender tile 多远) + 落地总时长.
# 屏幕高 600, defender tile 在屏中心附近 → 高度 600 让投射物从屏幕顶外开始落下.
# 落地 24 ticks (= 960ms) 视觉刚好.
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
    """spawn 赤雲波 投射物 — 从屏幕顶外正上方坠落到 target_tile (= AIM cursor 格).
    无水平运动, 仿原版 spawn_fn 只启 Z 轴 (mode flag bit 6).
    """
    from core.sprites.base import TILE_W, TILE_H
    eng = battle.engine

    tx, ty = target_tile
    spawn_x_px = tx * TILE_W + TILE_W // 2
    spawn_y_px = ty * TILE_H + TILE_H // 2

    e = eng.spawn(think_fn=cloudwave_think_fn)
    e.x = spawn_x_px * FP_ONE
    e.y = spawn_y_px * FP_ONE
    e.z = -SKY_DROP_HEIGHT_PX * FP_ONE       # 屏幕顶外, 上方 600 px
    e.vx = 0
    e.vy = 0
    e.vz = _compute_initial_vz(SKY_DROP_HEIGHT_PX, SKY_DROP_FLIGHT_TICKS, GRAVITY_PER_TICK)
    e.atlas_slot = 277          # edit01 (mode 0)
    e.frame_idx = 0
    e.flags |= 0x40
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.state_code = PROJ_STATE_FLYING
    return e


# =========================================================================
# 凤凰掌 0x17 三藏 — exe @0x4fe964 spawn + @0x4fe717 think_fn + @0x67312c traj
# =========================================================================
# Exe flow:
#   spawn 在 caster + 小偏移, mode 0x31 (toward-target spring), atlas 269-272 per facing.
#   state 0: attach 出现 seq (atlas N frames 0-4 @ 4 ticks each, exe @0x67312c[facing])
#   state 10: physics tick spring-toward-target. 当 entity 经过 target tile (e.g. UP: entity.y <=
#             target.y) → 翻转速度 step. 进 state 20.
#   state 20: 继续 physics (= 现在远离 target 飞出去). 当 entity 跑出屏幕 (-100/+540 边界) →
#             SIG -200 + -205 + destroy.
#
# 我们简化: 用 4 phase 状态机.
#   FLYING_OUT: 从 caster 朝 target 飞, linear velocity. 抵 target 时 → SIG_IMPACT_2 + 切 FLYING_BACK
#   FLYING_BACK: 沿原速度反向, 飞 30 tick → destroy
PHOENIX_ATLAS_BY_FACING = (269, 270, 271, 272)  # UP/DN/LF/RT, exe esam03a/b/c/d
PHOENIX_SPEED_PX_PER_TICK = 12      # 飞行速度 (px/tick @ 30ms = 400 px/s)
PHOENIX_BACK_TICKS = 30             # IMPACT 后飞 30 tick 退场

_PHOENIX_STATE_OUT = 0
_PHOENIX_STATE_BACK = 1
_PHOENIX_STATE_DONE = 2


def phoenix_think_fn(e: "Entity", eng: "Engine") -> None:
    if e.state_code == _PHOENIX_STATE_OUT:
        e.x += e.vx
        e.y += e.vy
        # 检测是否经过 target (= 速度方向跨过 target 坐标)
        tx = e.user_data['target_x']
        ty = e.user_data['target_y']
        passed = False
        if e.vx > 0 and e.x >= tx: passed = True
        elif e.vx < 0 and e.x <= tx: passed = True
        elif e.vy > 0 and e.y >= ty: passed = True
        elif e.vy < 0 and e.y <= ty: passed = True
        if passed:
            eng._signal(e, SIG_IMPACT_2)
            e.user_data['back_ticks'] = 0
            e.state_code = _PHOENIX_STATE_BACK
    elif e.state_code == _PHOENIX_STATE_BACK:
        # 继续匀速冲过 target, 直到 BACK_TICKS 收尾
        e.x += e.vx
        e.y += e.vy
        e.user_data['back_ticks'] += 1
        if e.user_data['back_ticks'] >= PHOENIX_BACK_TICKS:
            eng._signal(e, SIG_END)
            eng.destroy(e)
            e.state_code = _PHOENIX_STATE_DONE


def spawn_phoenix_effect(battle, attacker, target_tile: tuple[int, int]) -> "Entity":
    """spawn 凤凰掌 — phoenix 从 caster 朝 cursor 飞, 抵达时 SIG_IMPACT_2 触发伤害, 继续飞过去退场.
    atlas 按 caster facing 选 (UP=269/DN=270/LF=271/RT=272 = esam03a/b/c/d).
    """
    from core.sprites.base import TILE_W, TILE_H
    from core.anim_engine.bytecode import tuple_to_bytecode
    from core.reaction_seq import facing_to_seq_index
    eng = battle.engine

    facing_idx = facing_to_seq_index(attacker.facing)
    atlas = PHOENIX_ATLAS_BY_FACING[facing_idx]
    fx, fy = attacker.facing

    # 出生点: caster tile 中心 + facing 方向半 tile 偏移 (= 出 caster 身体), 高度抬到胸口.
    # 参考 exe FUN_004fe964: spawn 在 caster.x/y, z += 32 (高度), 然后按 facing 加 ±24/32 偏移.
    # 我们 TILE_W=64 → 半 tile = 32; 角色身高 ~80 → 胸口 ≈ -40 (在 tile 中心上 40).
    spawn_x_px = attacker.x * TILE_W + TILE_W // 2 + fx * (TILE_W // 2)
    spawn_y_px = attacker.y * TILE_H + TILE_H // 2 + fy * (TILE_H // 2)
    tx, ty = target_tile
    target_x_px = tx * TILE_W + TILE_W // 2
    target_y_px = ty * TILE_H + TILE_H // 2

    e = eng.spawn(think_fn=phoenix_think_fn)
    e.x = spawn_x_px * FP_ONE
    e.y = spawn_y_px * FP_ONE
    e.z = -(TILE_H // 2) * FP_ONE       # 上抬 TILE_H/2 px → anchor 落在 caster tile 上沿
    e.vx = fx * PHOENIX_SPEED_PX_PER_TICK * FP_ONE
    e.vy = fy * PHOENIX_SPEED_PX_PER_TICK * FP_ONE
    e.vz = 0
    e.atlas_slot = atlas
    e.frame_idx = 0
    e.flags |= 0x40
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.user_data['target_x'] = target_x_px * FP_ONE
    e.user_data['target_y'] = target_y_px * FP_ONE
    e.state_code = _PHOENIX_STATE_OUT
    # 5 帧出现 seq + 最后帧长持续 (= 留 phoenix 视觉持续整个飞行).
    seq = [('fm', atlas, i, 4) for i in range(4)] + [('fm', atlas, 4, 200), ('exit',)]
    eng.attach_seq(e, tuple_to_bytecode(seq))
    return e


# =========================================================================
# 火龍斬 0x22 — exe @0x504ad2 spawn + @0x504a77 think_fn + @0x676d38 effect seq
# =========================================================================
# 无物理 (无 z 落地), 落 cursor → 播放 16 帧火龍 atlas 278 → seq 完 signal IMPACT_2 → damage.
HUOLONG_EFFECT_SEQ: list[tuple] = [
    ('fm', 278, 0, 1), ('fm', 278, 1, 1), ('fm', 278, 2, 1), ('fm', 278, 3, 1),
    ('fm', 278, 4, 1), ('fm', 278, 5, 1), ('fm', 278, 6, 1), ('fm', 278, 7, 1),
    ('fm', 278, 8, 1), ('fm', 278, 9, 1), ('fm', 278, 10, 1), ('fm', 278, 11, 1),
    ('fm', 278, 12, 1), ('fm', 278, 13, 1), ('fm', 278, 14, 1), ('fm', 278, 15, 1),
    ('exit',),
]


def huolong_think_fn(e: "Entity", eng: "Engine") -> None:
    """火龍斬 effect entity. state 0: 等 seq 播完 → SIG_IMPACT_2 + destroy."""
    if e.state_code == PROJ_STATE_EXPLODING and not e.is_playing():
        eng._signal(e, SIG_IMPACT_2)
        eng._signal(e, SIG_END)
        eng.destroy(e)
        e.state_code = PROJ_STATE_DONE


def spawn_huolong_effect(battle, attacker, target_tile: tuple[int, int]) -> "Entity":
    """spawn 火龍斬 effect (无物理, 直接 cursor 上 attach 16 帧动画).
    Effect seq 完成时 think_fn 发 SIG_IMPACT_2 → 结算伤害.
    """
    from core.sprites.base import TILE_W, TILE_H
    from core.anim_engine.bytecode import tuple_to_bytecode
    eng = battle.engine

    tx, ty = target_tile
    e = eng.spawn(think_fn=huolong_think_fn)
    e.x = (tx * TILE_W + TILE_W // 2) * FP_ONE
    e.y = (ty * TILE_H + TILE_H // 2) * FP_ONE
    e.z = 0
    e.vx = e.vy = e.vz = 0
    e.atlas_slot = 278
    e.frame_idx = 0
    e.flags |= 0x40
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
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
POTIAN_SECONDARY_SEQ: list[tuple] = [
    ('fm', 279, 0, 5), ('fm', 279, 1, 4), ('fm', 279, 2, 3), ('fm', 279, 3, 3),
    ('fm', 279, 4, 3), ('fm', 279, 5, 3), ('fm', 279, 6, 3), ('fm', 279, 7, 3),
    ('fm', 279, 8, 3),
    ('exit',),
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
SECONDARY_PHASE_TICKS = 29
SCATTER_PHASE_TICKS = 38
SCATTER_INITIAL_OFFSET_PX = 600     # exe 0x2580000 = 600 << 16
SCATTER_TOWARD_STEP_PX = 1          # spring step size (per-tick velocity delta)

# Coordinator state codes (复用 PROJ_STATE_* 命名空间)
_POTIAN_PHASE_SECONDARY = 30        # spawn N secondaries, 等 29 ticks
_POTIAN_PHASE_CASTER_DASH = 31      # caster 跑 cdit1_g0 (前突+蓄力+斩), 等 IMPACT 信号
_POTIAN_PHASE_SCATTER = 32          # spawn 2 scatter + 1 trajectory per victim, 等 38 ticks
_POTIAN_PHASE_DAMAGE = 33           # 发 SIG_IMPACT_2 → 默认伤害路径


def potian_passive_effect_think(e: "Entity", eng: "Engine") -> None:
    """secondary / trajectory / scatter effect 共用: seq 完即销毁, 无副作用."""
    if e.state_code == PROJ_STATE_EXPLODING and not e.is_playing():
        eng.destroy(e)
        e.state_code = PROJ_STATE_DONE


def potian_scatter_think(e: "Entity", eng: "Engine") -> None:
    """scatter effect: exe mode 0x31 物理 (toward-target spring) + seq 同步播.
    target 在 user_data, step_x/step_y 是 spring 加速度."""
    if e.state_code == PROJ_STATE_EXPLODING:
        if not e.is_playing():
            eng.destroy(e)
            e.state_code = PROJ_STATE_DONE
            return
        # spring 物理: vx += sign(target.x - x) * step_x; x += vx
        target_x = e.user_data.get('target_x', e.x)
        target_y = e.user_data.get('target_y', e.y)
        step_x = e.user_data.get('step_x', SCATTER_TOWARD_STEP_PX * FP_ONE)
        step_y = e.user_data.get('step_y', SCATTER_TOWARD_STEP_PX * FP_ONE)
        e.vx += step_x if e.x < target_x else -step_x
        e.vy += step_y if e.y < target_y else -step_y
        e.x += e.vx
        e.y += e.vy


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
            eng._signal(e, SIG_IMPACT_2)
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
        _potian_spawn_scatter_phase(coord, eng)
        coord.user_data['phase_ticks'] = 0
        coord.state_code = _POTIAN_PHASE_SCATTER
        return
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
    e = eng.spawn(think_fn=potian_passive_effect_think)
    tx, ty = tile_xy
    e.x = (tx * TILE_W + TILE_W // 2) * FP_ONE
    e.y = (ty * TILE_H + TILE_H // 2) * FP_ONE
    e.z = 0
    e.atlas_slot = 279
    e.frame_idx = 0
    e.flags |= 0x40
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.state_code = PROJ_STATE_EXPLODING
    eng.attach_seq(e, tuple_to_bytecode(POTIAN_SECONDARY_SEQ))
    return e


def _spawn_potian_scatter_one(battle, victim_tile: tuple[int, int],
                              vx_sign: int, vy_sign: int, frame_idx: int) -> "Entity":
    """scatter effect: 从 victim+offset 飞向 victim, 初速度随机, atlas 279 frame 9 或 10."""
    from core.sprites.base import TILE_W, TILE_H
    from core.anim_engine.bytecode import tuple_to_bytecode
    eng = battle.engine
    rng = battle.rng

    tx, ty = victim_tile
    target_x = (tx * TILE_W + TILE_W // 2) * FP_ONE
    target_y = (ty * TILE_H + TILE_H // 2) * FP_ONE

    # 起始 = target + offset 600px on x AND y (exe spawn_fn A 的 +0x2580000)
    e = eng.spawn(think_fn=potian_scatter_think)
    e.x = target_x + SCATTER_INITIAL_OFFSET_PX * FP_ONE * vx_sign
    e.y = target_y + SCATTER_INITIAL_OFFSET_PX * FP_ONE * vy_sign
    e.z = 0
    # 初速度 = -(random+1) * vx_sign * 0x10000 (exe: (rand >> 10 + 1) * sign_step,
    # rand & 0x3ff ∈ [0,1023] 取 >> 10 = 0, 所以基本就是 ±0x10000 = ±1 px/tick).
    # 我们用 1..3 px/tick 随机, 视觉散布感更明显.
    e.vx = -vx_sign * rng.randint(1, 3) * FP_ONE
    e.vy = -vy_sign * rng.randint(1, 3) * FP_ONE
    e.vz = 0
    e.atlas_slot = 279
    e.frame_idx = frame_idx
    e.flags |= 0x40
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.user_data['target_x'] = target_x
    e.user_data['target_y'] = target_y
    e.user_data['step_x'] = SCATTER_TOWARD_STEP_PX * FP_ONE
    e.user_data['step_y'] = SCATTER_TOWARD_STEP_PX * FP_ONE
    e.state_code = PROJ_STATE_EXPLODING
    # 单帧 hold 整个生命周期 — exe 里 scatter effect 不播 seq, 静态 frame.
    eng.attach_seq(e, tuple_to_bytecode([('fm', 279, frame_idx, SCATTER_PHASE_TICKS), ('exit',)]))
    return e


def _spawn_potian_trajectory(battle, victim_tile: tuple[int, int]) -> "Entity":
    """trajectory: atlas 292 12 帧 在 victim 头顶播放 (主要视觉)."""
    from core.sprites.base import TILE_W, TILE_H
    from core.anim_engine.bytecode import tuple_to_bytecode
    eng = battle.engine
    e = eng.spawn(think_fn=potian_passive_effect_think)
    tx, ty = victim_tile
    e.x = (tx * TILE_W + TILE_W // 2) * FP_ONE
    e.y = (ty * TILE_H + TILE_H // 2) * FP_ONE
    e.z = 0
    e.atlas_slot = 292
    e.frame_idx = 0
    e.flags |= 0x40
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.state_code = PROJ_STATE_EXPLODING
    eng.attach_seq(e, tuple_to_bytecode(POTIAN_TRAJ_SEQ))
    return e


def _potian_spawn_scatter_phase(coord: "Entity", eng: "Engine") -> None:
    """coordinator 进 PHASE_SCATTER 时调: per victim spawn 2 scatter + 1 trajectory."""
    battle = coord.user_data['battle']
    victims = coord.user_data['victim_tiles']
    for vt in victims:
        # 2 个 scatter: 一个从 (-x, +y) 方向, 一个从 (+x, +y) 方向 (exe 第二个 spawn vx_sign=+)
        _spawn_potian_scatter_one(battle, vt, vx_sign=-1, vy_sign=+1, frame_idx=9)
        _spawn_potian_scatter_one(battle, vt, vx_sign=+1, vy_sign=+1, frame_idx=10)
        # 1 个 trajectory at victim
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

    # Per victim 立即 spawn secondary
    for vt in victims:
        _spawn_potian_secondary(battle, vt)

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
    coord.user_data['phase_ticks'] = 0
    coord.state_code = _POTIAN_PHASE_SECONDARY
    return coord
