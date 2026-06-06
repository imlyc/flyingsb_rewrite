"""孙悟空变身技能演出框架 (skill 0x00..0x09).

exe dispatcher (e.g. 大金刚 FUN_004f460a) 是多阶段变身演出, 我们用 coordinator entity
驱动 caster 的翻跟头隐现 + 神兽 spawn + AOE 伤害 + 收尾.

演出流程 (对应 exe state 流):
  FLIP_OUT: caster 翻跟头 (ps_CSON105 0..7) + emong 烟雾 → 翻完 caster 隐身
  TRANSFORM:   变身形态攻击阶段 (L1 占位: 直接 AOE 伤害; 后续接 eson01 从天而降逐敌)
  FLIP_IN:  caster 现身 + 翻跟头 (0..7) + emong → 翻完
  DONE:     post_attack_anim 收尾 + 销毁 coordinator

caster 变身期间不走标准 attack seq (caster.entity 不 attach skill seq), 全由 coordinator
控制 cast_flip_frame / cast_hidden. coordinator 标 projectile=True 让 units_animating 看到,
防回合提前结束.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.anim_engine.entity import SIG_END

if TYPE_CHECKING:
    from core.anim_engine.engine import Engine
    from core.anim_engine.entity import Entity

FP_ONE = 0x10000

# 哪些 skill 走孙悟空变身演出. L1 先做大金刚, 逐个加.
SON_TRANSFORM_SKILLS: set[int] = {0x00}

# coordinator 状态码 (避开 20 = PROJ_STATE_DONE, units_animating 用它判投射物结束)
_FLIP_OUT = 100
_TRANSFORM = 110
_FLIP_IN = 120
_DONE = 130

FLIP_HOLD_TICKS = 3        # 翻跟头每帧 hold (8 帧 × 3 = 24 tick ≈ 720ms)
TRANSFORM_TICKS = 40          # 变身形态攻击阶段时长 (占位, 后续 eson01 下落逐敌取代)
SOMERSAULT_N = 8           # ps_CSON105 8 帧

# emong 烟雾 (atlas 248). 真实用法 (exe 0x670ff0[0..2] + FUN_004f3558/34f6):
# 不是单个大烟雾, 而是撒 N 个随机小烟雾粒子, 每个随机选 3 段之一 (frames 0-5/6-11/12-17),
# 随机位置散布在 caster 周围, 每帧配向上 move (-1→-3 加速) = 冒泡上升. 多粒子叠加 = 浓烟消散.
EMONG_ATLAS = 248
EMONG_BODY_CENTER_PX = 45     # 烟雾起始 z 抬到角色身体中心
SMOKE_COUNT = 12              # 每次撒的烟雾粒子数 (exe 每 tick 4 个撒几 tick, 我们一次撒一批)
_EMONG_UP_MOVE = (1, 2, 2, 2, 2, 3)   # 每帧后向上位移 (px), exe 0x670ff0 加速上升


def _emong_seg(base: int) -> list[tuple]:
    """emong 一段 (6 帧 base..base+5) + 逐帧向上飘 move (exe 0x670ff0 单段)."""
    seq: list[tuple] = []
    for i in range(6):
        seq.append(('fm', EMONG_ATLAS, base + i, 1))
        seq.append(('move', 0, -_EMONG_UP_MOVE[i], 1))
    seq.append(('move', 0, -3, 1))
    seq.append(('exit',))
    return seq


EMONG_SEGS = [_emong_seg(0), _emong_seg(6), _emong_seg(12)]   # 3 段随机选


def _spawn_smoke(battle, caster) -> None:
    """在 caster 周围撒 SMOKE_COUNT 个随机 emong 烟雾粒子 (随机段 + 随机位置 + 向上飘)."""
    from core.sprites.base import TILE_W, TILE_H
    from core.anim_engine.bytecode import tuple_to_bytecode
    rng = battle.rng
    cx = caster.x * TILE_W + TILE_W // 2
    cy = caster.y * TILE_H + TILE_H // 2
    for _ in range(SMOKE_COUNT):
        seg = EMONG_SEGS[rng.randint(0, 2)]
        ox = rng.randint(-TILE_W // 3, TILE_W // 3)   # caster 周围 ±~21px 散布
        oy = rng.randint(-8, 8)
        e = battle.engine.spawn()
        e.x = (cx + ox) << 16
        e.y = (cy + oy) << 16
        e.z = -(EMONG_BODY_CENTER_PX + rng.randint(-12, 12)) << 16
        e.user_data['kind'] = 'hit_effect'
        battle.engine.attach_seq(e, tuple_to_bytecode(seg))


def son_transform_think(e: "Entity", eng: "Engine") -> None:
    """孙悟空变身 coordinator. 驱动翻跟头隐现 + 神兽 + 伤害 + 收尾."""
    if 'caster' not in e.user_data:
        return  # spawn 时的 init call (state=-1, user_data 未设), 跳过
    caster = e.user_data['caster']
    battle = e.user_data['battle']

    if e.state_code == _FLIP_OUT:
        e.user_data['flip_tick'] += 1
        if e.user_data['flip_tick'] >= FLIP_HOLD_TICKS:
            e.user_data['flip_tick'] = 0
            e.user_data['flip_idx'] += 1
            idx = e.user_data['flip_idx']
            if idx >= SOMERSAULT_N:
                # 翻跟头消失完 → 落地噗烟 (exe state 0x14 在翻跟头 cast seq 之后撒) + 隐身
                caster.cast_flip_frame = None
                caster.cast_hidden = True
                _spawn_smoke(battle, caster)
                e.state_code = _TRANSFORM
                spawn_eson01_attack(battle, caster, e)   # eson01 从天而降逐敌
            else:
                caster.cast_flip_frame = idx
    elif e.state_code == _TRANSFORM:
        # eson01 神兽砸完所有 victim (eson_done) → caster 现身翻跟头出现
        if e.user_data.get('eson_done'):
            caster.cast_hidden = False
            caster.cast_flip_frame = 0
            e.user_data['flip_idx'] = 0
            e.user_data['flip_tick'] = 0
            _spawn_smoke(battle, caster)
            e.state_code = _FLIP_IN
    elif e.state_code == _FLIP_IN:
        e.user_data['flip_tick'] += 1
        if e.user_data['flip_tick'] >= FLIP_HOLD_TICKS:
            e.user_data['flip_tick'] = 0
            e.user_data['flip_idx'] += 1
            idx = e.user_data['flip_idx']
            if idx >= SOMERSAULT_N:
                caster.cast_flip_frame = None
                e.state_code = _DONE
            else:
                caster.cast_flip_frame = idx
    elif e.state_code == _DONE:
        # 收尾: 清状态 + post_attack (回合结束流程) + 销毁 coord
        caster.cast_flip_frame = None
        caster.cast_hidden = False
        caster.pending_caster_coord = None
        eng._signal(e, SIG_END)
        eng.destroy(e)
        battle.post_attack_anim(caster)


# ============ eson01 神兽下落逐敌攻击 (exe FUN_004f4545 → think FUN_004f4288) ============
# eson01 (atlas 254) 从高空下落砸第一个 victim → 落地伤害 → (停顿) → 抛物线跳向下一个 victim
# 再砸 → 砸完所有 victim → 升空消失 → 通知 coordinator 进翻跟头出现.
#
# 严格还原 exe FUN_004f4288 状态机 + 物理积分器 FUN_004c3211 (全 16.16 fixed, 单位 px):
#   - 天降下落 (mode 0x41, 仅 z): 从 victim 上方 0x2bc=700px 起, 匀速 vz=-40 (无重力), 落到 z=0.
#   - 落地 (z<1): 发伤害(-200)+命中特效(-250), z=0, **设 +0x14=20 tick 等待计时器** → state 5.
#   - 落地停顿 (state 5): 空等 20 tick 才进 state 10 (原版刻意的蓄势/命中强调).
#   - 跳向下一敌 (state 10 → mode 0x71): 水平 vx=dx/0x28=dx/40 线性匀速;
#     垂直 vz=+0x28=40 上抛 + 重力 0x2=2px/tick² → 抛物线弧 (峰高 ~380px, 历时 ~40 tick),
#     落回 z<1 再砸. 水平除数 40 与弧线 tick 数同步 (2*vz/g = 2*40/2 = 40).
#   - 全砸完 (state 10 else): vz 取反匀速升空, mode 0x41, z>700 时发 -100(eson_done) + 自毁.
#
# 我们的 z 约定与 exe 反向 (负 z = 上空, 落地 z=0, 下落 = z 增大). 速度/重力符号相应翻转.
ESON01_ATLAS = 254
ESON_SKY_HEIGHT_PX = 700       # 天降起始高度 (exe 0x2bc)
ESON_DESCEND_VZ = 40           # 天降下落 / 终末升空 匀速 px/tick (exe 0x28, 无重力)
ESON_SLAM_HOLD_TICKS = 20      # 落地砸中后停顿 tick (exe +0x144+0x14)
ESON_LEAP_VZ = 40              # 跳跃初始上抛速度 px/tick (exe 0x28)
ESON_LEAP_GRAVITY = 2          # 跳跃重力 px/tick² (exe 0x2)
# 弧线历时 = 2*vz/g, 水平匀速除数与之同步 (exe 用 /0x28 = /40, 与 vz=40,g=2 的 40 tick 弧一致)
ESON_LEAP_TICKS = 2 * ESON_LEAP_VZ // ESON_LEAP_GRAVITY

_ESON_DESCEND = 200          # 天降下落 (避开 20=PROJ_DONE / 100+=coord state)
_ESON_PAUSE = 203            # 落地停顿
_ESON_LEAP = 205             # 抛物线跳向下一敌
_ESON_RISE = 210             # 终末升空


def _eson_collect_victims(battle, caster) -> list:
    """从 _pending_damage_range 收集范围内敌人 (eson01 逐个砸)."""
    victims = []
    dmg = getattr(battle, '_pending_damage_range', None)
    if dmg:
        for (x, y) in dmg:
            occ = battle.q.occupant(x, y)
            if occ is not None and occ.alive and occ.is_player != caster.is_player:
                victims.append(occ)
    else:
        t = caster.pending_attack_target
        if t is not None and t.alive:
            victims.append(t)
    return victims


def _victim_ground(victim) -> tuple[int, int]:
    """victim 脚下 tile 中心的 (x, y) 16.16 坐标."""
    from core.sprites.base import TILE_W, TILE_H
    return ((victim.x * TILE_W + TILE_W // 2) << 16,
            (victim.y * TILE_H + TILE_H // 2) << 16)


def _eson_position_above(e: "Entity", victim) -> None:
    """把 eson01 放到 victim 正上方高空 (准备天降下落)."""
    e.x, e.y = _victim_ground(victim)
    e.z = -ESON_SKY_HEIGHT_PX << 16          # 负 z = 上空


def _eson_hit(battle, caster, victim) -> None:
    """eson01 落地砸中 victim: 造成伤害阶段 (依次进行).
    扣血 + 受击反应 + 飘字 + hit-fx 立即生效 (范围攻击不转向), 但标 settle_pending
    抑制虚弱/死亡视觉, 等所有 victim 砸完后 _eson_settle_all 统一释放 (伤害结算同时进行)."""
    if not victim.alive:
        return
    from core.battle import combat
    combat._roll_damage_one(battle, caster, victim, face_attacker=False)
    # apply_damage 已设 settle_pending + shown_hp_override (逻辑 hp 即扣, 显示/视觉延迟).
    # 额外标 settle_batch: 不在自己飘字 flash 时结算, 等全砸完批量统一结算 (= 最后一个敌人受击结束).
    victim.settle_pending = True
    victim.settle_batch = True


def _eson_settle_all(victims) -> None:
    """伤害结算阶段 (同时进行): eson01 全部砸完后统一释放延迟结算.
    所有受害者同时解除抑制 (HP 显示更新 + 虚弱/死亡视觉放行) → 死亡的同步开始死亡动画."""
    for v in victims:
        if not (v.settle_pending or v.settle_batch):
            continue
        v.release_hp_display()   # 存活 → 显示真实 hp; 死亡 → 保留旧值 (不显 0)
        v.settle_damage()        # 解除 settle_pending/settle_batch (虚弱/死亡视觉放行)
        # 死亡者绕过逐发飘字门控, 同一 tick 一起开始死亡动画 (保证同步).
        if not v.alive and v.death_anim_time_ms < 0:
            v.death_anim_time_ms = 0


def _eson_land(e: "Entity") -> None:
    """落地砸中当前 victim: 切砸地帧 + 伤害 + 启动停顿计时 → _ESON_PAUSE (exe state 0→5)."""
    ud = e.user_data
    e.z = 0
    e.frame_idx = 0                          # exe: 落地切 frame 0 (举臂收势)
    _eson_hit(ud['battle'], ud['caster'], ud['victims'][ud['idx']])
    ud['pause_tick'] = 0
    e.state_code = _ESON_PAUSE


def _eson_start_leap(e: "Entity", victim) -> None:
    """砸完一个 victim 后, 设置抛物线跳向下一个 victim (exe state 10, mode 0x71)."""
    ud = e.user_data
    tx, ty = _victim_ground(victim)
    # 水平: 线性匀速, dx/ESON_LEAP_TICKS per tick (exe /0x28). 终点落地 (z=0).
    ud['leap_vx'] = (tx - e.x) // ESON_LEAP_TICKS
    ud['leap_vy'] = (ty - e.y) // ESON_LEAP_TICKS
    ud['leap_tx'] = tx
    ud['leap_ty'] = ty
    # 垂直: 上抛 (我们约定上空 = 负 z, 故初速 -LEAP_VZ; 重力 +GRAVITY 把它拉回 z=0).
    e.vz = -ESON_LEAP_VZ << 16
    e.frame_idx = 0                          # 上升时 frame 0 (exe: vz>=1 → frame 0)
    e.state_code = _ESON_LEAP


def eson01_attack_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'victims' not in ud:
        return  # init call

    if e.state_code == _ESON_DESCEND:
        # 天降匀速下落 (exe mode 0x41, 无重力), 落地砸.
        e.z += ESON_DESCEND_VZ << 16
        e.frame_idx = 1                      # 下落 = 砸地帧 (exe: vz<1 → frame 1)
        if e.z >= 0:
            _eson_land(e)

    elif e.state_code == _ESON_PAUSE:
        # 落地停顿 (exe state 5: 空等 20 tick 才动), 停顿期保持砸地姿 frame 0.
        ud['pause_tick'] += 1
        if ud['pause_tick'] >= ESON_SLAM_HOLD_TICKS:
            ud['idx'] += 1
            if ud['idx'] >= len(ud['victims']):
                # 全砸完 → 升空 (exe state 10 else: vz 取反匀速升).
                e.vz = -ESON_DESCEND_VZ << 16
                e.frame_idx = 0
                e.state_code = _ESON_RISE
            else:
                _eson_start_leap(e, ud['victims'][ud['idx']])

    elif e.state_code == _ESON_LEAP:
        # 抛物线跳向下一敌: 水平线性 + 垂直上抛受重力 (exe mode 0x71).
        e.x += ud['leap_vx']
        e.y += ud['leap_vy']
        e.vz += ESON_LEAP_GRAVITY << 16      # 重力把上抛速度拉回 (我们约定 +z = 下)
        e.z += e.vz
        e.frame_idx = 1 if e.vz > 0 else 0   # 下落段砸地帧, 上升段举臂帧
        if e.vz > 0 and e.z >= 0:            # 弧线落回地面 → 砸下一敌
            e.x, e.y = ud['leap_tx'], ud['leap_ty']
            _eson_land(e)

    elif e.state_code == _ESON_RISE:
        # 终末升空匀速 (exe mode 0x41), 升过 700px 高空 → 通知 coordinator + 自毁.
        e.z += e.vz
        if (e.z >> 16) <= -ESON_SKY_HEIGHT_PX:
            _eson_settle_all(ud['victims'])     # 全砸完升空到顶 → 同时结算
            ud['coord'].user_data['eson_done'] = True
            eng.destroy(e)


def spawn_eson01_attack(battle, caster, coord: "Entity") -> None:
    """变身形态攻击: spawn eson01 从天而降逐个砸 victim. 砸完设 coord.eson_done=True."""
    coord.user_data['eson_done'] = False
    victims = _eson_collect_victims(battle, caster)
    if not victims:
        coord.user_data['eson_done'] = True   # 无敌人, 直接跳过
        return
    e = battle.engine.spawn(think_fn=eson01_attack_think)
    e.atlas_slot = ESON01_ATLAS
    e.frame_idx = 1                           # 天降即砸地姿
    e.flags |= 0x40
    e.vz = 0
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['coord'] = coord
    e.user_data['victims'] = victims
    e.user_data['idx'] = 0
    _eson_position_above(e, victims[0])
    e.state_code = _ESON_DESCEND


def start_son_transform(battle, caster, target_tile, skill_id: int) -> "Entity":
    """启动孙悟空变身 coordinator. caster 不走标准 attack seq, 全由 coord 控制.
    调用前 confirm_attack_aim 已设好 caster.pending_* + battle._pending_damage_range."""
    from core.sprites.base import TILE_W, TILE_H
    eng = battle.engine
    e = eng.spawn(think_fn=son_transform_think)
    e.flags = 0x800 | 0x10000           # alive + has-think-fn, 不渲染 (无 visible bit)
    e.x = (target_tile[0] * TILE_W + TILE_W // 2) << 16
    e.y = (target_tile[1] * TILE_H + TILE_H // 2) << 16
    e.z = 0
    e.user_data['kind'] = 'son_transform_coord'
    e.user_data['projectile'] = True    # 让 units_animating 看到, 防回合提前结束
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['skill_id'] = skill_id
    e.user_data['flip_idx'] = 0
    e.user_data['flip_tick'] = 0
    e.user_data['phase_ticks'] = 0
    e.state_code = _FLIP_OUT
    # caster 起手翻跟头 (烟雾在翻跟头落地后才撒, 见 FLIP_OUT 翻完处).
    caster.cast_flip_frame = 0
    caster.pending_caster_coord = e
    return e


def is_son_transform_skill(skill_id: int | None) -> bool:
    return skill_id is not None and skill_id in SON_TRANSFORM_SKILLS
