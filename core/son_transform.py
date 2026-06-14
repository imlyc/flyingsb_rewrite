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

# 孙悟空 10 技能 (0x00..0x09) 全走变身演出. 变身阶段每技能召唤各自神兽 (exe 各有独立
# spawn/think fn, 全 dump 在 reverse_engineering/). 神兽配置:
#   ('eson01',)        大金刚: eson01 大猩猩逐敌砸 (atlas 254, FUN_004f4288)
#   ('sweep', atlas, n) 青龙/白虎/朱雀/玄武/月兔/凤凰: 神兽从高空下落到 AOE 中心 → 范围伤害 → 升空
#                       (exe 各 beast 从屏幕顶 fixed-pos 下落 FUN_004f4c62 等; 我们用世界 z 下落简化)
#   ('aoe',)           酷酷猫/分身术/超亂舞: 暂用中心范围伤害占位 (TODO: 酷酷猫 eson04a-e 演出 /
#                       分身术 4 分身 FUN_004f3876 / 超亂舞 16 粒子 FUN_004f8188)
SON_BEAST_CONFIG: dict[int, tuple] = {
    0x00: ('eson01',),
    0x01: ('qinglong', 255),    # 青龙 eson02: 盘踞神兽 + 冰锥雨 (见 video 1:00:48)
    0x02: ('sweep', 256, 4),    # 白虎 eson03
    0x03: ('aoe',),             # 酷酷猫 (TODO eson04a-e 257-261)
    0x04: ('aoe',),             # 分身术 (TODO 4 分身)
    0x05: ('sweep', 262, 1),    # 朱雀 eson05
    0x06: ('sweep', 263, 3),    # 玄武 eson06
    0x07: ('sweep', 264, 10),   # 美丽月兔 eson07a
    0x08: ('aoe',),             # 超亂舞 (TODO 16 粒子)
    0x09: ('sweep', 267, 4),    # M凤凰 eson09
}
SON_TRANSFORM_SKILLS: set[int] = set(SON_BEAST_CONFIG)


def _spawn_beast_attack(battle, caster, coord: "Entity") -> None:
    """变身阶段: 按 skill_id 召唤对应神兽攻击. 砸完设 coord.eson_done=True."""
    skill_id = coord.user_data['skill_id']
    cfg = SON_BEAST_CONFIG.get(skill_id, ('aoe',))
    kind = cfg[0]
    if kind == 'eson01':
        spawn_eson01_attack(battle, caster, coord)
    elif kind == 'qinglong':
        spawn_qinglong_beast(battle, caster, coord, cfg[1])
    elif kind == 'sweep':
        spawn_sweep_beast(battle, caster, coord, cfg[1], cfg[2])
    else:
        spawn_aoe_only(battle, caster, coord)

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
                _spawn_beast_attack(battle, caster, e)   # 按 skill 召唤对应神兽
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
        v.commit_hp()            # 提交工作缓冲 → 显示 (存活同步真值; 死亡保留旧值不显 0)
        v.release_death_visual() # 放行 settle_pending/settle_batch (虚弱/死亡视觉)
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


# ============ 通用下落神兽 (青龙/白虎/朱雀/玄武/月兔/凤凰) ============
# exe 各 beast 从屏幕顶 fixed-pos 下落 (FUN_004f4c62 等, 物理 mode 0x41). 我们用世界 z 下落简化:
# 神兽从 AOE 中心高空下落 → 落地对范围内所有敌人**同时**造成伤害 (非大金刚的逐个) → 升空消失.
BEAST_FRAME_TICKS = 3        # 神兽帧动画 tick/帧
BEAST_HOLD_TICKS = 18        # 落地后停留 (展示神兽 + 让命中反应播)
_BEAST_DESCEND = 220
_BEAST_HOLD = 222
_BEAST_RISE = 224


def _beast_animate(e: "Entity") -> None:
    ud = e.user_data
    ud['anim_tick'] += 1
    if ud['anim_tick'] >= BEAST_FRAME_TICKS:
        ud['anim_tick'] = 0
        e.frame_idx = (e.frame_idx + 1) % ud['frame_count']


def _aoe_hit_all(battle, caster, victims) -> None:
    """对所有 victim 同时造成伤害 (同时 AOE: 各自飘字 flash 时结算, 因同 tick 命中 → 同步)."""
    from core.battle import combat
    for v in victims:
        if v.alive:
            combat._roll_damage_one(battle, caster, v, face_attacker=False)


# ============ 神兽落地后对每个 victim 的专属攻击特效 (exe 各 beast 落地后撒粒子) ============
# 神兽落地除了 AOE 伤害, 还在每个 victim 头上**同时撒多个**下落粒子 (组合显示同一 atlas 多帧).
# 青龙 = eice 冰锥 (exe FUN_004d6f6a 撒 frame rand(0-3) 散落 + FUN_004d70fc 主冰锥): 用户确认组合多 fm_EICE.
# 配置: skill_id -> (atlas, (帧候选), 每 victim 粒子数). exe atlas: 朱雀 294=ej3 /
# 玄武 320=eba00 / 月兔 227=ds_chiri. 青龙 eice 是专属冰锥序列 (见 _spawn_qinglong_ice).
# 白虎(beast 自身扑击 atlas6)/凤凰 待做.
SON_BEAST_VICTIM_FX: dict[int, tuple] = {
    0x05: (294, (0,), 4),                   # 朱雀 ej3 火
    0x06: (320, (0, 1), 4),                 # 玄武 eba00 冰柱
    0x07: (227, (8, 9, 10, 11, 12, 13), 4),  # 月兔 ds_chiri
}
PARTICLE_FALL_HEIGHT_PX = 90    # 粒子起始高度 (victim 头上)
PARTICLE_FALL_VZ = 8            # 粒子下落 px/tick
PARTICLE_SCATTER_PX = 22        # 水平散布 ±
PARTICLE_SPLASH_TICKS = 6       # 落地后停留 tick


def beast_particle_think(e: "Entity", eng: "Engine") -> None:
    """神兽攻击粒子 (青龙冰锥等): 从 victim 头上下落, 落地停留后消失."""
    ud = e.user_data
    if 'fall' not in ud:
        return
    if e.state_code == 0:                    # 下落
        e.z += PARTICLE_FALL_VZ << 16
        if e.z >= 0:
            e.z = 0
            ud['splash'] = 0
            e.state_code = 1
    elif e.state_code == 1:                  # 落地停留
        ud['splash'] += 1
        if ud['splash'] >= PARTICLE_SPLASH_TICKS:
            eng.destroy(e)


# ---- 青龙 eice 冰锥序列 (exe FUN_004d6f6a/70fc 冰锥 + FUN_004d6dc3 碎裂) ----
# eice (atlas 300) 帧布局: 0-3=小冰锥 / 28,31,34=大冰锥(主, DAT_00656bb8) / 12-23=碎裂小冰块.
# 流程 (用户确认): 冰锥下落 (0-3 小 / 28/31/34 大) → 落地碎裂为多个小冰块 (12-23) → 大冰锥收尾.
EICE_ATLAS = 300
EICE_CONE_SMALL = (0, 1, 2, 3)          # 小冰锥 (雨)
EICE_CONE_BIG = (28, 31, 34)            # 大冰锥 (主, exe DAT_00656bb8)
EICE_SHATTER = tuple(range(12, 24))     # 碎裂小冰块 (exe rand%0xc+0xc)
ICE_SHARD_HEIGHT = 128                  # 小冰锥起始高度 (exe 0x800000=128px)
ICE_SHARD_VZ = 22                       # 小冰锥下落 px/tick (exe vz≈-24)
ICE_CONE_HEIGHT = 340                   # 大冰锥起始高度 (exe 0x1f40000=500px, 略降以多在屏内)
ICE_CONE_VZ = 30                        # 大冰锥下落 px/tick (exe vz≈-48)
ICE_SHATTER_TICKS = 12                  # 碎块停留 tick (exe think ~0x10)
_ICE_FALL = 0
_ICE_SHATTER = 1


def _spawn_ice_shatter(battle, x, y, big: bool) -> None:
    """冰锥落地碎裂: 撒 N 个小冰块 (frames 12-23), 四散 + 渐隐 (exe FUN_004d6dc3, 大锥6/小锥4)."""
    rng = battle.rng
    n = 6 if big else 4
    for _ in range(n):
        e = battle.engine.spawn(think_fn=ice_shatter_think)
        e.atlas_slot = EICE_ATLAS
        e.frame_idx = EICE_SHATTER[rng.randint(0, len(EICE_SHATTER) - 1)]
        e.flags |= 0x40
        e.x = x + (rng.randint(-10, 10) << 16)
        e.y = y + (rng.randint(-6, 6) << 16)
        e.z = -(rng.randint(0, 12) << 16)
        e.vx = rng.randint(-30000, 30000)
        e.vy = rng.randint(-20000, 20000)
        e.vz = -(rng.randint(10000, 50000))     # 上抛
        e.user_data['kind'] = 'hit_effect'
        e.user_data['projectile'] = True
        e.user_data['shatter'] = True
        e.user_data['tick'] = 0


def ice_shatter_think(e: "Entity", eng: "Engine") -> None:
    """碎冰块: 四散抛物 + 渐隐 (闪烁) 后消失."""
    ud = e.user_data
    if 'shatter' not in ud:
        return
    e.x += e.vx
    e.y += e.vy
    e.vz += 0x6000                        # 重力
    e.z += e.vz
    if e.z > 0:
        e.z = 0
        e.vz = 0
    ud['tick'] += 1
    if ud['tick'] > ICE_SHATTER_TICKS // 2:   # 后半程闪烁 (exe XOR visible)
        e.flags ^= 0x40
    if ud['tick'] >= ICE_SHATTER_TICKS:
        eng.destroy(e)


def ice_cone_think(e: "Entity", eng: "Engine") -> None:
    """冰锥: 下落 → 落地碎裂 (spawn 小冰块) → 自身消失. 大冰锥落地额外对 victim 结算伤害."""
    ud = e.user_data
    if 'cone' not in ud:
        return
    if e.state_code == _ICE_FALL:
        e.z += (ICE_CONE_VZ if ud['big'] else ICE_SHARD_VZ) << 16
        if e.z >= 0:
            e.z = 0
            _spawn_ice_shatter(ud['battle'], e.x, e.y, ud['big'])
            v = ud.get('victim')             # 大冰锥落地结算伤害 (exe FUN_004d70fc think)
            if v is not None and v.alive:
                from core.battle import combat
                combat._roll_damage_one(ud['battle'], ud['caster'], v, face_attacker=False)
            eng.destroy(e)


def _spawn_ice_cone(battle, x, y, height_px, frame, big, victim=None, caster=None) -> None:
    e = battle.engine.spawn(think_fn=ice_cone_think)
    e.atlas_slot = EICE_ATLAS
    e.frame_idx = frame
    e.flags |= 0x40
    e.x = x
    e.y = y
    e.z = -(height_px << 16)
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.user_data['cone'] = True
    e.user_data['big'] = big
    e.user_data['battle'] = battle
    e.user_data['victim'] = victim
    e.user_data['caster'] = caster
    e.state_code = _ICE_FALL


def _spawn_beast_victim_fx(battle, skill_id: int, victims) -> None:
    """神兽落地: 对每个 victim 头上撒专属攻击特效 (朱雀/玄武/月兔. 青龙走专属 beast)."""
    cfg = SON_BEAST_VICTIM_FX.get(skill_id)
    if not cfg:
        return
    atlas, frames, count = cfg
    rng = battle.rng
    for v in victims:
        if not v.alive:
            continue
        vx, vy = _victim_ground(v)
        for _ in range(count):
            e = battle.engine.spawn(think_fn=beast_particle_think)
            e.atlas_slot = atlas
            e.frame_idx = frames[rng.randint(0, len(frames) - 1)]
            e.flags |= 0x40
            e.x = vx + (rng.randint(-PARTICLE_SCATTER_PX, PARTICLE_SCATTER_PX) << 16)
            e.y = vy + (rng.randint(-PARTICLE_SCATTER_PX // 2, PARTICLE_SCATTER_PX // 2) << 16)
            e.z = -((PARTICLE_FALL_HEIGHT_PX + rng.randint(0, 40)) << 16)
            e.user_data['kind'] = 'hit_effect'
            # projectile=True: think_fn 驱动无 seq, 让 hit_effect render 在飞行期也画 (否则不渲染).
            e.user_data['projectile'] = True
            e.user_data['fall'] = True


def sweep_beast_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'victims' not in ud:
        return
    if e.state_code == _BEAST_DESCEND:
        e.z += ESON_DESCEND_VZ << 16
        _beast_animate(e)
        if e.z >= 0:
            e.z = 0
            _spawn_beast_victim_fx(ud['battle'], ud['skill_id'], ud['victims'])  # 冰锥等专属特效
            _aoe_hit_all(ud['battle'], ud['caster'], ud['victims'])
            ud['hold_tick'] = 0
            e.state_code = _BEAST_HOLD
    elif e.state_code == _BEAST_HOLD:
        _beast_animate(e)
        ud['hold_tick'] += 1
        if ud['hold_tick'] >= BEAST_HOLD_TICKS:
            e.state_code = _BEAST_RISE
    elif e.state_code == _BEAST_RISE:
        e.z -= ESON_DESCEND_VZ << 16
        _beast_animate(e)
        if (e.z >> 16) <= -ESON_SKY_HEIGHT_PX:
            ud['coord'].user_data['eson_done'] = True
            eng.destroy(e)


def spawn_sweep_beast(battle, caster, coord: "Entity", atlas: int, frame_count: int) -> None:
    """召唤下落神兽: 从 caster (AOE 中心) 高空下落, 落地对范围敌人同时伤害, 升空消失."""
    coord.user_data['eson_done'] = False
    victims = _eson_collect_victims(battle, caster)
    e = battle.engine.spawn(think_fn=sweep_beast_think)
    e.atlas_slot = atlas
    e.frame_idx = 0
    e.flags |= 0x40
    e.vz = 0
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['coord'] = coord
    e.user_data['victims'] = victims
    e.user_data['skill_id'] = coord.user_data['skill_id']
    e.user_data['frame_count'] = max(1, frame_count)
    e.user_data['anim_tick'] = 0
    e.user_data['hold_tick'] = 0
    e.x, e.y = _victim_ground(caster)        # AOE 中心 = caster tile
    e.z = -ESON_SKY_HEIGHT_PX << 16
    e.state_code = _BEAST_DESCEND


# ============ 青龙: 盘踞神兽 + 冰锥雨 (参考 video flyingsb4.mkv 1:00:48) ============
# 原版: 神兽 (eson02 atlas255) 落到战场中心**盘踞**(coil seq 0,1,2,1 循环), 期间对范围敌人
# 持续撒小冰锥(雨), 末尾大冰锥+伤害, 然后消失. (exe dispatcher state0x28 + beast think FUN_004f4c62)
QL_ATLAS = 255
QL_COIL_FRAMES = (0, 1, 2, 1)   # 盘踞动画 (exe seq 0x671b1c 循环)
QL_COIL_TICKS = 3
QL_DESCEND_HEIGHT = 220         # 神兽进场高度 (较矮, 偏盘踞而非天降)
QL_DESCEND_VZ = 22
# 严格还原 exe dispatcher state 0x28: 神兽落地 → 冰锥雨 100 tick, 每 2 tick 对**每个**敌人撒 1
# 小冰锥, 每 20 tick 对每个敌人触发受击反应 (-250); 雨止后 40 tick 每敌大冰锥落地 + 伤害.
QL_RAIN_TICKS = 100            # 冰锥雨持续 (exe +0x16c = +0x64)
QL_RAIN_INTERVAL = 2          # 每 2 tick 一波 (exe tick%2==0)
QL_REACT_INTERVAL = 20        # 每 20 tick 受击反应 (exe tick%0x14==0)
QL_FINALE_TICKS = 40          # 雨止后到大冰锥 (exe +0x28) + 落地缓冲
_QL_DESCEND = 0
_QL_RAIN = 1
_QL_FINALE = 2
_QL_RISE = 3


def _ql_coil(e: "Entity") -> None:
    ud = e.user_data
    ud['anim_tick'] += 1
    idx = (ud['anim_tick'] // QL_COIL_TICKS) % len(QL_COIL_FRAMES)
    e.frame_idx = QL_COIL_FRAMES[idx]


def _ql_rain_react(battle, caster, victim) -> None:
    """冰锥雨期间的受击反应 (exe -250: 受击动画 + 命中 sparkle, 无伤害)."""
    from core.battle import combat
    if not victim.alive:
        return
    combat.set_reaction(victim, "hit", None)      # 范围攻击不转向
    combat._emit_hit_effect(battle, caster, victim)


def qinglong_beast_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'victims' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    if e.state_code == _QL_DESCEND:
        e.z += QL_DESCEND_VZ << 16
        _ql_coil(e)
        if e.z >= 0:
            e.z = 0
            ud['rain_tick'] = 0
            e.state_code = _QL_RAIN
    elif e.state_code == _QL_RAIN:
        _ql_coil(e)
        ud['rain_tick'] += 1
        t = ud['rain_tick']
        # 冰锥雨: 每 2 tick 对每个敌人撒 1 小冰锥 (从高空落地碎裂)
        if t % QL_RAIN_INTERVAL == 0:
            for v in ud['victims']:
                if not v.alive:
                    continue
                vx, vy = _victim_ground(v)
                _spawn_ice_cone(battle,
                                vx + (battle.rng.randint(-28, 28) << 16),
                                vy + (battle.rng.randint(-8, 16) << 16),
                                ICE_SHARD_HEIGHT + battle.rng.randint(0, 30),
                                EICE_CONE_SMALL[battle.rng.randint(0, 3)], big=False)
        # 每 20 tick 受击反应
        if t % QL_REACT_INTERVAL == 0:
            for v in ud['victims']:
                _ql_rain_react(battle, caster, v)
        if t >= QL_RAIN_TICKS:
            ud['finale_tick'] = 0
            e.state_code = _QL_FINALE
    elif e.state_code == _QL_FINALE:
        _ql_coil(e)
        ud['finale_tick'] += 1
        if ud['finale_tick'] == QL_FINALE_TICKS:
            # 每个敌人头上一个大冰锥 (落地各自结算伤害)
            for v in ud['victims']:
                if v.alive:
                    vx, vy = _victim_ground(v)
                    _spawn_ice_cone(battle, vx, vy + (4 << 16), ICE_CONE_HEIGHT,
                                    EICE_CONE_BIG[battle.rng.randint(0, 2)], big=True,
                                    victim=v, caster=caster)
        if ud['finale_tick'] >= QL_FINALE_TICKS + 18:   # 等大冰锥落地结算后升空
            e.state_code = _QL_RISE
    elif e.state_code == _QL_RISE:
        e.z -= QL_DESCEND_VZ << 16
        _ql_coil(e)
        if (e.z >> 16) <= -QL_DESCEND_HEIGHT:
            ud['coord'].user_data['eson_done'] = True
            eng.destroy(e)


def spawn_qinglong_beast(battle, caster, coord: "Entity", atlas: int) -> None:
    """青龙: 神兽落到中心盘踞 + 持续冰锥雨 + 末尾大冰锥伤害."""
    coord.user_data['eson_done'] = False
    victims = _eson_collect_victims(battle, caster)
    e = battle.engine.spawn(think_fn=qinglong_beast_think)
    e.atlas_slot = atlas
    e.frame_idx = 0
    e.flags |= 0x40
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['coord'] = coord
    e.user_data['victims'] = victims
    e.user_data['anim_tick'] = 0
    e.user_data['rain_tick'] = 0
    e.x, e.y = _victim_ground(caster)        # 战场中心 = caster tile
    e.z = -QL_DESCEND_HEIGHT << 16
    e.state_code = _QL_DESCEND


# ============ AOE 占位 (酷酷猫/分身术/超亂舞, 待做专属演出) ============
_AOE_HOLD = 230


def aoe_only_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'victims' not in ud:
        return
    if e.state_code == _AOE_HOLD:
        ud['hold_tick'] += 1
        if ud['hold_tick'] == 1:
            _aoe_hit_all(ud['battle'], ud['caster'], ud['victims'])
        if ud['hold_tick'] >= BEAST_HOLD_TICKS:
            ud['coord'].user_data['eson_done'] = True
            eng.destroy(e)


def spawn_aoe_only(battle, caster, coord: "Entity") -> None:
    """占位: 中心范围伤害 (无神兽视觉). 酷酷猫/分身术/超亂舞 后续接专属演出."""
    coord.user_data['eson_done'] = False
    victims = _eson_collect_victims(battle, caster)
    e = battle.engine.spawn(think_fn=aoe_only_think)
    e.flags = 0x800 | 0x10000                # 不渲染 (无 visible bit)
    e.user_data['kind'] = 'son_aoe'
    e.user_data['projectile'] = True
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['coord'] = coord
    e.user_data['victims'] = victims
    e.user_data['hold_tick'] = 0
    e.state_code = _AOE_HOLD


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
