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


def spawn_cloudwave_projectile(battle, attacker, defender) -> "Entity":
    """spawn 赤雲波 投射物 — 从屏幕顶外正上方坠落到 defender (= "天降红云").
    无水平运动, 仿原版 spawn_fn 只启 Z 轴 (mode flag bit 6).
    """
    from core.sprites.base import TILE_W, TILE_H
    eng = battle.engine

    spawn_x_px = defender.x * TILE_W + TILE_W // 2
    spawn_y_px = defender.y * TILE_H + TILE_H // 2

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
