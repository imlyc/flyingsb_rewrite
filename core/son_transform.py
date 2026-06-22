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
    0x02: ('baihu', 256),       # 白虎 eson03: 盘踞神兽 + 旋风 (以风击退敌人, ehari00 旋涡)
    0x03: ('kukumao', 257),     # 酷酷猫 eson04a-e: 笑脸猫五段演出 + 解异常 (治疗类, 解异常暂占位)
    0x04: ('fenshen', 2),       # 分身术 eson: 孙悟空(cson_e0)分 4 身 上下左右各攻击, 末身结算 AOE
    0x05: ('zhuque', 262),      # 朱雀 eson05: 红凤凰悬空 + 火雨 ("以火攻击敌人")
    0x06: ('xuanwu', 263),      # 玄武 eson06: 盘踞神兽 + 地震 (屏幕震动) + 每敌冰柱 eba00/01
    0x07: ('yuetu', 264),       # 美丽月兔 eson07a/b: 召唤线条魔画 + 星光弹幕 (ds_chiri)
    0x08: ('luanwu',),          # 超亂舞: 施法(ps_CSON102) → 16 滑板满天飞 (eson08) + 周期受击 + 末尾伤害
    0x09: ('mfeng', 267),       # M凤凰 eson09: 复活术 (治疗类!) 全队复活回满 + 羽毛光点
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
    elif kind == 'baihu':
        spawn_baihu_beast(battle, caster, coord, cfg[1])
    elif kind == 'zhuque':
        spawn_zhuque_beast(battle, caster, coord, cfg[1])
    elif kind == 'xuanwu':
        spawn_xuanwu_beast(battle, caster, coord, cfg[1])
    elif kind == 'yuetu':
        spawn_yuetu_beast(battle, caster, coord, cfg[1])
    elif kind == 'mfeng':
        spawn_mfeng_beast(battle, caster, coord, cfg[1])
    elif kind == 'kukumao':
        spawn_kukumao_beast(battle, caster, coord)
    elif kind == 'sweep':
        spawn_sweep_beast(battle, caster, coord, cfg[1], cfg[2])
    else:
        spawn_aoe_only(battle, caster, coord)

# coordinator 状态码 (避开 20 = PROJ_STATE_DONE, units_animating 用它判投射物结束)
_CAST = 90               # 翻跟斗前的简短施法姿 (ps_CSON102 最后两列)
_FLIP_OUT = 100
_TRANSFORM = 110
_FLIP_IN = 120
_DONE = 130

# 施法姿: ps_CSON102 方向行 (0=上/背,1=下/正,2=左,3=右) 的最后两列 (col 2,3).
CAST_POSE_COLS = (2, 3)
CAST_POSE_FRAME_TICKS = 6      # 每帧 tick (简短)
_FACING_TO_CSON_ROW = {(0, -1): 0, (0, 1): 1, (-1, 0): 2, (1, 0): 3}


def _caster_cson_row(caster) -> int:
    """caster 朝向 → ps_CSON102/cson 方向行."""
    return _FACING_TO_CSON_ROW.get(tuple(getattr(caster, 'facing', (0, 1))), 1)

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


def _spawn_smoke_at(battle, world_x: int, world_y: int, count: int = None) -> None:
    """在像素坐标 (world_x, world_y) 周围撒 emong 烟雾粒子 (随机段 + 随机位置 + 向上飘)."""
    from core.sprites.base import TILE_W
    from core.anim_engine.bytecode import tuple_to_bytecode
    rng = battle.rng
    n = SMOKE_COUNT if count is None else count
    for _ in range(n):
        seg = EMONG_SEGS[rng.randint(0, 2)]
        ox = rng.randint(-TILE_W // 3, TILE_W // 3)
        oy = rng.randint(-8, 8)
        e = battle.engine.spawn()
        e.x = (world_x + ox) << 16
        e.y = (world_y + oy) << 16
        e.z = -(EMONG_BODY_CENTER_PX + rng.randint(-12, 12)) << 16
        e.user_data['kind'] = 'hit_effect'
        battle.engine.attach_seq(e, tuple_to_bytecode(seg))


def _spawn_smoke(battle, caster) -> None:
    """在 caster 周围撒 SMOKE_COUNT 个随机 emong 烟雾粒子."""
    from core.sprites.base import TILE_W, TILE_H
    _spawn_smoke_at(battle, caster.x * TILE_W + TILE_W // 2, caster.y * TILE_H + TILE_H // 2)


def son_transform_think(e: "Entity", eng: "Engine") -> None:
    """孙悟空变身 coordinator. 驱动翻跟头隐现 + 神兽 + 伤害 + 收尾."""
    if 'caster' not in e.user_data:
        return  # spawn 时的 init call (state=-1, user_data 未设), 跳过
    caster = e.user_data['caster']
    battle = e.user_data['battle']

    if e.state_code == _CAST:
        # 翻跟斗前简短施法姿: ps_CSON102 最后两列 (col 2 → 3), 各 CAST_POSE_FRAME_TICKS
        e.user_data['flip_tick'] += 1
        if e.user_data['flip_tick'] >= CAST_POSE_FRAME_TICKS:
            e.user_data['flip_tick'] = 0
            e.user_data['cast_pose_idx'] += 1
            ci = e.user_data['cast_pose_idx']
            if ci >= len(CAST_POSE_COLS):
                if e.user_data['skill_id'] == 0x08:
                    # 超亂舞: 保持施法姿(定格末帧), 不翻跟斗; spawn 16 滑板满天飞
                    caster.cast_pose_frame = e.user_data['cast_row'] * 4 + CAST_POSE_COLS[-1]
                    spawn_luanwu(battle, caster, e)
                    e.state_code = _TRANSFORM
                else:
                    # 0x04 分身: 施法完 → 起手翻跟头
                    caster.cast_pose_frame = None
                    caster.cast_flip_frame = 0
                    e.user_data['flip_idx'] = 0
                    e.state_code = _FLIP_OUT
            else:
                caster.cast_pose_frame = e.user_data['cast_row'] * 4 + CAST_POSE_COLS[ci]
    elif e.state_code == _FLIP_OUT:
        e.user_data['flip_tick'] += 1
        if e.user_data['flip_tick'] >= FLIP_HOLD_TICKS:
            e.user_data['flip_tick'] = 0
            e.user_data['flip_idx'] += 1
            idx = e.user_data['flip_idx']
            if idx >= SOMERSAULT_N:
                if e.user_data['skill_id'] == 0x04:
                    # 分身术: 孙悟空**原地翻跟斗不隐藏**, 对每敌召唤 4 分身围攻 (exe FUN_004f3ca3)
                    e.user_data['flip_idx'] = 0
                    e.user_data['flip_tick'] = 0
                    caster.cast_flip_frame = 0
                    spawn_fenshen(battle, caster, e)
                    e.state_code = _TRANSFORM
                else:
                    # 翻跟头消失完 → 落地噗烟 (exe state 0x14 在翻跟头 cast seq 之后撒) + 隐身
                    caster.cast_flip_frame = None
                    caster.cast_hidden = True
                    _spawn_smoke(battle, caster)
                    e.state_code = _TRANSFORM
                    _spawn_beast_attack(battle, caster, e)   # 按 skill 召唤对应神兽
            else:
                caster.cast_flip_frame = idx
    elif e.state_code == _TRANSFORM:
        if e.user_data['skill_id'] == 0x08:
            # 超亂舞: 孙悟空保持施法姿, 等滑板打完 (eson_done) → 收尾 (不翻跟斗/不隐身)
            if e.user_data.get('eson_done'):
                caster.cast_pose_frame = None
                e.state_code = _DONE
            return
        if e.user_data['skill_id'] == 0x04:
            # 分身术: 孙悟空原地**循环翻跟斗**, 等所有分身打完退场 (eson_done) → 收尾
            e.user_data['flip_tick'] += 1
            if e.user_data['flip_tick'] >= FLIP_HOLD_TICKS:
                e.user_data['flip_tick'] = 0
                e.user_data['flip_idx'] = (e.user_data['flip_idx'] + 1) % SOMERSAULT_N
                caster.cast_flip_frame = e.user_data['flip_idx']
            if e.user_data.get('eson_done'):
                caster.cast_flip_frame = None
                e.state_code = _DONE
            return
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
        caster.cast_pose_frame = None
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


def _screen_center(battle, caster) -> tuple[int, int]:
    """满屏/战场中心特效的本体位置 (x, y) 16.16.

    优先用可见屏幕中心 (BattleScene 每帧发布的 battle.view_center_world). 否则施法者靠
    地图/相机边缘时相机会 clamp, 施法者不在屏幕中心, 把神兽/特效锚在施法者格会让整体
    偏到半屏 (超亂舞滑板/盘踞神兽等都有此问题). headless 无 UI 时回退到施法者格.
    伤害目标由 _eson_collect_victims 按 caster+AOE 收集, 与本体位置无关, 故纯视觉安全."""
    view = getattr(battle, 'view_center_world', None)
    if view is not None:
        return (view[0] << 16, view[1] << 16)
    return _victim_ground(caster)


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
    e.user_data['draw_order'] = 10            # 神兽本体盖在命中特效之上
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
    e.user_data['draw_order'] = 10            # 神兽本体盖在命中特效之上
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['coord'] = coord
    e.user_data['victims'] = victims
    e.user_data['skill_id'] = coord.user_data['skill_id']
    e.user_data['frame_count'] = max(1, frame_count)
    e.user_data['anim_tick'] = 0
    e.user_data['hold_tick'] = 0
    e.x, e.y = _screen_center(battle, caster)        # AOE 中心 = caster tile
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
    e.user_data['draw_order'] = 10            # 青龙本体盖在冰锥之上 (用户要求)
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['coord'] = coord
    e.user_data['victims'] = victims
    e.user_data['anim_tick'] = 0
    e.user_data['rain_tick'] = 0
    e.x, e.y = _screen_center(battle, caster)        # 战场中心 = caster tile
    e.z = -QL_DESCEND_HEIGHT << 16
    e.state_code = _QL_DESCEND


# ============ 白虎: 盘踞神兽 + 旋风 (技能描述: 化身白虎以风击退敌人. video flyingsb6 3:15) ============
# 原版: 白虎神兽 (eson03 atlas256) 落到中心盘踞 (coil seq 0x671b48 = 帧 0,1,2,3,1); 对每个敌人
# 卷起**旋风/龙卷** — exe FUN_004da929 用 ehari00 (atlas295) 旋涡环, 按高度分帧组叠成竖直旋转柱;
# 敌人被风**击退/抖动** (弹簧物理). 我们: 每敌持续从脚下升起 ehari00 旋涡环堆成旋风柱 + 受击抖动.
BH_ATLAS = 256
BH_COIL_FRAMES = (0, 1, 2, 3, 1)   # exe seq 0x671b48
BH_DESCEND_HEIGHT = 220
BH_DESCEND_VZ = 22
BH_ATTACK_TICKS = 80             # 阶段1: 浮到风高度+旋转+旋风 (exe tick 8~0x78)
BH_FLING_TICKS = 14              # 阶段2: 抛向天空 (exe 0x77<tick<0x8c 强力上推 +0x40000)
BH_FALL_MAX_TICKS = 110          # 落下兜底上限 (抛出屏外, 落回耗时较长)
BH_WIND_INTERVAL = 4            # 每 4 tick 每敌升一对旋涡环 (exe tick%4)
# 敌人被风吹起 (exe FUN_004da9ed): 阶段1浮到风高度(z<0x64=100), 阶段2强力抛飞, 落地结算伤害.
BH_WIND_HEIGHT = 82            # 阶段1风高度 px
BH_LIFT_ACCEL = 0.55           # 阶段1上吹加速 (exe 0x21999)
BH_LIFT_GRAVITY = 0.5          # 重力 (exe spring accel 0x20000)
BH_FLING_ACCEL = 2.6           # 阶段2强力上推 (exe 0x40000, 远大于阶段1) → 抛出屏顶 (峰 ~570px)
BH_FALL_GRAVITY = 1.1          # 落下重力 (比上吹重力大, 摔得干脆)
# 腾空旋转: 切 idle row4 4 列(朝向) = 绕中轴线转. exe seq 0x656ef8 帧序 16,19,17,18 = 列 0,3,1,2
# = UP,RIGHT,DOWN,LEFT (direction_cols UP=0/DOWN=1/LEFT=2/RIGHT=3), 每帧 3 tick.
BH_SPIN_COLS = (0, 3, 1, 2)
BH_SPIN_FRAME_TICKS = 3
WIND_ATLAS = 295                 # ehari00 旋涡环
# ehari00 21 帧 = 旋涡环由大到小. exe 按高度 8 段 (每 16px) 选环: **低=小环(18-20), 高=大环(0-2)**.
WIND_BANDS = (
    (18, 19, 20), (15, 16, 17), (12, 13, 14), (9, 10, 11),
    (6, 7, 8), (3, 4, 5), (0, 1, 2), (0, 1, 2),
)
WIND_BAND_PX = 16                # 每段 16px (exe (z>>16)>>4)
WIND_TOP = 128                   # 旋风柱总高 (8 段 × 16, exe z>0x80 消失)
WIND_RING_VZ = 6                # 旋涡环上升 px/tick
WIND_RADIUS = 17                 # 旋涡环绕敌人半径 px
_BH_DESCEND = 0
_BH_ATTACK = 1
_BH_FLING = 2
_BH_FALL = 3
_BH_RISE = 4


def whirlwind_ring_think(e: "Entity", eng: "Engine") -> None:
    """旋涡环: 从敌人脚下升起, 按高度换环大小 (低小高大) + 旋转, 升到顶消失. 双股螺旋叠成旋风柱."""
    ud = e.user_data
    if 'ring' not in ud:
        return
    e.z -= WIND_RING_VZ << 16            # 上升 (我们约定上空 = 负 z)
    ud['life'] += 1
    h = -(e.z >> 16)                     # 当前高度 px
    band = min(7, max(0, h // WIND_BAND_PX))
    e.frame_idx = WIND_BANDS[band][(ud['life'] // 2) % 3]
    if h >= WIND_TOP:
        eng.destroy(e)


def _spawn_wind_pair(battle, vx, vy, phase) -> None:
    """在敌人两侧 (相位差 180°) 各升一个旋涡环 = 两股风; phase 每次旋转 → 双螺旋."""
    import math
    for dphase in (0.0, math.pi):
        a = phase + dphase
        ox = int(math.cos(a) * WIND_RADIUS) << 16
        oy = int(math.sin(a) * WIND_RADIUS * 0.4) << 16   # 椭圆 (俯视透视)
        e = battle.engine.spawn(think_fn=whirlwind_ring_think)
        e.atlas_slot = WIND_ATLAS
        e.frame_idx = WIND_BANDS[0][0]
        e.flags |= 0x40
        e.x = vx + ox
        e.y = vy + oy
        e.z = 0
        e.user_data['kind'] = 'hit_effect'
        e.user_data['projectile'] = True
        e.user_data['ring'] = True
        e.user_data['life'] = 0


def _bh_update_airborne(ud, mode: str) -> bool:
    """更新每个 victim 腾空 + 旋转. mode: 'float'=浮到风高度 / 'fling'=强力抛飞 / 'fall'=只重力落下.
    返回是否全部已落地 (FALL 阶段判结算)."""
    lifts = ud.setdefault('lift_vz', {})
    ud['spin_phase'] = ud.get('spin_phase', 0) + 1
    spin_col = BH_SPIN_COLS[(ud['spin_phase'] // BH_SPIN_FRAME_TICKS) % 4]   # 切朝向 = 转
    all_landed = True
    for v in ud['victims']:
        if not v.alive:
            continue
        vz = lifts.get(id(v), 0.0)
        if mode == 'float':
            if v.wind_lift < BH_WIND_HEIGHT:
                vz += BH_LIFT_ACCEL
            vz -= BH_LIFT_GRAVITY
        elif mode == 'fling':
            vz += BH_FLING_ACCEL
            vz -= BH_LIFT_GRAVITY
        else:                                  # fall (重力更大, 摔得干脆)
            vz -= BH_FALL_GRAVITY
        v.wind_lift = max(0.0, v.wind_lift + vz)
        if v.wind_lift <= 0.0:
            vz = 0.0
            v.wind_spin_col = -1               # 落地 → 停转 (恢复正常朝向渲染)
        else:
            all_landed = False
            v.wind_spin_col = spin_col          # 腾空 → 绕中轴线切朝向旋转
        lifts[id(v)] = vz
    return all_landed


def baihu_beast_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'victims' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    if e.state_code == _BH_DESCEND:
        e.z += BH_DESCEND_VZ << 16
        _bh_coil(e)
        if e.z >= 0:
            e.z = 0
            ud['atk_tick'] = 0
            e.state_code = _BH_ATTACK
    elif e.state_code == _BH_ATTACK:                  # 阶段1: 浮到风高度 + 旋转 + 旋风
        _bh_coil(e)
        ud['atk_tick'] += 1
        t = ud['atk_tick']
        _bh_update_airborne(ud, 'float')
        ud['phase'] += 0.4                            # 双螺旋相位旋转
        if t % BH_WIND_INTERVAL == 0:                 # 两股风: 每敌两侧各升旋涡环
            for v in ud['victims']:
                if v.alive:
                    vx, vy = _victim_ground(v)
                    _spawn_wind_pair(battle, vx, vy, ud['phase'])
        # 注: 阶段1(浮+旋转)无受击特效; 受击/命中特效只在最后摔落地面时由 _aoe_hit_all 触发 (用户确认)
        if t >= BH_ATTACK_TICKS:
            ud['fling_tick'] = 0
            e.state_code = _BH_FLING
    elif e.state_code == _BH_FLING:                   # 阶段2: 抛向天空
        _bh_coil(e)
        ud['fling_tick'] += 1
        _bh_update_airborne(ud, 'fling')
        if ud['fling_tick'] >= BH_FLING_TICKS:
            ud['fall_tick'] = 0
            e.state_code = _BH_FALL
    elif e.state_code == _BH_FALL:                    # 落下 → 落地结算伤害
        _bh_coil(e)
        ud['fall_tick'] += 1
        landed = _bh_update_airborne(ud, 'fall')
        if landed or ud['fall_tick'] >= BH_FALL_MAX_TICKS:
            for v in ud['victims']:
                v.wind_lift = 0.0
                v.wind_spin_col = -1
            _aoe_hit_all(battle, caster, ud['victims'])   # 摔地受伤 (exe z<1 发 -200/-250)
            e.state_code = _BH_RISE
    elif e.state_code == _BH_RISE:
        e.z -= BH_DESCEND_VZ << 16
        _bh_coil(e)
        if (e.z >> 16) <= -BH_DESCEND_HEIGHT:
            for v in ud['victims']:
                v.wind_lift = 0.0                     # 安全复位
                v.wind_spin_col = -1
            ud['coord'].user_data['eson_done'] = True
            eng.destroy(e)


def _bh_coil(e: "Entity") -> None:
    ud = e.user_data
    ud['anim_tick'] += 1
    e.frame_idx = BH_COIL_FRAMES[(ud['anim_tick'] // QL_COIL_TICKS) % len(BH_COIL_FRAMES)]


def spawn_baihu_beast(battle, caster, coord: "Entity", atlas: int) -> None:
    """白虎: 神兽落到中心盘踞 + 利爪连击 (爪痕 + 抖动) + 末尾伤害."""
    coord.user_data['eson_done'] = False
    victims = _eson_collect_victims(battle, caster)
    e = battle.engine.spawn(think_fn=baihu_beast_think)
    e.atlas_slot = atlas
    e.frame_idx = 0
    e.flags |= 0x40
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.user_data['draw_order'] = 10            # 神兽本体盖在爪痕之上
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['coord'] = coord
    e.user_data['victims'] = victims
    e.user_data['anim_tick'] = 0
    e.user_data['atk_tick'] = 0
    e.user_data['phase'] = 0.0
    e.x, e.y = _screen_center(battle, caster)
    e.z = -BH_DESCEND_HEIGHT << 16
    e.state_code = _BH_DESCEND


# ============ 朱雀: 红凤凰悬空 + 火雨 (exe FUN_004f6764 beast + FUN_004f663a 火 + FUN_004f65c7) ============
# 原版: 朱雀神兽 (eson05 atlas262, 大红凤凰单帧) 落到中心**悬空**; 悬停 0x80(128)tick 期间每 8 tick 从
# 高空(z=0x280=640px)在中心周围随机落下 1 颗火球 (ej3 atlas294 帧60), 火球落地 (z<1) 挂火爆 seq
# 0x655fa4 (fire01 atlas309 帧0-10) 燃烧; 火雨止后结算 AOE 伤害; 凤凰升空消失.
ZHUQUE_ATLAS = 262             # eson05 红凤凰 (1 帧)
ZHUQUE_DESCEND_HEIGHT = 250    # 进场高度
ZHUQUE_HOVER_HEIGHT = 96       # 悬空高度 (飞行神兽, 不落地)
ZHUQUE_DESCEND_VZ = 18
ZHUQUE_FIRE_TICKS = 128        # 火雨持续 (exe +0x80)
ZHUQUE_FIRE_INTERVAL = 8       # 每 8 tick 落 1 颗火 (exe tick%8)
ZHUQUE_FIRE_END_MARGIN = 30    # 结束前 0x1e tick 停撒 (exe timer-0x1e)
ZHUQUE_FINALE_TICKS = 18       # 末尾让最后的火烧完
FIREBALL_ATLAS = 294           # ej3 帧60 = 下落火球
FIREBALL_FRAME = 60
FIRE_BURST_ATLAS = 309         # fire01 帧0-10 = 落地火焰爆
FIRE_FALL_HEIGHT = 360         # 火球起始高度 (exe 640, 略降)
FIRE_FALL_VZ = 30              # 火球下落 px/tick (exe 48)
FIRE_SCATTER_X = 112           # 火雨水平散布 (exe rand%0x80)
FIRE_SCATTER_Y = 42
_ZQ_DESCEND = 0
_ZQ_HOVER = 1
_ZQ_FINALE = 2
_ZQ_RISE = 3


def _spawn_fire_burst(battle, x, y) -> None:
    """火球落地: 火焰爆 (fire01 帧0-10, seq 跑完自动回收) — exe seq 0x655fa4."""
    from core.anim_engine.bytecode import tuple_to_bytecode
    seq = [('fm', FIRE_BURST_ATLAS, f, 1) for f in range(11)] + [('exit',)]
    e = battle.engine.spawn()
    e.x = x
    e.y = y
    e.z = 0
    e.user_data['kind'] = 'hit_effect'
    battle.engine.attach_seq(e, tuple_to_bytecode(seq))


def fire_rain_think(e: "Entity", eng: "Engine") -> None:
    """下落火球: 从高空落下, 落地 → 火焰爆 + 自身消失 (exe FUN_004f65c7)."""
    ud = e.user_data
    if 'fire' not in ud:
        return
    e.z += FIRE_FALL_VZ << 16
    if e.z >= 0:
        e.z = 0
        _spawn_fire_burst(ud['battle'], e.x, e.y)
        eng.destroy(e)


def _spawn_fireball(battle, cx, cy) -> None:
    rng = battle.rng
    e = battle.engine.spawn(think_fn=fire_rain_think)
    e.atlas_slot = FIREBALL_ATLAS
    e.frame_idx = FIREBALL_FRAME
    e.flags |= 0x40
    e.x = cx + (rng.randint(-FIRE_SCATTER_X, FIRE_SCATTER_X) << 16)
    e.y = cy + (rng.randint(-FIRE_SCATTER_Y, FIRE_SCATTER_Y) << 16)
    e.z = -((FIRE_FALL_HEIGHT + rng.randint(0, 60)) << 16)
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.user_data['fire'] = True
    e.user_data['battle'] = battle


def zhuque_beast_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'victims' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    if e.state_code == _ZQ_DESCEND:
        e.z += ZHUQUE_DESCEND_VZ << 16
        if e.z >= -(ZHUQUE_HOVER_HEIGHT << 16):     # 降到悬空高度 (仍在空中)
            e.z = -(ZHUQUE_HOVER_HEIGHT << 16)
            ud['fire_tick'] = 0
            e.state_code = _ZQ_HOVER
    elif e.state_code == _ZQ_HOVER:
        ud['fire_tick'] += 1
        t = ud['fire_tick']
        if t % ZHUQUE_FIRE_INTERVAL == 0 and t < ZHUQUE_FIRE_TICKS - ZHUQUE_FIRE_END_MARGIN:
            cx, cy = _victim_ground(caster)         # 朱雀火雨以**施法者**为中心展开 (exe FUN_004f663a 用 DAT_00869c44 施法者坐标+随机偏移, 非屏幕中心)
            _spawn_fireball(battle, cx, cy)
        if t >= ZHUQUE_FIRE_TICKS:
            _aoe_hit_all(battle, caster, ud['victims'])   # 火雨止 → AOE 伤害
            ud['finale_tick'] = 0
            e.state_code = _ZQ_FINALE
    elif e.state_code == _ZQ_FINALE:
        ud['finale_tick'] += 1
        if ud['finale_tick'] >= ZHUQUE_FINALE_TICKS:
            e.state_code = _ZQ_RISE
    elif e.state_code == _ZQ_RISE:
        e.z -= ZHUQUE_DESCEND_VZ << 16
        if (e.z >> 16) <= -(ZHUQUE_HOVER_HEIGHT + ZHUQUE_DESCEND_HEIGHT):
            ud['coord'].user_data['eson_done'] = True
            eng.destroy(e)


def spawn_zhuque_beast(battle, caster, coord: "Entity", atlas: int) -> None:
    """朱雀: 红凤凰落到中心悬空 + 火雨 + AOE 伤害 + 升空."""
    coord.user_data['eson_done'] = False
    victims = _eson_collect_victims(battle, caster)
    e = battle.engine.spawn(think_fn=zhuque_beast_think)
    e.atlas_slot = atlas
    e.frame_idx = 0
    e.flags |= 0x40
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.user_data['draw_order'] = 10            # 凤凰本体盖在火雨之上
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['coord'] = coord
    e.user_data['victims'] = victims
    e.x, e.y = _screen_center(battle, caster)
    e.z = -(ZHUQUE_DESCEND_HEIGHT << 16)
    e.state_code = _ZQ_DESCEND


# ============ 玄武: 盘踞神兽 + 地震 (屏幕震动) + 每敌冰柱 (exe FUN_004f6f63 + FUN_004dc42f) ============
# 原版: 玄武神兽 (eson06 atlas263) 落到中心盘踞 (coil seq DAT_00671c68 = 帧0,1,2 ticks 8/8/15 循环);
# 落地即触发**地震** FUN_004d8c81(10,10,1000) = 相机每 tick 随机抖 ±10px (FUN_004d8b0c). 盘踞 0x80(128)
# tick; 结束前 0x1e(30) tick 对**每个**敌人头顶砸**落石** (FUN_004dc42f, eba00/eba01 随机). 到时停
# 地震 + 升空. 落石 (FUN_004dc371): 从上空匀速落下 → 落地 (音效+受击反应) → 碎裂成一片乱石 → 伤害.
# ⚠ eba00/eba01 是**石块** (非冰): 帧0=完整石头, 帧1..n=砸地碎成多块不同形状的散石 (用户确认: 落多形状石).
XW_ATLAS = 263
XW_COIL_FRAMES = ((0, 8), (1, 8), (2, 15))   # exe seq DAT_00671c68 (帧, ticks), 循环
XW_DESCEND_HEIGHT = 220
XW_DESCEND_VZ = 22
XW_COIL_TICKS = 128             # 盘踞总时长 (exe +0x190 = +0x80)
XW_ROCK_LEAD = 30              # 结束前砸落石 (exe frame == end - 0x1e)
XW_SHAKE_AMP = 10               # 地震振幅 px (exe FUN_004d8c81(10,10,...))
# 落石 (eba): exe 600px 上空匀速落下 (vz=-64); 这里降高度保证在屏内. 每敌砸多块不同形状石.
XW_ROCK_VARIANTS = (320, 321)             # eba00 (小石→小碎堆) / eba01 (大石→大范围散石) 随机
XW_ROCK_LAND_FRAMES = {320: (1, 2, 3), 321: (1, 2, 3, 4)}   # 落地碎裂帧 (exe land seq, 碎成多石)
XW_ROCK_HEIGHT = 220            # 落石起始高度 px (exe 0x258=600, 降以多在屏内)
XW_ROCK_VZ = 24                 # 落石下落 px/tick (exe vz=-64)
XW_ROCK_FRAME_TICKS = 2         # 碎裂帧 tick (exe land seq ticks=2)
_XW_DESCEND = 0
_XW_COIL = 1
_XW_RISE = 2
_XW_ROCK_FALL = 0
_XW_ROCK_SHATTER = 1


def _xw_coil(e: "Entity") -> None:
    """玄武盘踞动画: 帧 0,1,2 各 ticks 8/8/15, 循环 (exe seq DAT_00671c68)."""
    ud = e.user_data
    ud['anim_tick'] += 1
    total = sum(t for _, t in XW_COIL_FRAMES)
    t = ud['anim_tick'] % total
    acc = 0
    for frame, ticks in XW_COIL_FRAMES:
        acc += ticks
        if t < acc:
            e.frame_idx = frame
            return


def falling_rock_think(e: "Entity", eng: "Engine") -> None:
    """玄武落石 (eba00/01): 从上空匀速落下 → 落地 (受击反应) → 碎成多石帧动画 → 结算伤害 (exe FUN_004dc371)."""
    ud = e.user_data
    if 'rock' not in ud:
        return
    battle, caster, victim = ud['battle'], ud['caster'], ud['victim']
    if e.state_code == _XW_ROCK_FALL:
        e.z += XW_ROCK_VZ << 16
        if e.z >= 0:
            e.z = 0
            # 落地: 受击反应 (exe -250, 无伤害, 范围攻击不转向) + 切碎裂首帧
            _ql_rain_react(battle, caster, victim)
            land = XW_ROCK_LAND_FRAMES[ud['variant']]
            ud['land_frames'] = land
            ud['land_idx'] = 0
            ud['land_tick'] = 0
            e.frame_idx = land[0]
            e.state_code = _XW_ROCK_SHATTER
    elif e.state_code == _XW_ROCK_SHATTER:
        ud['land_tick'] += 1
        if ud['land_tick'] >= XW_ROCK_FRAME_TICKS:
            ud['land_tick'] = 0
            ud['land_idx'] += 1
            if ud['land_idx'] >= len(ud['land_frames']):
                # 碎裂播完: 结算伤害 (exe -200) + 销毁
                if victim.alive:
                    from core.battle import combat
                    combat._roll_damage_one(battle, caster, victim, face_attacker=False)
                eng.destroy(e)
                return
            e.frame_idx = ud['land_frames'][ud['land_idx']]


def _spawn_rock_fall(battle, caster, victim) -> None:
    """对 victim 头顶砸 1 块落石 (exe FUN_004dc42f). 随机 eba00/eba01 → 不同敌人石块形状/大小不同."""
    variant = XW_ROCK_VARIANTS[battle.rng.randint(0, 1)]
    vx, vy = _victim_ground(victim)
    e = battle.engine.spawn(think_fn=falling_rock_think)
    e.atlas_slot = variant
    e.frame_idx = 0                          # 下落帧 = 完整石头
    e.flags |= 0x40
    e.x = vx
    e.y = vy
    e.z = -(XW_ROCK_HEIGHT << 16)
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.user_data['rock'] = True
    e.user_data['variant'] = variant
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['victim'] = victim
    e.state_code = _XW_ROCK_FALL


def xuanwu_beast_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'victims' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    if e.state_code == _XW_DESCEND:
        e.z += XW_DESCEND_VZ << 16
        _xw_coil(e)
        if e.z >= 0:
            e.z = 0
            ud['coil_tick'] = 0
            ud['rocks_spawned'] = False
            e.state_code = _XW_COIL
    elif e.state_code == _XW_COIL:
        _xw_coil(e)
        # 地震: 相机每 tick 随机抖 ±AMP (exe FUN_004d8b0c)
        amp = XW_SHAKE_AMP
        battle.shake_offset = (battle.rng.randint(-amp, amp), battle.rng.randint(-amp, amp))
        ud['coil_tick'] += 1
        t = ud['coil_tick']
        # 结束前 LEAD tick: 每敌头顶砸落石 (exe frame == end - 0x1e)
        if not ud['rocks_spawned'] and t >= XW_COIL_TICKS - XW_ROCK_LEAD:
            ud['rocks_spawned'] = True
            for v in ud['victims']:
                if v.alive:
                    _spawn_rock_fall(battle, caster, v)
        if t >= XW_COIL_TICKS:
            battle.shake_offset = (0, 0)         # 停地震 (exe FUN_004d8ce1)
            e.state_code = _XW_RISE
    elif e.state_code == _XW_RISE:
        e.z -= XW_DESCEND_VZ << 16
        _xw_coil(e)
        if (e.z >> 16) <= -XW_DESCEND_HEIGHT:
            ud['coord'].user_data['eson_done'] = True
            eng.destroy(e)


def spawn_xuanwu_beast(battle, caster, coord: "Entity", atlas: int) -> None:
    """玄武: 神兽落到中心盘踞 + 地震 (屏幕震动) + 末尾每敌冰柱 + 伤害 + 升空."""
    coord.user_data['eson_done'] = False
    victims = _eson_collect_victims(battle, caster)
    e = battle.engine.spawn(think_fn=xuanwu_beast_think)
    e.atlas_slot = atlas
    e.frame_idx = 0
    e.flags |= 0x40
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.user_data['draw_order'] = 10            # 玄武本体盖在冰柱之上
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['coord'] = coord
    e.user_data['victims'] = victims
    e.user_data['anim_tick'] = 0
    e.x, e.y = _screen_center(battle, caster)         # 战场中心 = caster tile
    e.z = -XW_DESCEND_HEIGHT << 16
    e.state_code = _XW_DESCEND


# ============ 美丽月兔: 召唤线条魔画 + 星光弹幕 (exe FUN_004f77ab + FUN_004e8192) ============
# 原版: 月兔神兽 (eson07a 264 帧0-9 → eson07b 265 帧0-6, "Beauty rabbit" 华丽线条魔画) 落到中心,
# 循环绘制这幅画; 盘踞 0x80(128)tick; **最后 0x1e(30)tick 每 tick** 对每敌发受击反应(-250) + 撒
# 2 颗星光粒子 (ds_chiri atlas227 frames8-15) + 音效0xd4 = 持续星光弹幕. 到时升空. 伤害末尾统一结算.
YT_ATLAS = 264                  # eson07a (起手)
# 盘踞动画: 264 帧0-9 → 265 帧0-6 循环 (exe seq DAT_00671c8c, 每帧 3 tick). (atlas, frame)
YT_COIL = ([(264, i) for i in range(10)] + [(265, i) for i in range(7)])
YT_COIL_FRAME_TICKS = 3
# 魔画 305x351 锚点(158,156)≈中心; z=0 落地则一半沉到脚下(太低), 140太高 → 取 70 让魔画中心≈屏幕中心.
YT_HOVER_HEIGHT = 70            # 悬空高度 px (魔画中心抬到屏幕中心; 用户校: 0太低/140太高)
YT_DROP = 120                   # 进场下落距离 (从更高处落到悬空高度)
YT_DESCEND_VZ = 22
YT_HOLD_TICKS = 128             # 盘踞总时长 (exe +0x190 = +0x80)
YT_BARRAGE_LEAD = 30            # 最后 30tick 弹幕 (exe end - 0x1e <= frame)
# 弹幕**主视觉 = 大白爆命中特效**: exe 每 tick 对每敌 FUN_004cba90(enemy,-250) → 全局战斗控制器
# SIG_IMPACT_2 命中结算 → 命中特效 (_emit_hit_effect = et00 紫星 + ef010 红刺, 截图里的大白爆).
# 每 tick 连放 → 持续大爆 (单个 320ms, 多个叠加=持续亮). 伤害数字只一次 (起手结算, 后续纯视觉).
# 小碎屑 (ds_chiri) 是配角点缀, 不是主视觉.
YT_SPARKLE_ATLAS = 227
YT_SPARKLE_FRAMES = ((8, 2), (9, 2), (10, 2), (11, 2), (12, 1), (13, 1), (14, 1), (15, 1))  # (帧,ticks)
YT_SPARKLE_HEIGHT = 72          # 起始高度 px (exe victim.z+0x48, 敌人头顶上方)
YT_SPARKLE_VZ = 8               # 上喷初速 px/tick (exe 0x80000)
YT_SPARKLE_GRAVITY = 0.5        # 重力 (exe 0x8000), 上喷后回落
YT_SPARKLE_DX = 1               # 左右分开 px/tick (exe ±0x10000=±1.0)
# 大白爆 = **正常受击特效全套** (pick_hit_effects = et00 紫星 + ef010 红刺, 跟普通命中一样). 用户看视频
# 确认: 弹幕期每 N tick 持续生成正常受击特效, **不断累积叠加而不消失** (et00 紫星 + ef010 红刺都堆),
# 最后一次伤害时全部**一起消失**. 让特效实体持久: 必须带 think_fn (否则 engine.tick sweep 回收无 think
# 的 hit_effect) + projectile=True (seq 播完定格仍渲染). beast 追踪, 末尾统一 destroy.
YT_HIT_INTERVAL = 2             # 每 N tick spawn 一组正常受击特效 (持续累积叠加)
YT_REACT_INTERVAL = 10          # 弹幕期每 N tick 重戳受击反应 (~15tick, 重戳前续上 = 全程持续受击)
_YT_DESCEND = 0
_YT_BARRAGE = 1
_YT_RISE = 2


def _yt_animate(e: "Entity") -> None:
    """月兔盘踞: 264 帧0-9 → 265 帧0-6 循环 (跨 atlas, 每帧 3 tick)."""
    ud = e.user_data
    ud['anim_tick'] += 1
    idx = (ud['anim_tick'] // YT_COIL_FRAME_TICKS) % len(YT_COIL)
    atlas, frame = YT_COIL[idx]
    e.atlas_slot = atlas
    e.frame_idx = frame


def yuetu_sparkle_think(e: "Entity", eng: "Engine") -> None:
    """月兔星光粒子: 升起 + 左右漂移 (含重力) + 播 8 帧闪光 → 完则消失 (exe FUN_004e8152)."""
    ud = e.user_data
    if 'sparkle' not in ud:
        return
    e.x += ud['vx']
    e.vz += int(YT_SPARKLE_GRAVITY * 65536)      # 重力 (z 向下为正 → 抵消上升)
    e.z += e.vz
    ud['frame_tick'] += 1
    cur_frame, cur_ticks = YT_SPARKLE_FRAMES[ud['frame_idx']]
    if ud['frame_tick'] >= cur_ticks:
        ud['frame_tick'] = 0
        ud['frame_idx'] += 1
        if ud['frame_idx'] >= len(YT_SPARKLE_FRAMES):
            eng.destroy(e)
            return
        e.frame_idx = YT_SPARKLE_FRAMES[ud['frame_idx']][0]


def _spawn_yuetu_sparkles(battle, victim) -> None:
    """对 victim 撒 2 颗星光 (左右分开漂移), 从头上方升起 (exe FUN_004e8192 loop ×2)."""
    vx, vy = _victim_ground(victim)
    for i in range(2):
        e = battle.engine.spawn(think_fn=yuetu_sparkle_think)
        e.atlas_slot = YT_SPARKLE_ATLAS
        e.frame_idx = YT_SPARKLE_FRAMES[0][0]
        e.flags |= 0x40
        e.x = vx
        e.y = vy
        # 从敌人头顶一点喷出 (2 颗同起点, 靠 vx 左右分开 = 喷射)
        e.z = -(YT_SPARKLE_HEIGHT << 16)
        e.vz = -(YT_SPARKLE_VZ << 16)            # 上喷 (我们约定上空 = 负 z)
        e.user_data['kind'] = 'hit_effect'
        e.user_data['projectile'] = True
        e.user_data['sparkle'] = True
        e.user_data['draw_order'] = 20           # 画在魔画(10)之上 (魔画是背景线条画, 星光在前)
        e.user_data['vx'] = (YT_SPARKLE_DX if i == 0 else -YT_SPARKLE_DX) << 16
        e.user_data['frame_idx'] = 0
        e.user_data['frame_tick'] = 0


def _yt_hit_persist_think(e: "Entity", eng: "Engine") -> None:
    """空 think: 仅为让累积的受击特效**不被 engine.tick sweep 回收** (sweep 只清无 think 的 hit_effect).
    seq 播完后 projectile=True 让它定格渲染, beast 末尾统一 destroy."""
    return


def _spawn_yuetu_hit(battle, caster, victim, anchors) -> list:
    """对 victim spawn 1 组**正常受击特效** (复用 combat 的 spec/spawn — 与普通命中同一套真值), 但
    实体持久不自毁 (累积叠加). 每敌**第一组随机抖动 ±8px 定锚点, 之后都叠在该锚点** (anchors 缓存).
    与普通命中差异仅: 固定锚点(非每次抖) + persist(累积). 返回 entity 列表供末尾清除."""
    from core.battle import combat
    from core.hit_effect_seq import HIT_EFFECT_JITTER_PX, HIT_EFFECT_Y_BASELINE_PX
    from core.sprites.base import TILE_W, TILE_H
    key = id(victim)
    if key not in anchors:               # 第一组: 随机抖动定锚点; 后续复用
        anchors[key] = (battle.rng.randint(-HIT_EFFECT_JITTER_PX, HIT_EFFECT_JITTER_PX),
                        battle.rng.randint(-HIT_EFFECT_JITTER_PX, HIT_EFFECT_JITTER_PX))
    jx, jy = anchors[key]
    cx = victim.x * TILE_W + TILE_W // 2 + jx
    cy = victim.y * TILE_H + TILE_H // 2 - HIT_EFFECT_Y_BASELINE_PX + jy
    out = []
    for spec in combat.hit_effect_specs(victim, caster.name):   # 复用: 受击放哪些特效
        e = combat._spawn_effect_entity(battle, cx, cy, spec,   # 复用: spawn + attach_seq
                                        think_fn=_yt_hit_persist_think,  # 豁免 sweep 回收
                                        persist=True, draw_order=15)
        e.user_data['burst'] = True            # 标记供 beast 末尾统一销毁
        out.append(e)
    return out


def yuetu_beast_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'victims' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    if e.state_code == _YT_DESCEND:
        e.z += YT_DESCEND_VZ << 16
        _yt_animate(e)
        if e.z >= -(YT_HOVER_HEIGHT << 16):        # 落到悬空高度 (仍在空中)
            e.z = -(YT_HOVER_HEIGHT << 16)
            ud['hold_tick'] = 0
            e.state_code = _YT_BARRAGE
    elif e.state_code == _YT_BARRAGE:
        _yt_animate(e)
        ud['hold_tick'] += 1
        t = ud['hold_tick']
        # 最后 LEAD tick: 命中特效持续生成累积 (不消失) + 小碎屑 + **受击反应全程持续** (与特效同时).
        if t >= YT_HOLD_TICKS - YT_BARRAGE_LEAD:
            from core.battle import combat
            since = t - (YT_HOLD_TICKS - YT_BARRAGE_LEAD)
            for v in ud['victims']:
                if not v.alive:
                    continue
                if since % YT_HIT_INTERVAL == 0:
                    ud['bursts'].extend(_spawn_yuetu_hit(battle, caster, v, ud['hit_anchor']))
                if since % YT_REACT_INTERVAL == 0:
                    combat.set_reaction(v, "hit", None)       # 受击反应 (与受击特效/星光同时, 无伤害)
                _spawn_yuetu_sparkles(battle, v)              # 小碎屑点缀 (exe FUN_004e8192)
        if t >= YT_HOLD_TICKS:
            # 最后一次伤害 + 累积的命中特效**全部一起消失**
            _aoe_hit_all(battle, caster, ud['victims'])
            for be in ud['bursts']:
                eng.destroy(be)
            ud['bursts'].clear()
            e.state_code = _YT_RISE
    elif e.state_code == _YT_RISE:
        e.z -= YT_DESCEND_VZ << 16
        _yt_animate(e)
        if (e.z >> 16) <= -(YT_HOVER_HEIGHT + YT_DROP):
            ud['coord'].user_data['eson_done'] = True
            eng.destroy(e)


def spawn_yuetu_beast(battle, caster, coord: "Entity", atlas: int) -> None:
    """美丽月兔: 召唤线条魔画落中心循环绘制 + 末尾星光弹幕 + AOE 伤害 + 升空."""
    coord.user_data['eson_done'] = False
    victims = _eson_collect_victims(battle, caster)
    e = battle.engine.spawn(think_fn=yuetu_beast_think)
    e.atlas_slot = atlas
    e.frame_idx = 0
    e.flags |= 0x40
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.user_data['draw_order'] = 0             # 魔画是**背景**线条画 → 大白爆/星光(后 spawn)画在它之上
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['coord'] = coord
    e.user_data['victims'] = victims
    e.user_data['anim_tick'] = 0
    e.user_data['bursts'] = []                # 累积的命中特效, 末尾统一清除
    e.user_data['hit_anchor'] = {}            # 每敌的受击特效锚点偏移 (首组随机, 后续复用)
    e.x, e.y = _screen_center(battle, caster)         # 战场中心 = caster tile
    e.z = -((YT_HOVER_HEIGHT + YT_DROP) << 16)   # 从高处落到悬空高度
    e.state_code = _YT_DESCEND


# ============ M凤凰: 复活术 (治疗类! 全队复活回满 + 羽毛光点) (exe FUN_004f8ce6 + FUN_004f8bc6) ============
# 原版: 凤凰神兽 (eson09 atlas267 帧0 = 471x339 大凤凰图, 静态无 coil) 从天降到中心悬停; 落地音效0xef;
# hold 0x40(64)tick; 最后 0x1e(30)tick **每 tick** 对**除施法者外的每个队友**撒羽毛光点 (FUN_004f8bc6)
# + 音效0x111; 末尾升空. ⚠目标=**队友(含死者)**非敌人; 技能="将全体人员复原" = 全队复活+回满.
# 羽毛 = e00(atlas247) 帧30-41 (4变体×3帧, 3x3 极小光点), 从队友头顶飘落 (轻重力, ~63tick/落地消失).
MF_ATLAS = 267                  # eson09 帧0 (大凤凰, 静态)
MF_HOVER_HEIGHT = 80            # 悬停高度 px (大凤凰图中心≈屏幕中心; 锚点(207,166))
MF_DROP = 140                   # 进场下落距离
MF_DESCEND_VZ = 22
MF_HOLD_TICKS = 64              # 悬停时长 (exe +0x40)
MF_RISE_OFFSCREEN = 600         # 升空到此高度 px = 大凤凰(471x339)完全离屏 → 才消失 (避免屏内突然消失)
MF_FEATHER_LEAD = 30            # 最后 30tick 撒羽毛 (exe end - 0x1e)
MF_FEATHER_ATLAS = 247          # e00
MF_FEATHER_VARIANTS = ((30, 31, 32), (33, 34, 35), (36, 37, 38), (39, 40, 41))  # 4变体×3帧
MF_FEATHER_FRAME_TICKS = 2      # 羽毛 3 帧循环 tick
MF_FEATHER_HEIGHT = 128         # 羽毛起始高度 px (exe victim.z + 0x80)
MF_FEATHER_GRAVITY = 0.25       # 轻重力 (exe 0x4000)
MF_FEATHER_LIFE = 63            # 羽毛寿命 tick (exe frame > 0x3f) 或落地消失
_MF_DESCEND = 0
_MF_HOLD = 1
_MF_RISE = 2
# 8 朵祥云 (exe FUN_004f899d spawn + FUN_004f88ad think; eson09 帧1-3 = 3 个旋涡云变体, **不是小凤凰**):
# think 三段: 从就近屏外飘入(不横穿)→在大凤凰**两侧 + 多在下半部**散布悬停→主凤凰升空(coord['mf_leave'])
# 后**继续穿到对面**飘出消失. **位置固定不随机** (帧仍随机), 偏左 + 多数下半部前景, 一朵上半部身后.
# (x 偏移 px [相对中心], 高度 px [越大越靠上], draw_order [>10 凤凰前/ <10 凤凰后]).
# 高度 px = 相对施法者地面 (正=上方/负=下方). 大凤凰悬停时占 地面+246 ~ 地面-93;
# 下三分之一 ≈ 地面+20 ~ 地面-93, 故下半部云高度落在此带 (多在地面附近偏下).
MF_CLOUD_POSITIONS = [
    # 左侧 5 朵**聚成一团** (内侧到 ≈-50, 与右簇留约一整朵祥云的距离 ~100px), 下三分之一
    (-155, -20, 12), (-128, 10, 12), (-100, -50, 12), (-74, -5, 12), (-50, -35, 12),
    # 右侧 2 朵**聚在一起** (内侧 ≈+52)
    (52, 0, 12), (102, -40, 12),
    # 上半部 1 朵 (身后, draw_order<凤凰), 左侧 (用户)
    (-95, 170, 9),
]
# eson09 云帧天然 head 朝向 (像素质心): 帧1=右, 帧2/3=左. 用于按云所在侧翻转使 head 朝中心.
MF_CLOUD_FRAME_HEAD_RIGHT = {1}    # 其余 (2,3) head 朝左
MF_CLOUD_SPAWN_EXTRA = 440      # 目标基础上再往同侧外推多少 px = 从同侧屏外飘入
MF_CLOUD_EASE = 0.12            # 飘入趋近系数 (越近越慢 = 减速)
MF_CLOUD_SNAP = 4               # 距目标 <此 px → 转悬停
MF_CLOUD_OUT_ACCEL = 1.5        # 飘出加速 px/tick²
MF_CLOUD_OUT_OFF = 560          # |离中心|>此 px → 销毁
_MFC_IN = 0
_MFC_HOVER = 1
_MFC_OUT = 2


def mfeng_feather_think(e: "Entity", eng: "Engine") -> None:
    """凤凰羽毛光点: 头顶飘落 (左右微飘 + 轻重力) + 3帧循环 → 落地或寿命到消失 (exe FUN_004f8b51)."""
    ud = e.user_data
    if 'feather' not in ud:
        return
    e.x += ud['vx']
    e.vz += int(MF_FEATHER_GRAVITY * 65536)
    e.z += e.vz
    ud['life'] += 1
    # 3 帧循环
    ud['frame_tick'] += 1
    if ud['frame_tick'] >= MF_FEATHER_FRAME_TICKS:
        ud['frame_tick'] = 0
        ud['fi'] = (ud['fi'] + 1) % 3
        e.frame_idx = ud['variant'][ud['fi']]
    if e.z >= 0 or ud['life'] >= MF_FEATHER_LIFE:
        eng.destroy(e)


def _spawn_mfeng_feather(battle, ally) -> None:
    """对 ally 头顶撒 1 个羽毛光点 (随机 4 变体, 小随机速度)."""
    rng = battle.rng
    vx, vy = _victim_ground(ally)
    variant = MF_FEATHER_VARIANTS[rng.randint(0, 3)]
    e = battle.engine.spawn(think_fn=mfeng_feather_think)
    e.atlas_slot = MF_FEATHER_ATLAS
    e.frame_idx = variant[0]
    e.flags |= 0x40
    e.x = vx + (rng.randint(-12, 12) << 16)
    e.y = vy + (rng.randint(-6, 6) << 16)
    e.z = -((MF_FEATHER_HEIGHT + rng.randint(-20, 20)) << 16)
    e.vz = -(rng.randint(0, 2) << 16)            # 轻微上飘起手, 轻重力后落下
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.user_data['feather'] = True
    e.user_data['draw_order'] = 20               # 羽毛在凤凰之上
    e.user_data['variant'] = variant
    e.user_data['vx'] = rng.randint(-1, 1) << 16
    e.user_data['fi'] = 0
    e.user_data['frame_tick'] = 0
    e.user_data['life'] = 0


def _mfeng_revive(battle, targets) -> None:
    """**只复活死亡同伴并回满** (用户确认: 对存活角色无效, 哪怕残血也不加血). 重置死亡/受击视觉状态."""
    from core.battle.data import DamageEvent
    for u in targets:                            # targets = spawn 时捕获的死亡同伴
        u.hp = u.max_hp                          # 满血复活 (hp>0 = alive)
        u.shown_hp_override = None
        u.settle_pending = False
        u.settle_batch = False
        u.death_anim_time_ms = -1                # 取消死亡动画
        u.reaction_seq = None
        u.reaction_frame = None
        u.reaction_saved_facing = None
        battle.damage_events.append(DamageEvent(u.hp, u.hp, u.x, u.y, heal=True))


def mfeng_cloud_think(e: "Entity", eng: "Engine") -> None:
    """祥云: 飘入趋近散布目标(减速) → 悬停 → (主凤凰升空后)向外加速飘出销毁 (exe FUN_004f88ad)."""
    ud = e.user_data
    if 'cloud' not in ud:
        return
    if e.state_code == _MFC_IN:
        dx = ud['target_x'] - e.x
        e.x += int(dx * MF_CLOUD_EASE)                # 趋近 = 越近越慢 (减速飘入)
        if abs(dx) <= (MF_CLOUD_SNAP << 16):
            e.x = ud['target_x']
            e.state_code = _MFC_HOVER
    elif e.state_code == _MFC_HOVER:
        if ud['coord'].user_data.get('mf_leave'):     # 主凤凰升空 → 该散了
            ud['vx'] = 0.0
            e.state_code = _MFC_OUT
    elif e.state_code == _MFC_OUT:
        ud['vx'] += ud['dir_out'] * MF_CLOUD_OUT_ACCEL  # 向外加速飘出
        e.x += int(ud['vx'] * 65536)
        if abs((e.x - ud['center_x']) >> 16) > MF_CLOUD_OUT_OFF:
            eng.destroy(e)


def _spawn_mfeng_clouds(battle, caster, coord) -> None:
    """召唤 8 朵祥云 (位置固定/帧随机): 从同侧屏外飘入停在两侧, 悬停后**继续穿到对面**飘出."""
    cx, cy = _screen_center(battle, caster)
    for off, h, draw_order in MF_CLOUD_POSITIONS:
        side = 1 if off >= 0 else -1                  # 目标在右(+)/左(-)
        spawn_off = off + side * MF_CLOUD_SPAWN_EXTRA  # 同侧再外推 → 从同侧屏外飘入(不横穿)
        e = battle.engine.spawn(think_fn=mfeng_cloud_think)
        e.atlas_slot = MF_ATLAS                       # eson09 帧1-3 = 3 个旋涡云变体
        e.frame_idx = battle.rng.randint(1, 3)        # 帧随机 (用户: 随机帧保留)
        e.flags |= 0x40
        # 朝向: 左侧云 head 朝右(向中心), 右侧云 head 朝左(向中心). 帧天然朝向不符则翻转.
        wants_head_right = (side < 0)                 # 左侧(side<0) → head 朝右
        natural_head_right = e.frame_idx in MF_CLOUD_FRAME_HEAD_RIGHT
        e.user_data['flip_x'] = (wants_head_right != natural_head_right)
        e.x = cx + (spawn_off << 16)
        e.y = cy
        e.z = -(h << 16)
        e.user_data['kind'] = 'hit_effect'
        e.user_data['projectile'] = True
        e.user_data['cloud'] = True
        e.user_data['draw_order'] = draw_order        # 多数 12 (凤凰前); 上半部那朵 9 (凤凰后)
        e.user_data['center_x'] = cx
        e.user_data['target_x'] = cx + (off << 16)
        e.user_data['dir_out'] = -side                # 飘出 = **穿到对面** (悬停后继续运动)
        e.user_data['vx'] = 0.0
        e.user_data['coord'] = coord
        e.state_code = _MFC_IN


def mfeng_beast_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'allies' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    if e.state_code == _MF_DESCEND:
        e.z += MF_DESCEND_VZ << 16
        if e.z >= -(MF_HOVER_HEIGHT << 16):       # 降到悬停高度 (仍在空中)
            e.z = -(MF_HOVER_HEIGHT << 16)
            ud['hold_tick'] = 0
            e.state_code = _MF_HOLD
    elif e.state_code == _MF_HOLD:
        ud['hold_tick'] += 1
        t = ud['hold_tick']
        if t >= MF_HOLD_TICKS - MF_FEATHER_LEAD:
            since = t - (MF_HOLD_TICKS - MF_FEATHER_LEAD)
            if since == 0:
                _mfeng_revive(battle, ud['allies'])   # 只复活死亡同伴回满 (与羽毛同时, 一次)
            for u in ud['allies']:                    # 羽毛只撒在被复活的死亡同伴身上
                _spawn_mfeng_feather(battle, u)
        if t >= MF_HOLD_TICKS:
            ud['coord'].user_data['mf_leave'] = True   # 通知祥云飘出
            e.state_code = _MF_RISE
    elif e.state_code == _MF_RISE:
        e.z -= MF_DESCEND_VZ << 16                # **持续平滑升空** (不冻住; 飞出屏外才消失)
        # 升到完全离屏后, 等祥云也飘出完才收尾 (期间仍继续上升 = 屏外不可见, 无卡顿)
        if (e.z >> 16) <= -MF_RISE_OFFSCREEN:
            clouds = any(s.user_data.get('cloud') for s in eng.entities if (s.flags & 0x800))
            if not clouds:
                ud['coord'].user_data['eson_done'] = True
                eng.destroy(e)


def spawn_mfeng_beast(battle, caster, coord: "Entity", atlas: int) -> None:
    """M凤凰: 大凤凰降到中心悬停 + **只复活死亡同伴回满** + 羽毛光点 + 升空 (复活术, 对存活者无效)."""
    coord.user_data['eson_done'] = False
    party = battle.players if caster.is_player else battle.enemies
    allies = [u for u in party if not u.alive]   # **只取死亡同伴** (复活目标; 存活者无效)
    e = battle.engine.spawn(think_fn=mfeng_beast_think)
    e.atlas_slot = atlas
    e.frame_idx = 0                              # eson09 帧0 = 大凤凰 (静态)
    e.flags |= 0x40
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.user_data['draw_order'] = 10               # 大凤凰图
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['coord'] = coord
    e.user_data['allies'] = allies
    e.x, e.y = _screen_center(battle, caster)            # 中心 = caster tile
    e.z = -((MF_HOVER_HEIGHT + MF_DROP) << 16)   # 从高处降到悬停高度
    e.state_code = _MF_DESCEND
    coord.user_data['mf_leave'] = False
    _spawn_mfeng_clouds(battle, caster, coord)    # 8 朵祥云散布簇拥


# ============ 酷酷猫: 笑脸猫五段演出 + 解异常 (exe FUN_004f5f0d spawn + FUN_004f5ecc think + seq 0x671b80) ============
# 原版: "变成笑容猫, 解除全部的异常状态". 静态居中播放五段动画 (eson04a-e 257-261): 黑剪影→橙猫→
# 逐级放大到大笑脸 (柴郡猫式咧嘴, 末段只剩漂浮的大笑). think 无物理 (静态), seq 播完发-100 销毁.
# ⚠目标=队友(解异常治疗类, 非攻击). **解异常暂占位** (无异常状态系统, 留 _kukumao_cure 钩子).
KUKUMAO_HEIGHT = 90             # 居中高度 px (静态, 笑脸猫显示在屏幕中部)
# seq 0x671b80: eson04a 帧0-4 → b/c/d/e 各(长hold帧0 + 帧1-3快闪). 省略原 sound 289 (wav 未接).
KUKUMAO_SEQ = (
    [('fm', 257, i, 3) for i in range(5)]
    + [('fm', 258, 0, 24)] + [('fm', 258, i, 3) for i in (1, 2, 3)]
    + [('fm', 259, 0, 24)] + [('fm', 259, i, 3) for i in (1, 2, 3)]
    + [('fm', 260, 0, 24)] + [('fm', 260, i, 3) for i in (1, 2, 3)]
    + [('fm', 261, 0, 24)] + [('fm', 261, i, 3) for i in (1, 2, 3)]
    + [('exit',)]
)


def _kukumao_cure(battle, caster) -> None:
    """酷酷猫解除全队异常状态. ⚠目前无异常状态系统 → 占位空操作.
    待加状态系统后, 这里遍历队友清其异常状态字段 (allies = players if caster.is_player else enemies)."""
    return


def kukumao_think(e: "Entity", eng: "Engine") -> None:
    """笑脸猫: 静态播 seq (atlas 自动切 257→261); 播完 → 解异常 + 收尾销毁 (exe FUN_004f5ecc)."""
    ud = e.user_data
    if 'kukumao' not in ud:
        return
    if e.is_playing():
        ud['started'] = True
        return
    if ud.get('started') and not ud['done']:       # 五段演出播完
        ud['done'] = True
        _kukumao_cure(ud['battle'], ud['caster'])    # 解异常 (占位)
        ud['coord'].user_data['eson_done'] = True
        eng.destroy(e)


def spawn_kukumao_beast(battle, caster, coord: "Entity") -> None:
    """酷酷猫: 笑脸猫居中静态播五段演出 + 解异常 (无伤害)."""
    from core.anim_engine.bytecode import tuple_to_bytecode
    coord.user_data['eson_done'] = False
    e = battle.engine.spawn(think_fn=kukumao_think)
    e.flags |= 0x40
    e.x, e.y = _screen_center(battle, caster)             # 屏幕中心 = caster tile
    e.z = -(KUKUMAO_HEIGHT << 16)
    e.user_data['kind'] = 'hit_effect'
    e.user_data['draw_order'] = 10
    e.user_data['kukumao'] = True
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['coord'] = coord
    e.user_data['started'] = False
    e.user_data['done'] = False
    battle.engine.attach_seq(e, tuple_to_bytecode(KUKUMAO_SEQ))


# ============ 超亂舞: 施法 → 16 滑板满天飞 (exe FUN_004f837b/4f82c9 coord + FUN_004f8188/4f803e 滑板) ============
# 原版: 孙悟空施法(ps_CSON102, 同分身念咒) → coordinator spawn 16 滑板(eson08 atlas266, 8方向帧),
# 各随机位置+随机方向飞, **撞屏幕边反弹**(翻向); 每 20tick 全敌受击; 128tick 时结算伤害+滑板全销毁.
LUANWU_SKATE_ATLAS = 266        # eson08 = 滑板孙悟空 (8 帧 = 8 方向)
LUANWU_COUNT = 32
LUANWU_SPEED = 48               # 滑板飞行速度 px/tick (= 原版 exe 0x30=48)
LUANWU_HEIGHT = 48              # 飞行高度 px (exe z=0x300000)
LUANWU_DURATION = 128           # coordinator 总时长 tick (exe frame==0x80)
LUANWU_REACT_INTERVAL = 20      # 每 N tick 全敌受击 (exe frame%0x14)
LUANWU_BOX_HW = 340             # 反弹框半宽 px (绕 cursor 中心 = 满屏飞)
LUANWU_BOX_HH = 200             # 反弹框半高 px
LUANWU_BOUNCE_TURN = 0.5        # **反弹时**额外随机偏转 rad (~±29°) — 打破刚性轨迹不聚团; 平时直线
# eson08 8 方向帧 = **从北顺时针**: 0=上(N) 1=右上 2=右(E) 3=右下 4=下(S) 5=左下 6=左(W) 7=左上.
# (渲染逐帧辨认确认.) 帧 = 飞行速度方向的罗盘扇区, 滑板头朝飞行方向.
_LUANWU_RUN = 240


def _skate_frame(vx: float, vy: float) -> int:
    """飞行速度方向 → eson08 帧 (从北顺时针 45° 一档, 滑板头=飞行方向; 反弹后自动更新)."""
    import math
    ang = math.atan2(vx, -vy)                            # 从北(-y)顺时针的角度
    return round(ang / (math.pi / 4)) % 8


def skateboard_think(e: "Entity", eng: "Engine") -> None:
    """滑板: 直线飞 + 撞反弹框边反向(翻向帧); coordinator 结束(luanwu_done)时销毁 (exe FUN_004f803e)."""
    ud = e.user_data
    if 'skate' not in ud:
        return
    if ud['coord'].user_data.get('luanwu_done'):
        eng.destroy(e)
        return
    e.x += int(ud['vx'] * 65536)                          # 平时直线飞
    e.y += int(ud['vy'] * 65536)
    px, py = e.x >> 16, e.y >> 16
    cx, cy = ud['cx'], ud['cy']
    bounced = False
    if px < cx - LUANWU_BOX_HW or px > cx + LUANWU_BOX_HW:
        ud['vx'] = -ud['vx']                              # 撞左右边反弹
        bounced = True
    if py < cy - LUANWU_BOX_HH or py > cy + LUANWU_BOX_HH:
        ud['vy'] = -ud['vy']                              # 撞上下边反弹
        bounced = True
    if bounced:                                           # 反弹时随机偏转 → 不沿刚性轨迹聚团
        import math
        da = ud['battle'].rng.uniform(-LUANWU_BOUNCE_TURN, LUANWU_BOUNCE_TURN)
        cos_a, sin_a = math.cos(da), math.sin(da)
        vx, vy = ud['vx'], ud['vy']
        ud['vx'] = vx * cos_a - vy * sin_a
        ud['vy'] = vx * sin_a + vy * cos_a
    e.frame_idx = _skate_frame(ud['vx'], ud['vy'])        # 帧跟飞行方向 (反弹后更新)


def _spawn_skateboard(battle, cx: int, cy: int, coord, idx: int = 0) -> None:
    """spawn 1 个滑板: 4×4 网格分散位置(+抖动) + 随机方向 + 轻微随机速度 (防聚团). cx,cy=px 中心."""
    import math
    ang = battle.rng.random() * 2 * math.pi
    spd = LUANWU_SPEED * battle.rng.uniform(0.82, 1.18)  # 速度轻微差异 → 不同步, 不聚团
    vx = math.cos(ang) * spd
    vy = math.sin(ang) * spd
    e = battle.engine.spawn(think_fn=skateboard_think)
    e.atlas_slot = LUANWU_SKATE_ATLAS
    e.flags |= 0x40
    # 4×4 网格铺开: idx → 格中心 + 半格抖动 (初始就分散)
    col, row = idx % 4, (idx // 4) % 4
    cw, ch = (2 * LUANWU_BOX_HW) // 4, (2 * LUANWU_BOX_HH) // 4
    gx = -LUANWU_BOX_HW + col * cw + cw // 2 + battle.rng.randint(-cw // 2, cw // 2)
    gy = -LUANWU_BOX_HH + row * ch + ch // 2 + battle.rng.randint(-ch // 2, ch // 2)
    e.x = (cx + gx) << 16
    e.y = (cy + gy) << 16
    e.z = -(LUANWU_HEIGHT << 16)
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.user_data['skate'] = True
    e.user_data['draw_order'] = 10
    e.user_data['battle'] = battle
    e.user_data['vx'] = vx
    e.user_data['vy'] = vy
    e.user_data['cx'] = cx
    e.user_data['cy'] = cy
    e.user_data['coord'] = coord
    e.frame_idx = _skate_frame(vx, vy)


def luanwu_coord_think(e: "Entity", eng: "Engine") -> None:
    """超亂舞 coordinator: spawn 16 滑板 → 每 20tick 全敌受击 → 128tick 结算伤害+滑板全销毁 (exe FUN_004f82c9)."""
    ud = e.user_data
    if 'luanwu' not in ud:
        return
    battle, caster, coord = ud['battle'], ud['caster'], ud['coord']
    if not ud['spawned']:                                 # 起手 spawn 16 滑板
        ud['spawned'] = True
        # 框中心 = 可见屏幕中心 (满屏飞). 施法者靠地图/相机边缘时相机会 clamp, 此时
        # 屏幕中心 ≠ 施法者格, 用施法者格当中心会让滑板整体偏到半屏 (bug). headless
        # 无 UI 时回退到 cursor 格.
        view = getattr(battle, 'view_center_world', None)
        cx, cy = view if view is not None else ((coord.x >> 16), (coord.y >> 16))
        for i in range(LUANWU_COUNT):
            _spawn_skateboard(battle, cx, cy, coord, idx=i)
    ud['tick'] += 1
    t = ud['tick']
    if t % LUANWU_REACT_INTERVAL == 0:                    # 周期全敌受击 (滑板撞击感)
        for v in ud['victims']:
            _ql_rain_react(battle, caster, v)
    if t >= LUANWU_DURATION:                              # 结算伤害 + 滑板全销毁 + 收尾
        _aoe_hit_all(battle, caster, ud['victims'])
        coord.user_data['luanwu_done'] = True             # 滑板自毁
        coord.user_data['eson_done'] = True
        eng.destroy(e)


def spawn_luanwu(battle, caster, coord: "Entity") -> None:
    """超亂舞: 16 滑板满天飞 + 周期受击 + 末尾 AOE 伤害 (施法姿由 coordinator 保持)."""
    coord.user_data['eson_done'] = False
    coord.user_data['luanwu_done'] = False
    e = battle.engine.spawn(think_fn=luanwu_coord_think)
    e.flags = 0x800 | 0x10000                             # alive + think, 不渲染
    e.user_data['kind'] = 'son_aoe'
    e.user_data['projectile'] = True
    e.user_data['luanwu'] = True
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['coord'] = coord
    e.user_data['victims'] = _eson_collect_victims(battle, caster)
    e.user_data['spawned'] = False
    e.user_data['tick'] = 0
    e.state_code = _LUANWU_RUN


# ============ 分身术: 孙悟空原地翻跟斗 + 对每敌召唤 4 分身围攻 (exe FUN_004f3ca3/3c73/3bdf/3876/3693) ============
# 原版: 孙悟空本体**原地翻跟斗不隐藏**; IMPACT 时 dispatcher **循环每个敌人** FUN_004f3c73(victim) 各建
# coordinator → 每敌上方先冒烟 + 依次投放 4 分身(围着**那个敌人**上/下/左/右)落地攻击 → 依次退场.
# 分身=复制孙悟空本体(cson_e0 atlas2): 落下→落地播方向攻击帧(dir*4..+3)→升空喷烟消失. **每敌的末身**
# 退场时对**那个敌人**结算伤害 (exe -250). 每敌各伤害一次.
FENSHEN_ATLAS = 0               # cson1_g0 = 孙悟空**普通攻击**图 (ATK_A, 16帧=四方向×4, dir N=帧N*4..+3).
                                # ⚠不是 cson_e0(atlas2, 那是施法/特效图)! exe 攻击 seq 用 atlas slot 0.
FENSHEN_FALL_SHEET = "ps_CSON102"   # 下落/站姿用 (4col×4row 64×96, 最后一列 col3=站姿)
FENSHEN_PS_GRID = (4, 64, 96, 32, 84)   # (cols, fw, fh, anchor_x, anchor_y脚部)
FENSHEN_SPAWN_INTERVAL = 16     # 每 N tick 给每敌投 1 分身 (exe frame & 0xf == 0)
# 4 分身: (x偏移px, y偏移px, dir). exe FUN_004f3876 index→(pos, dir 0x110). cson_e0/ps_CSON102 同向: dir 行.
FENSHEN_CLONES = [
    (0, -32, 1),   # 上, dir1 (朝下/正面)
    (0, 32, 0),    # 下, dir0 (朝上/背面)
    (-40, 0, 3),   # 左, dir3 (朝右)
    (40, 0, 2),    # 右, dir2 (朝左)
]
FENSHEN_DROP_HEIGHT = 64        # 分身从上方落下 px (exe spawn z+0x40)
FENSHEN_FALL_VZ = 6             # 落下 px/tick
FENSHEN_RISE_VZ = 7             # 升空回云 px/tick
# 攻击 seq (exe PTR_DAT_00671a8c): 每个分身**连打 6 拳**, 节奏由慢加速 — 每拳后 HOLD 递减 24→12→6→3→3→3.
# 单拳: 前冲 + frame0(3t) + 发 -200 敌人受击 + frame1(3t)+frame2(3t)+frame3(5t) + 后退.
FENSHEN_ATK_COUNT = 6
FENSHEN_HOLDS = (24, 12, 6, 3, 3, 3)              # 每拳后停留 tick (加速连打)
FENSHEN_STRIKE_SCHED = ((0, 3), (1, 3), (2, 3), (3, 5))   # 单拳 (帧偏移, tick); frame0 完发受击
FENSHEN_LUNGE_PX = 7           # 出拳时朝敌人前冲 px (收拳归位)
_FS_FALL = 0
_FS_ATTACK = 1
_FS_RISE = 2


def _fenshen_set_stand(e, d):
    """分身切到 ps_CSON102 站姿 (下落/升空): 最后一列 col3 = 帧 d*4+3."""
    e.user_data['ps_sheet'] = FENSHEN_FALL_SHEET
    e.user_data['ps_grid'] = FENSHEN_PS_GRID
    e.frame_idx = d * 4 + 3


def _fenshen_lunge(e, ud, px: int):
    """分身出拳朝敌人前冲 px (px=0 收拳归位). 方向 = 离敌偏移的反向 (朝敌)."""
    e.x = ud['base_x'] + ((ud['lunge_dx'] * px) << 16)
    e.y = ud['base_y'] + ((ud['lunge_dy'] * px) << 16)


def _fenshen_hit(ud, deal_damage: bool) -> None:
    """单拳命中敌人: 受击 (reaction+爆); deal_damage=True (末身末拳) 额外结算伤害数字."""
    v = ud['victim']
    if not v.alive:
        return
    if deal_damage:
        from core.battle import combat
        combat._roll_damage_one(ud['battle'], ud['caster'], v, face_attacker=False)
    else:
        _ql_rain_react(ud['battle'], ud['caster'], v)


def fenshen_clone_think(e: "Entity", eng: "Engine") -> None:
    """孙悟空分身: ps_CSON102 站姿落下 → 落地播 cson_e0 攻击帧(命中帧敌人受击) → 站姿升空回云喷烟消失.
    每身命中都使敌人受击(reaction+爆); **末身**额外结算伤害一次 (exe -200受击/-250伤害)."""
    ud = e.user_data
    if 'clone' not in ud:
        return
    d = ud['dir']
    v = ud['victim']
    if e.state_code == _FS_FALL:                        # ps_CSON102 站姿下落
        e.z += FENSHEN_FALL_VZ << 16
        if e.z >= 0:
            e.z = 0
            ud['atk_num'] = 0                           # 第几拳 (0..5)
            ud['strike_idx'] = 0                        # 单拳第几帧 (-1=拳间 hold)
            ud['tick'] = 0
            ud.pop('ps_sheet', None)                    # 切到 cson1_g0 普通攻击图
            e.atlas_slot = FENSHEN_ATLAS
            e.frame_idx = d * 4
            e.state_code = _FS_ATTACK
    elif e.state_code == _FS_ATTACK:                    # 连打 6 拳 (加速节奏) + 每拳敌人受击
        ud['tick'] += 1
        si = ud['strike_idx']
        if si >= 0:                                     # 出拳中
            frame_off, ticks = FENSHEN_STRIKE_SCHED[si]
            e.frame_idx = d * 4 + frame_off
            _fenshen_lunge(e, ud, FENSHEN_LUNGE_PX)     # 前冲
            if ud['tick'] >= ticks:
                ud['tick'] = 0
                if si == 0:                             # frame0 完 → 敌人受击 (exe signal -200)
                    _fenshen_hit(ud, deal_damage=(ud['is_last'] and ud['atk_num'] == FENSHEN_ATK_COUNT - 1))
                ud['strike_idx'] += 1
                if ud['strike_idx'] >= len(FENSHEN_STRIKE_SCHED):   # 单拳完 → 拳间 hold
                    ud['strike_idx'] = -1
                    e.frame_idx = d * 4
                    _fenshen_lunge(e, ud, 0)            # 收拳归位
        else:                                           # 拳间 hold (节奏递减)
            if ud['tick'] >= FENSHEN_HOLDS[ud['atk_num']]:
                ud['tick'] = 0
                ud['atk_num'] += 1
                if ud['atk_num'] >= FENSHEN_ATK_COUNT:  # 6 拳打完 → 升空
                    _fenshen_set_stand(e, d)
                    e.state_code = _FS_RISE
                else:
                    ud['strike_idx'] = 0                # 下一拳
    elif e.state_code == _FS_RISE:                      # 站姿升空回云
        e.z -= FENSHEN_RISE_VZ << 16
        if (e.z >> 16) <= -FENSHEN_DROP_HEIGHT:         # 升到顶 → 喷烟 (回云中) 消失
            _spawn_smoke_at(ud['battle'], e.x >> 16, e.y >> 16, count=6)
            eng.destroy(e)


def _spawn_clone(battle, caster, victim, idx: int) -> None:
    """对 victim 身边 spawn 1 个分身 (idx 0-3 = 上/下/左/右, 朝向 victim), 落点带烟雾. idx==3 末身结算伤害."""
    ox, oy, d = FENSHEN_CLONES[idx]
    vx, vy = _victim_ground(victim)
    e = battle.engine.spawn(think_fn=fenshen_clone_think)
    e.flags |= 0x40
    e.x = vx + (ox << 16)
    e.y = vy + (oy << 16)
    e.z = -(FENSHEN_DROP_HEIGHT << 16)
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.user_data['clone'] = True
    e.user_data['shadow'] = True                       # 落地影子 → 接地 (否则看着浮空)
    e.user_data['behind_units'] = (oy < 0)             # 敌人上方(身后)的分身 → 画在敌人身后
    e.user_data['draw_order'] = 8
    e.user_data['dir'] = d
    e.user_data['is_last'] = (idx == 3)
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['victim'] = victim
    e.user_data['base_x'] = e.x                         # 出拳前冲的归位基准
    e.user_data['base_y'] = e.y
    e.user_data['lunge_dx'] = 0 if ox == 0 else (-1 if ox > 0 else 1)   # 朝敌 = 离敌偏移的反向
    e.user_data['lunge_dy'] = 0 if oy == 0 else (-1 if oy > 0 else 1)
    _fenshen_set_stand(e, d)                            # 下落时 ps_CSON102 站姿 (最后一列)
    e.state_code = _FS_FALL
    _spawn_smoke_at(battle, (vx >> 16) + ox, (vy >> 16) + oy, count=6)  # 出现喷烟 (云)


def fenshen_spawner_think(e: "Entity", eng: "Engine") -> None:
    """分身术 spawner: 每 16tick 给**每个敌人**投放 1 分身 (共4轮), 全投完等所有分身退场 → 收尾.
    (exe: 每敌一个 coordinator FUN_004f3bdf 各 spawn 4 分身; 这里合并为一个 spawner 并行处理所有敌人.)"""
    ud = e.user_data
    if 'fenshen' not in ud:
        return
    if ud['round'] < 4:
        if ud['tick'] % FENSHEN_SPAWN_INTERVAL == 0:
            for v in ud['victims']:
                if v.alive:
                    _spawn_clone(ud['battle'], ud['caster'], v, ud['round'])
            ud['round'] += 1
        ud['tick'] += 1
    elif not any(c.user_data.get('clone') for c in eng.entities if (c.flags & 0x800)):
        ud['coord'].user_data['eson_done'] = True
        eng.destroy(e)


def spawn_fenshen(battle, caster, coord: "Entity") -> None:
    """分身术: 每敌上方先冒烟 + 依次投放 4 分身围攻 + 依次退场, 每敌末身各结算伤害."""
    coord.user_data['eson_done'] = False
    victims = _eson_collect_victims(battle, caster)
    for v in victims:                                  # 每敌上方先冒一团烟
        vx, vy = _victim_ground(v)
        _spawn_smoke_at(battle, vx >> 16, (vy >> 16) - 36, count=8)
    e = battle.engine.spawn(think_fn=fenshen_spawner_think)
    e.flags = 0x800 | 0x10000                          # alive + think, 不渲染 (spawner 无视觉)
    e.user_data['kind'] = 'son_aoe'
    e.user_data['projectile'] = True
    e.user_data['fenshen'] = True
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['coord'] = coord
    e.user_data['victims'] = victims
    e.user_data['round'] = 0
    e.user_data['tick'] = 0


# ============ AOE 占位 (超亂舞, 待做专属演出) ============
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
    # ps_CSON102 简短施法姿: **0x04 分身 (PTR_00671b0c) + 0x08 超亂舞 (PTR_00671db0, 同位帧2/6)**.
    # 其余技能 cast = 翻跟斗本身 (槽5=ps_CSON105), 直接进 FLIP_OUT.
    if skill_id in (0x04, 0x08):
        e.user_data['cast_row'] = _caster_cson_row(caster)
        e.user_data['cast_pose_idx'] = 0
        e.state_code = _CAST
        caster.cast_pose_frame = e.user_data['cast_row'] * 4 + CAST_POSE_COLS[0]
    else:
        e.state_code = _FLIP_OUT
        caster.cast_flip_frame = 0                # 起手翻跟头第 0 帧
    caster.pending_caster_coord = e
    return e


def is_son_transform_skill(skill_id: int | None) -> bool:
    return skill_id is not None and skill_id in SON_TRANSFORM_SKILLS
