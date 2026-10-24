"""孙悟空变身技能演出框架 (skill 0x00..0x09).

exe dispatcher (e.g. 大金刚 FUN_004f460a) 是多阶段变身演出, 我们用 coordinator entity
驱动 caster 的翻跟头隐现 + 神兽 spawn + AOE 伤害 + 收尾.

演出流程 (对应 exe state 流):
  FLIP_OUT: caster 翻跟头 (ps_CSON105 0..7) + emong 烟雾 → 翻完 caster 隐身
  TRANSFORM:   变身形态攻击阶段 (L1 占位: 直接 AOE 伤害; 后续接 eson01 从天而降逐敌)
  FLIP_IN:  caster 现身 + 翻跟头 (0..7) + emong → 翻完
  DONE:     post_attack_anim 收尾 + 销毁 coordinator

翻跟头走真 attach_seq (caster.entity 挂 exe @0x670dc4 转写字节码, 内嵌音效/跳弧自动生效,
units.py mode2 分支渲染 ps_XXX105); 隐身/施法姿等仍由 coordinator 控制 cast_hidden /
cast_pose_frame. coordinator 标 projectile=True 让 units_animating 看到, 防回合提前结束.
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

TRANSFORM_TICKS = 40          # 变身形态攻击阶段时长 (占位, 后续 eson01 下落逐敌取代)
# 隐身烟雾 → 神兽 spawn 的间隔 (exe 各 dispatcher case 0x14 设 +0x16c = now+0x20, case 0x1e 到时
# 才播技能音 + spawn 神兽). 烟雾散去后停 1.28s 再召唤, 所有孙悟空神兽技能一致.
BEAST_SPAWN_DELAY_TICKS = 32

# ============ 翻跟头 seq (exe @0x670dc4 / @0x670d24 逐字节转写) ============
# 结构: sound 0x127(起跳) → 8 帧 idle slot5 (= ps_XXX105 翻跟头) 各 2 tick, 帧间 MOVE dz
# 小跳弧 (exe z+ = 上, 升 8+4+2=14px 再 -2-4-4-4 落回; 我们负 z = 上 → 符号翻转) →
# sound 0x128(翻完落地) → exit. 循环版 @0x670d24 内容全同, 结尾 op 0x01 loop (分身 TRANSFORM 期,
# 每圈重播两声 = exe 行为). attach 到 caster.entity 播放, 内嵌 sound/move op 自动生效,
# units.py mode2 (atlas_slot|0x20000) 分支按 per-unit ps_ 家族 (slot N → ps_XXX10N) 渲染.
SFX_FLIP = 0x127              # 翻跟头起跳音 (E127, seq 首 op)
SFX_FLIP_END = 0x128          # 翻跟头收尾音 (E128, seq 末 op)
_FLIP_BODY: list[tuple] = [
    ('sound', SFX_FLIP, 0x0411),
    ('idle', 5, 0, 2), ('move', 0, 0, -8, 0),
    ('idle', 5, 1, 2), ('move', 0, 0, -4, 0),
    ('idle', 5, 2, 2), ('move', 0, 0, -2, 0),
    ('idle', 5, 3, 2),
    ('idle', 5, 4, 2), ('move', 0, 0, 2, 0),
    ('idle', 5, 5, 2), ('move', 0, 0, 4, 0),
    ('idle', 5, 6, 2), ('move', 0, 0, 4, 0),
    ('idle', 5, 7, 2), ('move', 0, 0, 4, 0),
    ('sound', SFX_FLIP_END, 0x0411),
]
FLIP_SEQ = _FLIP_BODY + [('exit',)]        # @0x670dc4 单次 (隐身/现身各 attach 一次)
FLIP_LOOP_SEQ = _FLIP_BODY + [('loop',)]   # @0x670d24 循环 (分身原地连续翻)


def _flip_attach(battle, caster, loop: bool = False) -> None:
    """把翻跟头 seq attach 到 caster.entity (= exe FUN_00438d40 attach 0x670dc4/0x670d24).
    播放期 caster.is_attacking=True, units.py 走 mode2 渲染 ps_XXX105; seq 内嵌音效/跳弧自动生效."""
    from core.anim_engine.bytecode import tuple_to_bytecode
    if caster.entity is None:
        caster.entity = battle.engine.spawn()
    ent = caster.entity
    ent.x = ent.y = ent.z = 0
    ent.user_data = {'unit': caster}
    battle.engine.attach_seq(ent, tuple_to_bytecode(FLIP_LOOP_SEQ if loop else FLIP_SEQ))


def _flip_stop(caster) -> None:
    """终止翻跟头 (循环版没有 exit, 收尾手动清; 单次版播完自清, 调用无害)."""
    ent = caster.entity
    if ent is not None:
        ent.flags &= ~0x20000
        ent.seq = b''
        ent.x = ent.y = ent.z = 0

# emong 烟雾 (atlas 248). 真实用法 (exe 0x670ff0[0..2] + FUN_004f3558/34f6):
# 不是单个大烟雾, 而是撒 N 个随机小烟雾粒子, 每个随机选 3 段之一 (frames 0-5/6-11/12-17),
# 随机位置散布在 caster 周围, 每帧配向上 move (-1→-3 加速) = 冒泡上升. 多粒子叠加 = 浓烟消散.
EMONG_ATLAS = 248
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


SMOKE_PER_TICK = 4            # exe FUN_004f3635(x, y, z=32px, dir, 4, 2): spawner 每 tick 4 粒, 第 3 tick (age==2) 撒完自毁 → 12 粒
SMOKE_TICKS = 3
SMOKE_Z_PX = 32               # dispatcher 传 0x200000 = 32px (spawner 再 +1)


def _spawn_smoke_burst(battle, sx: int, sy: int, sz: int) -> None:
    """exe FUN_004f3558 一 tick: 4 粒 emong, 位置 = spawner (x-24+rand%48, y-1+rand&3, z-24+rand%48), 段 rand%3."""
    from core.anim_engine.bytecode import tuple_to_bytecode
    rng = battle.rng
    for _ in range(SMOKE_PER_TICK):
        seg = EMONG_SEGS[rng.randint(0, 2)]
        e = battle.engine.spawn()
        e.x = sx + ((rng.randint(0, 47) - 24) << 16)
        e.y = sy + ((rng.randint(0, 3) - 1) << 16)
        e.z = -(sz + ((rng.randint(0, 47) - 24) << 16))
        e.user_data['kind'] = 'hit_effect'
        battle.engine.attach_seq(e, tuple_to_bytecode(seg))


def _smoke_spawner_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'smoke' not in ud:
        return
    _spawn_smoke_burst(ud['battle'], e.x, e.y, ud['sz'])
    ud['left'] -= 1
    if ud['left'] <= 0:
        eng.destroy(e)


def _spawn_smoke_at(battle, world_x: int, world_y: int, z_px: int = SMOKE_Z_PX, count: int = SMOKE_PER_TICK * SMOKE_TICKS) -> None:
    """在像素坐标 (world_x, world_y) 撒 emong 烟雾: exe spawner (x, y+1, z+1), 出生 tick 起每 tick 4 粒共 3 tick
    (实录 变身烟 +24/+25/+26 各 4 粒, z 9..56). 出生 tick 那批直接撒, 余下两 tick 交给 spawner 实体."""
    sx, sy, sz = world_x << 16, (world_y + 1) << 16, (z_px + 1) << 16
    _spawn_smoke_burst(battle, sx, sy, sz)
    ticks = max(1, -(-count // SMOKE_PER_TICK))
    if ticks > 1:
        sp = battle.engine.spawn(think_fn=_smoke_spawner_think)
        sp.flags = 0x800 | 0x10000
        sp.x, sp.y = sx, sy
        sp.user_data.update(kind='smoke_spawner', smoke=True, battle=battle, sz=sz, left=ticks - 1)


SFX_SMOKE = 0x129             # 变身烟雾音 (E129): exe 各 dispatcher 在两处 FUN_004f3635 烟雾旁都播
SFX_ESON_BEAST = 0x107        # 大金刚神兽音 (E095, 3.2s): case 0x1e spawn 时播, case 0x28 收尾切断
SFX_ESON_SLAM = 0xec          # 大金刚每敌砸中音 (E068): case -250 受击特效旁播


def _sfx(battle, sound_id: int, solo: bool = False) -> None:
    """播全局 sound_id 音效 (= exe FUN_00416311, 技能 dispatcher 显式调用).
    solo=True: 同 id 播放中跳过 (exe 每 id 单 DirectSound buffer 听感), 密集连发音用."""
    battle.engine._emit('sound_play_solo' if solo else 'sound_play', None, sound_id)


def _sfx_stop(battle, sound_id: int) -> None:
    """切断指定音效 (= exe FUN_00416388, 技能收尾切断长音)."""
    battle.engine._emit('sound_stop', None, sound_id)


def _spawn_smoke(battle, caster, sound: int = SFX_SMOKE) -> None:
    """在 caster 周围撒 emong 烟雾 (4/t × 3t) + 烟雾音 (默认 0x129; 酷酷猫返程 0x128).
    exe 各 dispatcher 隐身/现身两处 FUN_004f3635 前都 FUN_00416311(音), 与本 fn 调用点一一对应."""
    from core.sprites.base import TILE_W, TILE_H
    _sfx(battle, sound)
    _spawn_smoke_at(battle, caster.x * TILE_W + TILE_W // 2, caster.y * TILE_H + TILE_H // 2)


def _son_return(coord: "Entity") -> None:
    """神兽退场 (-150) → exe dispatcher 0x3c 同 tick: 切断神兽长音 + 烟 + 重 attach 翻跟头 0x670dc4 现身.
    神兽 think 里直接调 (= exe 同步信号), 不等 coordinator 下一 tick."""
    ud = coord.user_data
    caster, battle = ud['caster'], ud['battle']
    if ud.get('beast_sound') is not None:
        _sfx_stop(battle, ud.pop('beast_sound'))      # exe case 0x28: FUN_00416388 切断神兽长音 (如大金刚 0x107)
    ud['eson_done'] = True
    caster.cast_hidden = False
    _spawn_smoke(battle, caster, sound=ud.get('return_sound', SFX_SMOKE))
    _flip_attach(battle, caster)
    coord.state_code = _FLIP_IN


def son_transform_think(e: "Entity", eng: "Engine") -> None:
    """孙悟空变身 coordinator. 驱动翻跟头隐现 + 神兽 + 伤害 + 收尾."""
    if 'caster' not in e.user_data:
        return  # spawn 时的 init call (state=-1, user_data 未设), 跳过
    caster = e.user_data['caster']
    battle = e.user_data['battle']

    if e.state_code == _CAST:
        t = e.user_data['flip_tick']
        e.user_data['flip_tick'] = t + 1
        if e.user_data['skill_id'] == 0x04:
            # 分身术 cast seq PTR_DAT_00671b0c[dir]: ps_CSON102 列 2 (t15=16 tick) → signal -100 (每敌 spawner + 0x106)
            # → 列 3 (t3=4 tick) → exit → 0x14 挂循环翻跟头 0x670d24 (实录 分身 16/32/48/64, 翻跟头 +20)
            row = e.user_data['cast_row']
            if t == 0:
                caster.cast_pose_frame = row * 4 + 2
            elif t == 15:
                spawn_fenshen(battle, caster, e)
                caster.cast_pose_frame = row * 4 + 3
            elif t == 19:
                caster.cast_pose_frame = None
                _flip_attach(battle, caster, loop=True)
                e.state_code = _TRANSFORM
            return
        # 超亂舞: cast seq 的 -1008 (= exe -100) 由 on_signal 同 tick 召滑板 (见 start_son_transform), 这里只等它切状态
        if e.user_data['skill_id'] == 0x08:
            return
    elif e.state_code == _FLIP_OUT:
        # 翻跟头 seq (attach @start_son_transform) 播完 (exit op 清 playing) → 隐身变身
        if not caster.is_attacking:
            # 翻跟头消失完 → 落地噗烟 (exe state 0x14 在翻跟头 cast seq 之后撒) + 隐身;
            # 神兽延迟 32 tick 再召唤 (exe case 0x1e)
            caster.cast_hidden = True
            _spawn_smoke(battle, caster)
            e.user_data['beast_delay'] = BEAST_SPAWN_DELAY_TICKS
            e.state_code = _TRANSFORM
    elif e.state_code == _TRANSFORM:
        if e.user_data['skill_id'] == 0x08:
            # 超亂舞: 孙悟空定格施法姿, 滑板打完 (eson_done) 且飘字落定 (0x1e) → 收尾渐亮 (不翻跟斗/不隐身)
            if e.user_data.get('eson_done') and getattr(battle, 'float_pending', 0) == 0:
                e.state_code = _DONE
            return
        if e.user_data['skill_id'] == 0x04:
            # 分身术 0x1e: 所有 spawner 的末身结算完 (+0x78==0) 且飘字落定 (+0x7a==0) → 停翻跟头 + idle
            if e.user_data.get('fs_spawners', 1) <= 0 and getattr(battle, 'float_pending', 0) == 0:
                _flip_stop(caster)
                e.state_code = _DONE
            return
        # 烟雾后延迟 32 tick 才召唤神兽 (exe case 0x14 → 0x1e 的 +0x20 等待)
        bd = e.user_data.get('beast_delay')
        if bd is not None:
            bd -= 1
            e.user_data['beast_delay'] = bd
            if bd <= 0:                                  # 烟 +32 tick 召唤 (实录 烟 +24 → 龙 +56)
                e.user_data.pop('beast_delay')
                _spawn_beast_attack(battle, caster, e)   # 按 skill 召唤对应神兽
            return
        # 神兽退场 (eson_done) → caster 现身翻跟头; 朱雀/玄武/月兔 的 dispatcher 0x1e 还要等飘字落定 (+0x7a==0)
        if e.user_data.get('eson_done'):
            if e.user_data.get('return_waits_floats') and getattr(battle, 'float_pending', 0) > 0:
                return
            _son_return(e)
    elif e.state_code == _FLIP_IN:
        if not caster.is_attacking:        # 翻跟头 seq 播完
            e.state_code = _DONE
    elif e.state_code == _DONE:
        # 收尾: 清状态 + post_attack (回合结束流程) + 销毁 coord
        _flip_stop(caster)
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
    _sfx(battle, SFX_ESON_SLAM)   # exe case -250: 受击特效旁播砸中音 0xec
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
    # exe case 0x1e: spawn 神兽时播 0x107 (E095 长音), 收尾 case 0x28 切断 → 记在 coord 上
    _sfx(battle, SFX_ESON_BEAST)
    coord.user_data['beast_sound'] = SFX_ESON_BEAST
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
    eson01_attack_think(e, battle.engine)       # 出生当 tick 先走一步 (实录首帧 z=660)


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
ICE_SHARD_HEIGHT = 128                  # 小冰锥起始高度 exe FUN_004d6f6a z=0x80; 出生当 tick 先走一步 → 实录首帧 104, 5 tick 落到 8
ICE_SHARD_VZ = 24                       # 小冰锥下落 px/tick (exe +0x174=0xffe80000=-24)
ICE_SHARD_VX = 4                        # 小冰锥 x 漂移 px/tick (exe +0x16c=0x40000, flags 0x51 x 轴匀速; 实录 x 每 tick +4)
ICE_CONE_HEIGHT = 500                   # 大冰锥起始高度 (exe 0x1f40000=500px)
ICE_CONE_VZ = 48                        # 大冰锥下落 px/tick (exe +0x174=0xffd00000=-48, ~10t 落地)
ICE_SHATTER_TICKS = 17                  # 碎块寿命: 原版实录 state0 9 tick (上抛) + state10 8 tick
ICE_SHATTER_RISE_TICKS = 9
_ICE_FALL = 0
_ICE_SHATTER = 1


def _spawn_ice_shatter(battle, x, y, big: bool) -> None:
    """冰锥落地碎裂: 撒小冰块 (frames 12-23), 匀速四散 + 后半程闪烁 (exe FUN_004d6dc3 每调一次 4 片).
    大冰锥落地 FUN_004d7058 连调 6 次 = 24 片 (冰龍升天实录 3 根锥 72 片, 不分命中与否); 小冰锥 1 次 = 4 片.
    exe 每片: 位置 = 锥落点 (无抖动, z=0); vx = rand%3000/500-3 ∈[-3,3) px/t, vy = rand%2000/500-2 ∈[-2,2),
    vz = rand%3000/1000 ∈[0,3) 向上; FUN_004c3211 (无 flag 1) = 纯 pos += vel, **无重力**: 实录 17 tick 直线上飘 (z 最高 ~49)."""
    rng = battle.rng
    n = 24 if big else 4
    for _ in range(n):
        e = battle.engine.spawn(think_fn=ice_shatter_think)
        e.atlas_slot = EICE_ATLAS
        e.frame_idx = EICE_SHATTER[rng.randint(0, len(EICE_SHATTER) - 1)]
        e.flags |= 0x40
        e.x = x
        e.y = y
        e.z = 0
        e.vx = (rng.randint(0, 2999) << 16) // 500 - (3 << 16)
        e.vy = (rng.randint(0, 1999) << 16) // 500 - (2 << 16)
        e.vz = -((rng.randint(0, 2999) << 16) // 1000)     # 上飘 (我们 z 负=高)
        e.user_data['kind'] = 'hit_effect'
        e.user_data['projectile'] = True
        e.user_data['shatter'] = True
        e.user_data['tick'] = 0


def ice_shatter_think(e: "Entity", eng: "Engine") -> None:
    """碎冰块 (exe FUN_004d6d46): 匀速直线 (无重力) + tick≥9 起每 tick XOR 可见 (闪烁), tick 17 消失."""
    ud = e.user_data
    if 'shatter' not in ud:
        return
    e.x += e.vx
    e.y += e.vy
    e.z += e.vz
    ud['tick'] += 1
    if ud['tick'] > ICE_SHATTER_RISE_TICKS:   # 后半程闪烁 (exe XOR visible)
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
        if not ud['big']:
            e.x += ICE_SHARD_VX << 16
        if e.z >= 0:
            e.z = 0
            _spawn_ice_shatter(ud['battle'], e.x, e.y, ud['big'])
            v = ud.get('victim')             # 大冰锥落地结算伤害 (exe FUN_004d70fc think)
            if v is not None and v.alive:
                from core.battle import combat
                combat._roll_damage_one(ud['battle'], ud['caster'], v, face_attacker=False)
            eng.destroy(e)


def _spawn_ice_cone(battle, x, y, height_px, frame, big, victim=None, caster=None) -> None:
    # exe 冰锥 spawn fn 末尾各播一声: 小冰锥 FUN_004d6f6a→0xad / 大冰锥 FUN_004d70fc→0xae.
    # 小冰锥雨每 2 tick/敌 一颗, 但 exe 每 id 单 buffer → 播放中重触发不叠放, 听感 = 一段段
    # (0.56s/段, 100 tick 雨约 5-7 段, 用户确认原版是段落感非糊成一片) → solo 通道.
    _sfx(battle, SFX_QL_ICE_BIG if big else SFX_QL_ICE_SMALL, solo=not big)
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
    if not big:
        ice_cone_think(e, battle.engine)       # 池序: 出生当 tick 先走一步 (实录首帧 z=104)


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
# ============ 神兽共用: 屏顶弹簧飘落 → 悬停 → 升空 (2026-10-22 实录 son_01..07 全部一致) ============
# spawn (青龙 FUN_004f4d4e / 白虎 4f56e1 / 朱雀 4f68a5 / 玄武 4f70d0 / 月兔 4f7931 同款): x = 屏幕中心 x,
# y = 屏幕中心 y + 1000, z = 1900, flags 0x41 (z 弹簧目标 2000 加速度 2), vz -60 → 每 tick v += 2 减速下落,
# v ≥ 0 即悬停 (z 1030, 首帧 1842, 29 帧). 升空: v=0 加速度 2; 青龙/白虎 v > 59 自毁 (29 帧), 朱雀/玄武/月兔 z > 1800 自毁 (28 帧).
BEAST_SPAWN_Y_OFF = 1000
BEAST_SPAWN_Z = 1900
BEAST_TARGET_Z = 2000
BEAST_VZ0 = -60
BEAST_ACCEL = 2
BEAST_RISE_V_END = 59
BEAST_RISE_Z_END = 1800
BEAST_HOVER_TICKS = 128          # 朱雀/玄武/月兔 悬停 +0x80 (以神兽自身 age 计: 悬停 age 29 → 结束 157)
BEAST_LEAD_TICKS = 30            # 结束前 0x1e: 朱雀停火 / 玄武落石 / 月兔弹幕开始


def _beast_step(e: "Entity") -> None:
    """exe FUN_004c3211 flag 0x41: v += ±a (朝目标 z), z += v. ud['ez'] 为 exe 约定 (正 = 高)."""
    ud = e.user_data
    ud['vz'] += BEAST_ACCEL if ud['ez'] < BEAST_TARGET_Z else -BEAST_ACCEL
    ud['ez'] += ud['vz']
    e.z = -(ud['ez'] << 16)


def _beast_spawn(battle, caster, coord, atlas: int, think_fn, draw_order: int = 10) -> "Entity":
    coord.user_data['eson_done'] = False
    e = battle.engine.spawn(think_fn=think_fn)
    e.atlas_slot = atlas
    e.frame_idx = 0
    e.flags |= 0x40
    e.user_data.update(kind='hit_effect', projectile=True, draw_order=draw_order, battle=battle, caster=caster,
                       coord=coord, victims=_eson_collect_victims(battle, caster),
                       ez=BEAST_SPAWN_Z, vz=BEAST_VZ0, age=0)
    cx, cy = _screen_center(battle, caster)
    e.x, e.y = cx, cy + (BEAST_SPAWN_Y_OFF << 16)
    e.state_code = 0
    _beast_step(e)                                 # 出生当 tick 先走一步 (实录首帧 z=1842)
    return e


def _beast_rise_start(e: "Entity") -> None:
    e.flags &= ~0x20000
    e.user_data['vz'] = 0


def _beast_rise_step(e: "Entity", by_z: bool) -> bool:
    """升空一步; 返回是否该自毁 (by_z: z > 1800, 否则 v > 59)."""
    _beast_step(e)
    ud = e.user_data
    return ud['ez'] > BEAST_RISE_Z_END if by_z else ud['vz'] > BEAST_RISE_V_END


def _damage_only(battle, caster, victim) -> None:
    """exe -200 只飘字 (无受击 seq/特效) 的结算."""
    from core.battle import combat
    if not victim.alive:
        return
    caster.suppress_hit_fx = True
    caster.suppress_hit_reaction = True
    try:
        combat._roll_damage_one(battle, caster, victim, face_attacker=False)
    finally:
        caster.suppress_hit_fx = False
        caster.suppress_hit_reaction = False


def _react_dir(battle, caster, victim) -> None:
    """exe -250 = 受击 seq + 仅方向 starburst 655c10[dir] (朱雀/玄武 dispatcher 只有一个 FUN_004d0c90)."""
    from core.jah_skills import _hit
    if victim.alive:
        _hit(battle, caster, victim, fx='dir')


QL_ATLAS = 255
# 2026-10-22 原版实录 (son_01_F194496) + 反编译 reverse_engineering/qinglong_decomp.txt:
# dispatcher FUN_004f4e37: 翻跟头 seq 完 → 0x14: 烟 (4/t×3t) + 隐身, +32t → 0x1e: 播 0x147 + FUN_004f4d4e 龙:
#   x = 屏幕中心 x, y = 屏幕中心 y + 1000, z = 1900, flags 0x41 (z 轴无阻尼弹簧目标 2000, 加速度 2), vz -60
#   → 每 tick v += 2 (减速下落), v ≥ 0 即悬停 (z = 1030, 29 帧) → 挂 seq 0x671b1c + 发 -100.
#   0x28 (雨): dispatcher age < 开始+100 且 age%2==0: 每敌 **重挂 seq** (帧 0,1 每 tick 交替) + 小冰锥 FUN_004d6f6a
#   (x = 敌x-44+rand%64, y = 敌y-6+rand%30, z 128, vz -24, vx +4); age%20==0 时每敌 -250 (受击 seq + 两特效).
#   雨停后 seq 尾 2,2,1,1 → 定格 1. age == 开始+140: 每敌大冰锥 FUN_004d70fc (z 500 vz -48, 落地 24 碎冰 + -200/-250).
#   0x32: 飘字计数 0 (此刻还没落地 → 立即) → 龙 -100: 不播 seq (定格帧 0), v=0 加速度 2 升空, v > 59 (30t, 升 930px)
#   → -150 自毁 → 0x3c: 烟 + 翻跟头现身 → 0x46 seq 完 idle → 0x50 渐亮.
# dispatcher age = attach 后 tick + 21 (渐暗 20 + state 10); 龙生成在 age 77.
QL_SPAWN_Y_OFF = BEAST_SPAWN_Y_OFF
QL_SPAWN_Z = BEAST_SPAWN_Z
QL_TARGET_Z = BEAST_TARGET_Z
QL_VZ0 = BEAST_VZ0
QL_ACCEL = BEAST_ACCEL
QL_RISE_V_END = BEAST_RISE_V_END
QL_RAIN_TICKS = 100
QL_BIG_CONE_AT = 141            # 实录: 悬停 +141 重挂 seq + 大冰锥, +142 升空
QL_SPAWN_AGE = 77
QL_SKY_PX = 930                 # 升空 30 tick 共 930px (测试/文档用)
SFX_QL_BEAST = 0x147
SFX_QL_ICE_SMALL = 0xad
SFX_QL_ICE_BIG = 0xae
_QL_DESCEND = 0
_QL_RAIN = 1
_QL_RISE_WAIT = 2
_QL_RISE = 3


def _ql_step(e: "Entity") -> None:
    """exe FUN_004c3211 flag 0x41: v += ±a (朝目标 z), z += v. ud['ez'] 为 exe 约定 (正 = 高)."""
    ud = e.user_data
    ud['vz'] += QL_ACCEL if ud['ez'] < QL_TARGET_Z else -QL_ACCEL
    ud['ez'] += ud['vz']
    e.z = -(ud['ez'] << 16)


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
    ud['age'] += 1
    if e.state_code == _QL_DESCEND:
        _beast_step(e)
        if ud['vz'] >= 0:
            ud['rain_start'] = ud['age']
            e.frame_idx = 0
            e.state_code = _QL_RAIN
    elif e.state_code == _QL_RAIN:
        age = ud['age']; t = age - ud['rain_start']
        if t <= QL_RAIN_TICKS:                             # 实录 50 波: 悬停后 t = 2,4,...,100
            if age % 2 == 0 and t >= 2:                    # 重挂 seq: 帧 0 → 下 tick 帧 1
                e.frame_idx = 0
                for v in ud['victims']:
                    if not v.alive:
                        continue
                    vx, vy = _victim_ground(v)
                    _spawn_ice_cone(battle,
                                    vx + ((battle.rng.randint(0, 63) - 44) << 16),
                                    vy + ((battle.rng.randint(0, 29) - 6) << 16),
                                    ICE_SHARD_HEIGHT, EICE_CONE_SMALL[battle.rng.randint(0, 3)], big=False)
                    if age % 20 == 0:
                        _ql_rain_react(battle, caster, v)
            elif t >= 2:
                e.frame_idx = 1
        else:
            k = t - QL_RAIN_TICKS - 1                      # 最后一次重挂 (t=100 帧 0) 后 seq 尾: 1,1,2,2,1,1 → 定格 1 (实录 186..191)
            e.frame_idx = (1, 1, 2, 2, 1, 1)[k] if k < 6 else 1
        if t == QL_BIG_CONE_AT:
            e.frame_idx = 0
            for v in ud['victims']:
                if v.alive:
                    vx, vy = _victim_ground(v)
                    _spawn_ice_cone(battle, vx, vy + (1 << 16), ICE_CONE_HEIGHT - ICE_CONE_VZ,
                                    EICE_CONE_BIG[battle.rng.randint(0, 2)], big=True,
                                    victim=v, caster=caster)
            e.state_code = _QL_RISE_WAIT
    elif e.state_code == _QL_RISE_WAIT:                    # 0x32 下一 tick 看到飘字计数 0 → 龙 -100
        ud['vz'] = 0
        e.frame_idx = 0
        e.state_code = _QL_RISE
    elif e.state_code == _QL_RISE:
        _beast_step(e)
        if ud['vz'] > QL_RISE_V_END:
            eng.destroy(e)
            _son_return(ud['coord'])                       # -150 → dispatcher 0x3c 同 tick: 烟 + 翻跟头现身


def spawn_qinglong_beast(battle, caster, coord: "Entity", atlas: int) -> None:
    """青龙: 神兽从屏顶减速飘到悬停点 + 100 tick 冰锥雨 + 大冰锥伤害 + 加速升空."""
    coord.user_data['eson_done'] = False
    _sfx(battle, SFX_QL_BEAST)   # exe case 0x1e: 神兽 spawn 播龙吟 0x147 (单次, 无 stop)
    victims = _eson_collect_victims(battle, caster)
    e = battle.engine.spawn(think_fn=qinglong_beast_think)
    e.atlas_slot = atlas
    e.frame_idx = 0
    e.flags |= 0x40
    e.user_data['kind'] = 'hit_effect'
    e.user_data['projectile'] = True
    e.user_data['draw_order'] = 10            # 青龙本体盖在冰锥之上 (exe y+1000 排序最前)
    e.user_data['battle'] = battle
    e.user_data['caster'] = caster
    e.user_data['coord'] = coord
    e.user_data['victims'] = victims
    cx, cy = _screen_center(battle, caster)
    e.x, e.y = cx, cy + (QL_SPAWN_Y_OFF << 16)
    e.user_data.update(ez=QL_SPAWN_Z, vz=QL_VZ0, age=QL_SPAWN_AGE)
    e.state_code = _QL_DESCEND
    _beast_step(e)                               # 出生当 tick 先走一步 (实录首帧 z=1842)


# ============ 白虎: 盘踞神兽 + 旋风吹起敌人再抛摔 (2026-10-22 实录 son_02_F221671 + reverse_engineering/baihu_wind_decomp.txt) ============
# dispatcher FUN_004f57ca: 与青龙同模板 (烟 → +32t 神兽 FUN_004f56e1: 同青龙的屏中心 y+1000 z1900 弹簧落到 1030 悬停).
# 悬停 → 挂 coil seq 0x671b48 (帧 0×19,1×4,2×4,[音 0x139],3×13,1×4, 定格 1) + 发 -100 → 每敌一个**风锚** FUN_004dae7c
# (fn 4da9ed, 不可见): 初始偏敌 (±(16+rand&7), ±(12+rand%6)), flags 0x31 = x/y 无阻尼弹簧 (加速度 1px) 朝敌格,
# 但只在 t%4==0 时走一步 (每 4 tick), 同时相位 +0x1000 (1/16 圈, 到 0x10000 归 0), 在锚位两侧出 2 个旋涡环
# (ehari00 slot 295): 位置 = 锚 + (sin(φ)×16, -cos(φ)×12) 与 φ+半圈, z 从 0 以 3|4 px/t 匀速上升 (出生先走一步),
# 按 z>>4 的 8 段换帧组, z>128 消失 (寿命 42|32). t%64==0 首敌播 0xdc.
# 敌人: t==8 挂旋转 seq 0x656ef8 (row4 列 0,3,1,2 各 ticks3=4 帧) + flags 0x71 (z 弹簧目标 0 加速度 2 = 重力),
# vz0 = (rand&7)/4; t<120 且 z<100: vz += 2.1 (浮在 ~100px 上下); 120≤t<140: vz += 4 (抛飞, t==120 首敌播 0xf4);
# t>120 且 z<1 落地: 播 0xf0, 停转, -200 (伤害飘字) + -250 (受击 seq + 两特效), 锚自毁.
# 0x32: 所有锚结束且飘字落定 → 神兽 -100 (定格, v=0 加速度 2 升空 29t) → -150 → 烟 + 翻跟头现身 (同青龙).
BH_ATLAS = 256
BH_COIL_SEQ = [('fm', BH_ATLAS, 0, 18), ('fm', BH_ATLAS, 1, 3), ('fm', BH_ATLAS, 2, 3), ('sound', 0x139, 0x0411),
               ('fm', BH_ATLAS, 3, 12), ('fm', BH_ATLAS, 1, 3), ('exit',)]            # @0x671b48
SFX_BH_WIND = 0xdc               # 旋风起 (E052): 锚 t%64==0 (t=0,64), 仅首敌
SFX_BH_ROAR = 0x139              # 白虎吼 (E145): coil seq 里的 sound op (悬停 +26t)
SFX_BH_FLING = 0xf4              # 抛天 (E076): 锚 t==120, 仅首敌
SFX_BH_SLAM = 0xf0               # 摔地 (E072): 每敌落地
BH_LIFT_START = 8
BH_LIFT_END = 120
BH_FLING_END = 140
BH_LIFT_HEIGHT = 100 << 16
BH_LIFT_ACCEL = 0x21999          # +2.1 px/t² (z<100 时)
BH_FLING_ACCEL = 0x40000         # +4 px/t²
BH_GRAVITY = 0x20000             # 弹簧目标 z=0 加速度 2
BH_SPIN_COLS = (0, 3, 1, 2)      # seq 0x656ef8 帧 16,19,17,18 = row4 列 0,3,1,2
BH_SPIN_FRAME_TICKS = 4          # ticks=3 → 实机 4 tick/帧
BH_ANCHOR_STEP = 4
BH_RING_RX, BH_RING_RY = 16, 12
WIND_ATLAS = 295                 # ehari00 旋涡环
# ehari00 21 帧: 按高度 8 段 (z>>4) 选帧组 PTR_DAT_00656ed8[band]: 低=小环(18-20), 高=大环(0-2)
WIND_BANDS = (
    (18, 19, 20), (15, 16, 17), (12, 13, 14), (9, 10, 11),
    (6, 7, 8), (3, 4, 5), (0, 1, 2), (0, 1, 2),
)
WIND_TOP = 128
_BH_DESCEND = 0
_BH_HOVER = 1
_BH_RISE_WAIT = 2
_BH_RISE = 3


def whirlwind_ring_think(e: "Entity", eng: "Engine") -> None:
    """旋涡环 FUN_004da929: 匀速上升 (vz 3|4), 帧组按 z>>4, z>128 消失."""
    ud = e.user_data
    if 'ring' not in ud:
        return
    e.z -= ud['vz'] << 16
    ud['life'] += 1
    h = -(e.z >> 16)
    band = min(7, max(0, h >> 4))
    e.frame_idx = WIND_BANDS[band][(ud['life'] // 2) % 3]
    if h > WIND_TOP:
        eng.destroy(e)


def _spawn_wind_pair(battle, ax: int, ay: int, phase: int) -> None:
    """锚位两侧 (相位差半圈) 各一个旋涡环: (sin φ × 16, -cos φ × 12); vz 随机 3|4, 出生先走一步."""
    import math
    for ph in (phase, (phase + 0x8000) & 0xffff):
        a = ph / 0x10000 * 2 * math.pi
        e = battle.engine.spawn(think_fn=whirlwind_ring_think)
        e.atlas_slot = WIND_ATLAS
        e.frame_idx = WIND_BANDS[0][0]
        e.flags |= 0x40
        e.x = ax + int(math.sin(a) * BH_RING_RX * 65536)
        e.y = ay - int(math.cos(a) * BH_RING_RY * 65536)
        e.z = 0
        e.user_data.update(kind='hit_effect', projectile=True, ring=True, life=0, vz=(battle.rng.randint(0, 1) + 3))
        whirlwind_ring_think(e, battle.engine)


def _bh_anchor_think(e: "Entity", eng: "Engine") -> None:
    """风锚 FUN_004da9ed: 驱动一个敌人的腾空/抛飞/落地 + 每 4 tick 走一步并出旋涡环."""
    ud = e.user_data
    if 'anchor' not in ud:
        return
    battle, caster, v = ud['battle'], ud['caster'], ud['victim']
    t = ud['t']
    if t == BH_LIFT_START and v.alive:
        ud['lifted'] = True
        ud['z'] = 0
        ud['vz'] = (battle.rng.randint(0, 7) << 16) >> 2
        ud['spin'] = 0
    if ud.get('lifted'):
        if t < BH_LIFT_END and ud['z'] < BH_LIFT_HEIGHT:
            ud['vz'] += BH_LIFT_ACCEL
        if BH_LIFT_END <= t < BH_FLING_END:
            ud['vz'] += BH_FLING_ACCEL
        if t == BH_LIFT_END and ud['first']:
            _sfx(battle, SFX_BH_FLING)
        ud['vz'] += BH_GRAVITY if ud['z'] < 0 else -BH_GRAVITY   # FUN_004c3211 flag 0x41 目标 z=0
        ud['z'] += ud['vz']
        v.wind_lift = max(0.0, ud['z'] / 65536)
        v.wind_spin_col = BH_SPIN_COLS[(ud['spin'] // BH_SPIN_FRAME_TICKS) % 4]
        ud['spin'] += 1
    if t < BH_LIFT_END and t % BH_ANCHOR_STEP == 0:
        if t % 64 == 0 and ud['first']:
            _sfx(battle, SFX_BH_WIND)
        for k in ('x', 'y'):                                 # flags 0x31: 每步 v += ±1px 朝敌格, pos += v
            ud['v' + k] += 1 if ud[k] < ud['t' + k] else -1
            ud[k] += ud['v' + k]
        ud['phase'] += 0x1000
        if ud['phase'] >= 0x10000:
            ud['phase'] = 0
        e.x, e.y = ud['x'] << 16, ud['y'] << 16
        _spawn_wind_pair(battle, e.x, e.y, ud['phase'])
    if t > BH_LIFT_END and ud.get('lifted') and ud['z'] < (1 << 16):
        _sfx(battle, SFX_BH_SLAM)
        v.wind_lift = 0.0
        v.wind_spin_col = -1
        from core.battle import combat
        combat._roll_damage_one(battle, caster, v, face_attacker=False)   # -200 飘字 + -250 受击 seq/特效
        ud['coord'].user_data['bh_anchors'] -= 1
        eng.destroy(e)
        return
    ud['t'] = t + 1


def _spawn_wind_anchor(battle, caster, coord: "Entity", victim, first: bool) -> None:
    rng = battle.rng
    vx, vy = _victim_ground(victim)
    tx, ty = vx >> 16, vy >> 16
    ox = (16 + rng.randint(0, 7)) * (1 if rng.randint(0, 1) else -1)
    oy = (12 + rng.randint(0, 5)) * (1 if rng.randint(0, 1) else -1)
    e = battle.engine.spawn(think_fn=_bh_anchor_think)
    e.flags = 0x800 | 0x10000
    e.user_data.update(kind='wind_anchor', projectile=True, anchor=True, battle=battle, caster=caster, coord=coord,
                       victim=victim, first=first, t=0, phase=0, x=tx + ox, y=ty + oy, tx=tx, ty=ty, vx=0, vy=0)
    e.x, e.y = (tx + ox) << 16, (ty + oy) << 16
    coord.user_data['bh_anchors'] = coord.user_data.get('bh_anchors', 0) + 1
    _bh_anchor_think(e, battle.engine)                       # 出生当 tick 先 think (实录 旋涡环与悬停同 tick)


def baihu_beast_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'victims' not in ud:
        return
    battle, caster, coord = ud['battle'], ud['caster'], ud['coord']
    if e.state_code == _BH_DESCEND:
        _beast_step(e)
        if ud['vz'] >= 0:
            from core.anim_engine.bytecode import tuple_to_bytecode
            battle.engine.attach_seq(e, tuple_to_bytecode(BH_COIL_SEQ))
            coord.user_data['bh_anchors'] = 0
            alive = [v for v in ud['victims'] if v.alive]
            for i, v in enumerate(alive):                    # -100: 每敌一个风锚
                _spawn_wind_anchor(battle, caster, coord, v, first=(i == 0))
            e.state_code = _BH_HOVER
    elif e.state_code == _BH_HOVER:
        if coord.user_data.get('bh_anchors', 0) == 0 and getattr(battle, 'float_pending', 0) == 0:
            e.state_code = _BH_RISE_WAIT                     # 0x32 → 下 tick 神兽 -100
    elif e.state_code == _BH_RISE_WAIT:
        e.flags &= ~0x20000
        ud['vz'] = 0
        e.state_code = _BH_RISE
    elif e.state_code == _BH_RISE:
        _beast_step(e)
        if ud['vz'] > QL_RISE_V_END:
            for v in ud['victims']:
                v.wind_lift = 0.0
                v.wind_spin_col = -1
            eng.destroy(e)
            _son_return(coord)


def spawn_baihu_beast(battle, caster, coord: "Entity", atlas: int) -> None:
    """白虎: 同青龙的进场弹簧 + 悬停 coil seq + 风锚吹起/抛摔每个敌人 + 飘字落定后升空."""
    coord.user_data['eson_done'] = False
    victims = _eson_collect_victims(battle, caster)
    e = battle.engine.spawn(think_fn=baihu_beast_think)
    e.atlas_slot = atlas
    e.frame_idx = 0
    e.flags |= 0x40
    e.user_data.update(kind='hit_effect', projectile=True, draw_order=10, battle=battle, caster=caster,
                       coord=coord, victims=victims, ez=QL_SPAWN_Z, vz=QL_VZ0, age=QL_SPAWN_AGE)
    cx, cy = _screen_center(battle, caster)
    e.x, e.y = cx, cy + (QL_SPAWN_Y_OFF << 16)
    e.state_code = _BH_DESCEND
    _beast_step(e)


# ============ 朱雀: 红凤凰悬停 + 火雨 (exe FUN_004f6985 / 4f68a5 / 4f6764 / 4f663a / 4f65c7; 实录 son_05_F231303) ============
# 悬停 (age 29) 起: age%8==0 且 age < 结束-30 时落火 (12 颗, tick 88..176): FUN_004f663a 以**施法者**为中心:
# r = rand&127, x = 施法者x ± r, y = 施法者y+1 ± (128-r)×3/4 (菱形), z 640 vz -48 匀速 (首帧 592), ej3(294) 帧 60, 播 0xd7;
# 落地 (z<1) 挂火爆 seq 0x655fa4 (fire01(309) 帧 0-10 各 1t) 完自毁. 结束 (age 157): 对自己发 -200 (全敌飘字) + -250
# (全敌受击 seq + 方向 starburst), 升空 (z>1800, 28t) → -100 → dispatcher 0x1e 等飘字落定 → 烟 + 翻跟头现身.
ZHUQUE_ATLAS = 262
SFX_ZQ_BEAST = 0x146
SFX_ZQ_FIRE = 0xd7
FIREBALL_ATLAS = 294
FIREBALL_FRAME = 60
FIRE_BURST_ATLAS = 309
FIRE_FALL_HEIGHT = 640
FIRE_FALL_VZ = 48
_ZQ_DESCEND = 0
_ZQ_HOVER = 1
_ZQ_RISE = 2


def _spawn_fire_burst(battle, x, y) -> None:
    """火球落地: 火焰爆 (fire01 帧0-10 各 1t, seq 跑完自动回收) — exe seq 0x655fa4."""
    from core.anim_engine.bytecode import tuple_to_bytecode
    seq = [('fm', FIRE_BURST_ATLAS, f, 1) for f in range(11)] + [('exit',)]
    e = battle.engine.spawn()
    e.x, e.y, e.z = x, y, 0
    e.user_data['kind'] = 'hit_effect'
    battle.engine.attach_seq(e, tuple_to_bytecode(seq))


def fire_rain_think(e: "Entity", eng: "Engine") -> None:
    """下落火球 FUN_004f65c7: 匀速 48px/t, z<1 → 火焰爆 + 自身消失."""
    ud = e.user_data
    if 'fire' not in ud:
        return
    e.z += FIRE_FALL_VZ << 16
    if e.z >= 0:
        e.z = 0
        _spawn_fire_burst(ud['battle'], e.x, e.y)
        eng.destroy(e)


def _spawn_fireball(battle, caster) -> None:
    rng = battle.rng
    cx, cy = _victim_ground(caster)
    r = rng.randint(0, 127)
    dy = (128 - r) * 3 // 4
    e = battle.engine.spawn(think_fn=fire_rain_think)
    e.atlas_slot = FIREBALL_ATLAS
    e.frame_idx = FIREBALL_FRAME
    e.flags |= 0x40
    e.x = cx + ((r if rng.randint(0, 1) else -r) << 16)
    e.y = cy + (1 << 16) + ((dy if rng.randint(0, 1) else -dy) << 16)
    e.z = -(FIRE_FALL_HEIGHT << 16)
    e.user_data.update(kind='hit_effect', projectile=True, fire=True, battle=battle)
    _sfx(battle, SFX_ZQ_FIRE)
    fire_rain_think(e, battle.engine)             # 出生当 tick 先走一步 (实录首帧 z=592)


def zhuque_beast_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'victims' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    ud['age'] += 1
    age = ud['age']
    if e.state_code == _ZQ_DESCEND:
        _beast_step(e)
        if ud['vz'] >= 0:
            ud['end'] = age + BEAST_HOVER_TICKS
            e.state_code = _ZQ_HOVER
    elif e.state_code == _ZQ_HOVER:
        if age % 8 == 0 and age < ud['end'] - BEAST_LEAD_TICKS:
            _spawn_fireball(battle, caster)
        if age >= ud['end']:
            for v in ud['victims']:                      # -200 全敌飘字, 再 -250 全敌受击 + 方向特效
                _damage_only(battle, caster, v)
            for v in ud['victims']:
                _react_dir(battle, caster, v)
            _beast_rise_start(e)
            e.state_code = _ZQ_RISE
    elif e.state_code == _ZQ_RISE:
        if _beast_rise_step(e, by_z=True):
            ud['coord'].user_data['eson_done'] = True   # -100 → 0x1e 等飘字落定再现身
            eng.destroy(e)


def spawn_zhuque_beast(battle, caster, coord: "Entity", atlas: int) -> None:
    """朱雀: 红凤凰弹簧飘落悬停 + 12 颗火雨 + 末尾全敌伤害 + 升空."""
    _sfx(battle, SFX_ZQ_BEAST)                # exe case 0x19: 召唤朱雀播 0x146
    coord.user_data['return_waits_floats'] = True
    _beast_spawn(battle, caster, coord, atlas, zhuque_beast_think)


# ============ 玄武: 盘踞 + 地震 + 末尾每敌落石 (exe FUN_004f71b0 / 4f70d0 / 4f6f63 / 4dc42f / 4dc371; 实录 son_06_F236103) ============
# 悬停 (age 29): FUN_004d8c81(10,10,1000) 地震 (相机每 tick ±10px 随机, 播 0xe3) + 挂 coil seq 0x671c68
# (音 0x145, 帧 0 t8, 1 t8, 2 t15, 循环). age == 结束-30 (127, tick 183): 每敌落石 FUN_004dc42f: 敌 (x,y) z = 敌z+600,
# vz -64 匀速 (首帧 536), 随机 eba00(320)/eba01(321), 下落 seq 帧 0 t2; 落地 (z<1): 播 0xf6 + -250 (受击 seq + 方向特效)
# + 落地 seq (320: 帧 1,2,3 t2 / 321: 帧 1,2,3,4 t2) 完 → -200 (飘字) 自毁. 结束 (157): 停 seq + 停地震 (停 0xe3), 升空 28t.
XW_ATLAS = 263
XW_COIL_SEQ = [('sound', 0x145, 0x0411), ('fm', XW_ATLAS, 0, 8), ('fm', XW_ATLAS, 1, 8), ('fm', XW_ATLAS, 2, 15), ('loop',)]
XW_SHAKE_AMP = 10
XW_ROCK_VARIANTS = (320, 321)
XW_ROCK_LAND_FRAMES = {320: (1, 2, 3), 321: (1, 2, 3, 4)}
XW_ROCK_HEIGHT = 600
XW_ROCK_VZ = 64
SFX_XW_COIL = 0x145
SFX_XW_QUAKE = 0xe3
SFX_XW_ROCK = 0xf6
_XW_DESCEND = 0
_XW_COIL = 1
_XW_RISE = 2
_XW_ROCK_FALL = 0
_XW_ROCK_SHATTER = 1


def falling_rock_think(e: "Entity", eng: "Engine") -> None:
    """玄武落石 FUN_004dc371: 匀速落下 → 落地 0xf6 + -250 → 碎裂 seq → 完 -200 飘字 → 自毁."""
    ud = e.user_data
    if 'rock' not in ud:
        return
    battle, caster, victim = ud['battle'], ud['caster'], ud['victim']
    if e.state_code == _XW_ROCK_FALL:
        e.z += XW_ROCK_VZ << 16
        if e.z >= 0:
            from core.anim_engine.bytecode import tuple_to_bytecode
            e.z = 0
            _sfx(battle, SFX_XW_ROCK)
            _react_dir(battle, caster, victim)
            land = XW_ROCK_LAND_FRAMES[ud['variant']]
            battle.engine.attach_seq(e, tuple_to_bytecode([('fm', ud['variant'], f, 2) for f in land] + [('exit',)]))
            e.state_code = _XW_ROCK_SHATTER
    elif e.state_code == _XW_ROCK_SHATTER:
        if not e.is_playing():
            _damage_only(battle, caster, victim)
            eng.destroy(e)


def _spawn_rock_fall(battle, caster, victim) -> None:
    from core.anim_engine.bytecode import tuple_to_bytecode
    variant = XW_ROCK_VARIANTS[battle.rng.randint(0, 1)]
    vx, vy = _victim_ground(victim)
    e = battle.engine.spawn(think_fn=falling_rock_think)
    e.atlas_slot = variant
    e.frame_idx = 0
    e.flags |= 0x40
    e.x, e.y = vx, vy
    e.z = -(XW_ROCK_HEIGHT << 16)
    e.user_data.update(kind='hit_effect', projectile=True, rock=True, variant=variant, battle=battle,
                       caster=caster, victim=victim)
    e.state_code = _XW_ROCK_FALL
    battle.engine.attach_seq(e, tuple_to_bytecode([('fm', variant, 0, 2), ('exit',)]))
    falling_rock_think(e, battle.engine)          # 出生当 tick 先走一步 (实录首帧 z=536)


def xuanwu_beast_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'victims' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    ud['age'] += 1
    age = ud['age']
    if e.state_code == _XW_DESCEND:
        _beast_step(e)
        if ud['vz'] >= 0:
            from core.anim_engine.bytecode import tuple_to_bytecode
            ud['end'] = age + BEAST_HOVER_TICKS
            _sfx(battle, SFX_XW_QUAKE)
            battle.engine.attach_seq(e, tuple_to_bytecode(XW_COIL_SEQ))
            e.state_code = _XW_COIL
    elif e.state_code == _XW_COIL:
        battle.shake_offset = (battle.rng.randint(-XW_SHAKE_AMP, XW_SHAKE_AMP), battle.rng.randint(-XW_SHAKE_AMP, XW_SHAKE_AMP))
        if age == ud['end'] - BEAST_LEAD_TICKS:
            for v in ud['victims']:
                if v.alive:
                    _spawn_rock_fall(battle, caster, v)
        if age >= ud['end']:
            battle.shake_offset = (0, 0)
            _sfx_stop(battle, SFX_XW_QUAKE)
            _beast_rise_start(e)
            e.state_code = _XW_RISE
    elif e.state_code == _XW_RISE:
        if _beast_rise_step(e, by_z=True):
            ud['coord'].user_data['eson_done'] = True
            eng.destroy(e)


def spawn_xuanwu_beast(battle, caster, coord: "Entity", atlas: int) -> None:
    """玄武: 弹簧飘落盘踞 + 地震 + 末尾每敌落石 (落地受击, 碎完飘字) + 升空."""
    coord.user_data['return_waits_floats'] = True
    _beast_spawn(battle, caster, coord, atlas, xuanwu_beast_think)


# ============ 月兔: 魔画盘踞 + 末 30 tick 弹幕 (exe FUN_004f7a11 / 4f7931 / 4f77ab / 4e8192 / 4e8152; 实录 son_07_F238470) ============
# 召唤播 0x108 (返程 0x1e 切断). 悬停 (age 29) 挂 seq 0x671c8c: eson07a(264) 帧 0-7 t3, 音 0x12a, 帧 8 t3, 音 0xa9, 帧 9 t3,
# eson07b(265) 帧 0-6 t3, 循环. age ≥ 结束-30 (tick 183..212) **每 tick**: 每敌 -250 (受击 seq 重挂 + 两特效) + 2 星光
# FUN_004e8192 (ds_chiri(227) seq 0x66f2dc 帧 8-11 t2, 12-15 t1 = 20t; z 敌+72, vz 8 每 tick -0.5, vx ∓1) + 播 0xd4.
# 结束 (157): 停 seq, -200 全敌飘字, 升空 28t → -100 → 0x1e 等飘字 → 停 0x108 + 烟 + 现身.
YT_ATLAS = 264
YT_COIL_SEQ = ([('fm', 264, i, 3) for i in range(8)] + [('sound', 0x12a, 0x0411), ('fm', 264, 8, 3), ('sound', 0xa9, 0x0411), ('fm', 264, 9, 3)]
               + [('fm', 265, i, 3) for i in range(7)] + [('loop',)])
YT_SPARKLE_ATLAS = 227
YT_SPARKLE_SEQ = [('fm', 227, f, 2) for f in (8, 9, 10, 11)] + [('fm', 227, f, 1) for f in (12, 13, 14, 15)] + [('exit',)]
YT_SPARKLE_Z = 72
YT_SPARKLE_VZ = 0x80000          # 8 px/t
YT_SPARKLE_GRAVITY = 0x8000      # 0.5 px/t² (弹簧目标 z 0)
SFX_YT_BEAST = 0x108
SFX_YT_BARRAGE = 0xd4
_YT_DESCEND = 0
_YT_HOVER = 1
_YT_RISE = 2


def yuetu_sparkle_think(e: "Entity", eng: "Engine") -> None:
    """星光 FUN_004e8152: flags 0x51 (x 匀速 ∓1, z 弹簧目标 0 加速度 0.5 从 vz 8 减速上升); seq 播完消失."""
    ud = e.user_data
    if 'sparkle' not in ud:
        return
    e.x += ud['vx']
    ud['vz'] += YT_SPARKLE_GRAVITY if ud['ez'] < 0 else -YT_SPARKLE_GRAVITY
    ud['ez'] += ud['vz']
    e.z = -ud['ez']
    if not e.is_playing():
        eng.destroy(e)


def _spawn_yuetu_sparkles(battle, victim) -> None:
    from core.anim_engine.bytecode import tuple_to_bytecode
    vx, vy = _victim_ground(victim)
    for i in range(2):
        e = battle.engine.spawn(think_fn=yuetu_sparkle_think)
        e.atlas_slot = YT_SPARKLE_ATLAS
        e.frame_idx = 8
        e.flags |= 0x40
        e.x, e.y = vx, vy
        e.user_data.update(kind='hit_effect', projectile=True, sparkle=True, draw_order=20,
                           vx=(-1 if i == 0 else 1) << 16, vz=YT_SPARKLE_VZ, ez=YT_SPARKLE_Z << 16)
        e.z = -e.user_data['ez']
        battle.engine.attach_seq(e, tuple_to_bytecode(YT_SPARKLE_SEQ))


def yuetu_beast_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'victims' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    ud['age'] += 1
    age = ud['age']
    if e.state_code == _YT_DESCEND:
        _beast_step(e)
        if ud['vz'] >= 0:
            from core.anim_engine.bytecode import tuple_to_bytecode
            ud['end'] = age + BEAST_HOVER_TICKS
            battle.engine.attach_seq(e, tuple_to_bytecode(YT_COIL_SEQ))
            e.state_code = _YT_HOVER
    elif e.state_code == _YT_HOVER:
        if age >= ud['end'] - BEAST_LEAD_TICKS:
            for v in ud['victims']:
                if v.alive:
                    _ql_rain_react(battle, caster, v)         # -250: 受击 seq 重挂 + 两特效 (每 tick)
                    _spawn_yuetu_sparkles(battle, v)
            _sfx(battle, SFX_YT_BARRAGE, solo=True)
        if age >= ud['end']:
            for v in ud['victims']:
                _damage_only(battle, caster, v)
            _beast_rise_start(e)
            e.state_code = _YT_RISE
    elif e.state_code == _YT_RISE:
        if _beast_rise_step(e, by_z=True):
            ud['coord'].user_data['eson_done'] = True
            eng.destroy(e)


def spawn_yuetu_beast(battle, caster, coord: "Entity", atlas: int) -> None:
    """美丽月兔: 魔画弹簧飘落盘踞 + 末 30 tick 星光弹幕 (每 tick 受击) + 全敌伤害 + 升空."""
    _sfx(battle, SFX_YT_BEAST)
    coord.user_data['beast_sound'] = SFX_YT_BEAST    # 返程 0x1e 切断
    coord.user_data['return_waits_floats'] = True
    _beast_spawn(battle, caster, coord, atlas, yuetu_beast_think, draw_order=0)


# ============ M凤凰: 复活术 (exe 2026-10-23 实录 son_09_F10548 + reverse_engineering/mfeng_decomp.txt) ============
# dispatcher FUN_004f8f71: 翻跟头 → 0x14 烟 + 隐身 +32t → 0x19 FUN_004f8e70 召凤凰 (+0x78=1) → 0x1e 等 +0x78==0 (凤凰 -100)
#   且 +0x7a==0 (每个目标的回血飘字 -20) → 烟 + 现身. -200 (0xffffff38): 对**目标列表**每人 (= 光标选中的倒下队友, 不含施法者):
#   think 换回 FUN_004bb56b (复活/待机) + 0x10000 idle + FUN_004d074e 白色回血飘字, +0x7a++.
# 凤凰 FUN_004f8e70/4f8ce6: eson09 267 帧 0, 与其它神兽**同款弹簧进场** (屏中心 x, y+1000, z1900, vz-60, a2 → 29t 悬停 z1030)
#   → 0xef, end = age+64; end-30..end **每 tick** 对每个目标撒 1 片羽毛 + 0x111 (31 次); end: DAT_0086a7dc=1 (云散), -200,
#   升空 (目标 z2000, v0 a2) z>1800 → -100 自毁 (28t).
# 祥云 FUN_004f899d/4f88ad ×8 (帧 1 左 / 2|3 右, z1000, y = 屏中心 y+1000 -140 + rand%300): 左云生在 屏中心 x-900-rand%160
#   vx+60 a-2, 右云 +900+rand%160 vx-60 a+2 (生 tick 先走一步); |vx|≤2 → a=0 悬停 (vx 仍 2 慢漂);
#   凤凰 end → a = ±2 向外 (vx<1 → -2) 加速, |vx|>60 自毁 (30t).
# 羽毛 FUN_004f8bc6/4f8b51: 生在目标 (x,y) z128, vx,vy = (rand&31-16)/16, vz = (rand&63)/16 (向上), a 0.25 弹簧朝 z0
#   (v += ±a; z += v), vz 恰为 0 时 a/=4 (慢落 → 活满 64t); age>63 或 z<1 自毁; seq PTR_DAT_00656abc[rand&3]:
#   e00 247 帧 (30|33|36|39)+0..2 各 2t 循环.
MF_ATLAS = 267                  # eson09 帧0 大凤凰, 帧 1-3 祥云
MF_HOLD_TICKS = 64              # 悬停 (exe +0x40)
MF_FEATHER_LEAD = 30            # end-0x1e 起撒羽毛
MF_FEATHER_ATLAS = 247          # e00
MF_FEATHER_VARIANTS = ((30, 31, 32), (33, 34, 35), (36, 37, 38), (39, 40, 41))
MF_FEATHER_FRAME_TICKS = 1      # seq 656abc 每帧 ticks=1 (引擎显示 2t; 实录 son_09 "36 37×2 38×2")
MF_FEATHER_Z = 128 << 16        # exe 0x800000
MF_FEATHER_ACCEL = 0x4000       # 0.25 px/t² 弹簧朝 z0
MF_FEATHER_MAX_AGE = 0x3f
SFX_MF_LAND = 0xef              # 凤凰悬停音 (E071)
SFX_MF_FEATHER = 0x111          # 羽毛音 (E105) 每 tick
MF_CLOUD_COUNT = 8
MF_CLOUD_X_OFF = 900            # 屏中心 x ± (900 + rand%160)
MF_CLOUD_X_RAND = 160
MF_CLOUD_Y_OFF = BEAST_SPAWN_Y_OFF - 140   # 屏中心 y + 1000 - 140 + rand%300
MF_CLOUD_Y_RAND = 300
MF_CLOUD_Z = 1000
MF_CLOUD_V0 = 60 << 16
MF_CLOUD_ACCEL = 2 << 16
MF_CLOUD_V_MIN = 2 << 16        # |vx| ≤ 2 → 悬停
MF_CLOUD_V_OUT = 60 << 16       # 飘出 |vx| > 60 → 自毁
_MF_DESCEND = 0
_MF_HOLD = 1
_MF_RISE = 2
_MFC_IN = 0
_MFC_HOVER = 1
_MFC_OUT = 2


def mfeng_feather_think(e: "Entity", eng: "Engine") -> None:
    """羽毛 FUN_004f8b51: 弹簧朝 z0 (a 0.25, vz==0 时 a/=4), age>63 或 z<1 自毁."""
    ud = e.user_data
    if 'feather' not in ud:
        return
    e.x += ud['vx']
    e.y += ud['vy']
    ud['vz'] += -ud['az'] if ud['ez'] > 0 else ud['az']
    ud['ez'] += ud['vz']
    e.z = -ud['ez']
    if ud['vz'] == 0:
        ud['az'] >>= 2
    if ud['age'] > MF_FEATHER_MAX_AGE or ud['ez'] < FP_ONE:   # exe +0x144 出生帧为 0, 实录活 64 帧
        eng.destroy(e)
    ud['age'] += 1


def _spawn_mfeng_feather(battle, ally) -> None:
    """FUN_004f8bc6: 目标脚下 (x,y) z128, 随机小速度, 4 变体 seq 之一. 出生 tick 先走一步 (池序)."""
    from core.anim_engine.bytecode import tuple_to_bytecode
    rng = battle.rng
    vx, vy = _victim_ground(ally)
    e = battle.engine.spawn(think_fn=mfeng_feather_think)
    e.atlas_slot = MF_FEATHER_ATLAS
    e.flags |= 0x40
    e.x, e.y = vx, vy
    e.user_data.update(kind='hit_effect', projectile=True, feather=True, draw_order=20,
                       vx=((rng.randrange(32) - 16) << 16) >> 4, vy=((rng.randrange(32) - 16) << 16) >> 4,
                       vz=(rng.randrange(64) << 16) >> 4, az=MF_FEATHER_ACCEL, ez=MF_FEATHER_Z, age=0)
    e.z = -e.user_data['ez']
    var = MF_FEATHER_VARIANTS[rng.randrange(4)]
    e.frame_idx = var[0]
    battle.engine.attach_seq(e, tuple_to_bytecode([('fm', MF_FEATHER_ATLAS, f, MF_FEATHER_FRAME_TICKS) for f in var] + [('loop',)]))
    mfeng_feather_think(e, battle.engine)


def _mfeng_revive(battle, targets) -> None:
    """exe -200: 目标 (倒下队友) think 换回待机 + 白色回血飘字 (+0x7a 计数, 落定 -20). 回满 = 数值近似."""
    from core.battle.data import DamageEvent
    from core.battle.combat import push_damage_event
    for u in targets:
        u.hp = u.max_hp
        u.shown_hp_override = None
        u.settle_pending = False
        u.settle_batch = False
        u.death_anim_time_ms = -1
        u.reaction_seq = None
        u.reaction_frame = None
        u.reaction_saved_facing = None
        push_damage_event(battle, u, DamageEvent(u.hp, u.hp, u.x, u.y, heal=True))


def mfeng_cloud_think(e: "Entity", eng: "Engine") -> None:
    """祥云 FUN_004f88ad: FUN_004c3211 (v += a; x += v) 减速到 |vx|≤2 → a=0 漂 → 凤凰走 → 向外 a±2 → |vx|>60 自毁."""
    ud = e.user_data
    if 'cloud' not in ud:
        return
    ud['vx'] += ud['ax']
    e.x += ud['vx']
    if e.state_code == _MFC_IN:
        if abs(ud['vx']) <= MF_CLOUD_V_MIN:
            ud['ax'] = 0
            e.state_code = _MFC_HOVER
    elif e.state_code == _MFC_HOVER:
        # exe 凤凰 (下标小) 先于云 think, 同 tick 置 DAT_0086a7dc 云即起飞; 我们池序不定 → 按绝对 tick 比较
        if eng._tick_id >= ud['coord'].user_data.get('mf_leave_tick', 1 << 60):
            ud['ax'] = -MF_CLOUD_ACCEL if ud['vx'] < FP_ONE else MF_CLOUD_ACCEL
            e.state_code = _MFC_OUT
    elif e.state_code == _MFC_OUT:
        if abs(ud['vx']) > MF_CLOUD_V_OUT:
            eng.destroy(e)


def _spawn_mfeng_clouds(battle, caster, coord) -> None:
    """FUN_004f899d ×8: rand&1 定左右; 左 帧1, 右 帧 2+(rand&1); y/z 同神兽基准 (屏中心 y+1000 带, z1000)."""
    rng = battle.rng
    cx, cy = _screen_center(battle, caster)
    for _ in range(MF_CLOUD_COUNT):
        e = battle.engine.spawn(think_fn=mfeng_cloud_think)
        e.atlas_slot = MF_ATLAS
        e.flags |= 0x40
        if rng.randrange(2) == 0:
            e.x = cx - ((MF_CLOUD_X_OFF + rng.randrange(MF_CLOUD_X_RAND)) << 16)
            vx, ax = MF_CLOUD_V0, -MF_CLOUD_ACCEL
            e.frame_idx = 1
        else:
            e.x = cx + ((MF_CLOUD_X_OFF + rng.randrange(MF_CLOUD_X_RAND)) << 16)
            vx, ax = -MF_CLOUD_V0, MF_CLOUD_ACCEL
            e.frame_idx = 2 + rng.randrange(2)
        e.y = cy + ((MF_CLOUD_Y_OFF + rng.randrange(MF_CLOUD_Y_RAND)) << 16)
        e.z = -(MF_CLOUD_Z << 16)
        e.user_data.update(kind='hit_effect', projectile=True, cloud=True, draw_order=12, coord=coord, vx=vx, ax=ax)
        e.state_code = _MFC_IN
        mfeng_cloud_think(e, battle.engine)          # 出生 tick 先走一步 (实录首帧已位移 60)


def mfeng_beast_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'allies' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    ud['age'] += 1
    age = ud['age']
    if e.state_code == _MF_DESCEND:
        _beast_step(e)
        if ud['vz'] >= 0:
            _sfx(battle, SFX_MF_LAND)
            ud['end'] = age + MF_HOLD_TICKS
            ud['coord'].user_data['mf_leave_tick'] = eng._tick_id + MF_HOLD_TICKS   # 云散 = 凤凰 end 当 tick
            e.state_code = _MF_HOLD
    elif e.state_code == _MF_HOLD:
        if age >= ud['end'] - MF_FEATHER_LEAD:
            for u in ud['allies']:
                _spawn_mfeng_feather(battle, u)
            _sfx(battle, SFX_MF_FEATHER, solo=True)
        if age >= ud['end']:
            _mfeng_revive(battle, ud['allies'])         # -200
            _beast_rise_start(e)
            e.state_code = _MF_RISE
    elif e.state_code == _MF_RISE:
        if _beast_rise_step(e, by_z=True):
            ud['coord'].user_data['eson_done'] = True   # -100 → 0x1e 等飘字落定再现身
            eng.destroy(e)


def spawn_mfeng_beast(battle, caster, coord: "Entity", atlas: int) -> None:
    """M凤凰: 凤凰弹簧进场悬停 64t, 末 30t 每 tick 撒羽毛, 末尾复活倒下队友 (白字回满) + 升空; 8 朵祥云两侧对飞."""
    party = battle.players if caster.is_player else battle.enemies
    allies = [u for u in party if not u.alive]   # 目标列表 = 倒下的队友
    coord.user_data['return_waits_floats'] = True
    e = _beast_spawn(battle, caster, coord, atlas, mfeng_beast_think)
    e.user_data['allies'] = allies
    _spawn_mfeng_clouds(battle, caster, coord)


# ============ 酷酷猫: 笑脸猫五段演出 + 解异常 (exe FUN_004f5f0d spawn + FUN_004f5ecc think + seq 0x671b80) ============
# 原版: "变成笑容猫, 解除全部的异常状态". 静态居中播放五段动画 (eson04a-e 257-261): 黑剪影→橙猫→
# 逐级放大到大笑脸 (柴郡猫式咧嘴, 末段只剩漂浮的大笑). think 无物理 (静态), seq 播完发-100 销毁.
# ⚠目标=队友(解异常治疗类, 非攻击). **解异常暂占位** (无异常状态系统, 留 _kukumao_cure 钩子).
KUKUMAO_Y_OFF = 800             # exe FUN_004f5f0d: x = 屏幕中心 x, y = 屏幕中心 y + 800, z = 800 (实录 d=(+1,+777) z=800) → 画在屏幕中心
KUKUMAO_Z = 800
SFX_KUKUMAO_RETURN = 0x128      # dispatcher 0x28 返程烟前播 0x128 (不是通常的 0x129)
# seq 0x671b80 (tools/verify_seqs 逐 op 核对): eson04a 帧0-4 → b/c/d/e 各(长hold帧0 + 帧1-3快闪),
# 每段开头 sound 0x121 (E121 猫叫) 共 5 次 —— 首段在帧 0 前, 后四段在 24 tick hold 之后.
SFX_KUKUMAO = 0x121
KUKUMAO_SEQ = (
    [('sound', SFX_KUKUMAO, 0x0411)] + [('fm', 257, i, 3) for i in range(5)]
    + [('fm', 258, 0, 24), ('sound', SFX_KUKUMAO, 0x0411)] + [('fm', 258, i, 3) for i in (1, 2, 3)]
    + [('fm', 259, 0, 24), ('sound', SFX_KUKUMAO, 0x0411)] + [('fm', 259, i, 3) for i in (1, 2, 3)]
    + [('fm', 260, 0, 24), ('sound', SFX_KUKUMAO, 0x0411)] + [('fm', 260, i, 3) for i in (1, 2, 3)]
    + [('fm', 261, 0, 24), ('sound', SFX_KUKUMAO, 0x0411)] + [('fm', 261, i, 3) for i in (1, 2, 3)]
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
    cx, cy = _screen_center(battle, caster)
    e.x, e.y = cx, cy + (KUKUMAO_Y_OFF << 16)
    e.z = -(KUKUMAO_Z << 16)
    coord.user_data['return_sound'] = SFX_KUKUMAO_RETURN
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
# 2026-10-23 实录 son_08_F1653533 + reverse_engineering/luanwu_decomp.txt:
# cast seq 0x671d40[dir] = fm_mode1 18 (ps_CSON102) 列 2 t3, 列 3 t3, -100, exit (+7 定格); -100 → 协调实体 FUN_004f82c9:
# 出生 tick 生成 16 块滑板 (FUN_004f8188) + 播 0xb1; age%20==0 → -250 全敌受击 + 两特效 + 0xbd; age==128 → 滑板自毁 + -200 全敌飘字.
# 滑板: 位置 = 屏幕矩形内均匀随机 (cam-w/2 + rand%w, cam-h/2 + rand%h), z 48, flags 0x31 无加速度 = 匀速, 角度 a=rand%1000/1000 圈,
# vx = sin(a)×48, vy = cos(a)×48, 帧 = DAT_00671e14[((a+0xf000)&0xffff)*8>>16]; 出屏幕左右: 帧查 671e1c 表 + vx 取反, 上下: 671e24 + vy 取反.
LUANWU_COUNT = 16
LUANWU_SPEED = 48
LUANWU_HEIGHT = 48
LUANWU_DURATION = 128
LUANWU_REACT_INTERVAL = 20
LUANWU_SCREEN = (640, 480)
LUANWU_CAST_SLOT = 18           # ps_CSON102 在 ps_ 登记表的绝对下标 (core.grid_atlas_table)
LUANWU_SIG = -1008
LUANWU_DIR_FRAMES = (4, 3, 2, 1, 0, 7, 6, 5)      # DAT_00671e14
LUANWU_FLIP_X = (0, 7, 6, 5, 4, 3, 2, 1)          # DAT_00671e1c
LUANWU_FLIP_Y = (4, 3, 2, 1, 0, 7, 6, 5)          # DAT_00671e24
_LUANWU_RUN = 240
SFX_LUANWU_START = 0xb1
SFX_LUANWU_HIT = 0xbd


def _luanwu_cast_seq(row: int) -> list[tuple]:
    # exe 这里是 signal -100 (dispatcher 召协调实体); 我们用专用信号 -1008 走实体 on_signal 回调, 避免 tactics 把它当普攻 IMPACT 结算
    return [('fm_mode1', LUANWU_CAST_SLOT, row * 4 + 2, 3), ('fm_mode1', LUANWU_CAST_SLOT, row * 4 + 3, 3), ('jump', LUANWU_SIG), ('exit',)]


def _luanwu_screen_rect(battle, caster) -> tuple[int, int, int, int]:
    view = getattr(battle, 'view_center_world', None)
    if view is None:
        from core.sprites.base import TILE_W, TILE_H
        view = (caster.x * TILE_W + TILE_W // 2, caster.y * TILE_H + TILE_H // 2)
    w, h = LUANWU_SCREEN
    return view[0] - w // 2, view[1] - h // 2, w, h


def skateboard_think(e: "Entity", eng: "Engine") -> None:
    """滑板 FUN_004f803e: 匀速直线; 出屏幕矩形左右/上下边 → 翻帧 + 该轴速度取反; 协调实体结束 (luanwu_done) 自毁."""
    ud = e.user_data
    if 'skate' not in ud:
        return
    if ud['coord'].user_data.get('luanwu_done'):
        eng.destroy(e)
        return
    e.x += ud['vx']
    e.y += ud['vy']
    x0, y0, w, h = ud['rect']
    px, py = e.x >> 16, e.y >> 16
    if px < x0 or px > x0 + w:
        e.frame_idx = LUANWU_FLIP_X[e.frame_idx]
        ud['vx'] = -ud['vx']
    if py < y0 or py > y0 + h:
        e.frame_idx = LUANWU_FLIP_Y[e.frame_idx]
        ud['vy'] = -ud['vy']


def _spawn_skateboard(battle, caster, coord, rect) -> None:
    import math
    rng = battle.rng
    x0, y0, w, h = rect
    a16 = (rng.randint(0, 999) << 16) // 1000                    # 角度 (16.16 圈)
    ang = a16 / 65536 * 2 * math.pi
    e = battle.engine.spawn(think_fn=skateboard_think)
    e.atlas_slot = LUANWU_SKATE_ATLAS
    e.frame_idx = LUANWU_DIR_FRAMES[(((a16 + 0xf000) & 0xffff) * 8) >> 16]
    e.flags |= 0x40
    e.x = (x0 + rng.randint(0, w - 1)) << 16
    e.y = (y0 + rng.randint(0, h - 1)) << 16
    e.z = -(LUANWU_HEIGHT << 16)
    e.user_data.update(kind='hit_effect', projectile=True, skate=True, draw_order=10, battle=battle, coord=coord,
                       vx=int(math.sin(ang) * LUANWU_SPEED * 65536), vy=int(math.cos(ang) * LUANWU_SPEED * 65536), rect=rect)


def luanwu_coord_think(e: "Entity", eng: "Engine") -> None:
    """超亂舞协调实体 FUN_004f82c9: 出生 16 滑板 + 0xb1; age%20 全敌 -250 (受击+两特效+0xbd); age 128 滑板自毁 + -200 飘字."""
    ud = e.user_data
    if 'luanwu' not in ud:
        return
    battle, caster, coord = ud['battle'], ud['caster'], ud['coord']
    ud['tick'] += 1
    t = ud['tick']                                        # 出生 tick (= cast -100) 后第 t tick; exe age = t-1
    if (t - 1) % LUANWU_REACT_INTERVAL == 0 and t <= LUANWU_DURATION:   # 实录 受击在 +8, +28, ..., +128
        for v in ud['victims']:
            _ql_rain_react(battle, caster, v)
        _sfx(battle, SFX_LUANWU_HIT)
    if t > LUANWU_DURATION:                               # age == 128 (实录 +136): 滑板自毁 + 飘字
        coord.user_data['luanwu_done'] = True
        for v in ud['victims']:
            _damage_only(battle, caster, v)
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
    e.user_data['spawned'] = True
    e.user_data['tick'] = 0
    e.state_code = _LUANWU_RUN
    rect = _luanwu_screen_rect(battle, caster)           # exe 协调实体 state -1 (出生 tick): 16 滑板 + 0xb1
    for _ in range(LUANWU_COUNT):
        _spawn_skateboard(battle, caster, coord, rect)       # luanwu_done 标在 son 协调实体上
    _sfx(battle, SFX_LUANWU_START)


# ============ 分身术: 孙悟空原地翻跟斗 + 对每敌召唤 4 分身围攻 (exe FUN_004f3ca3/3c73/3bdf/3876/3693) ============
# 原版: 孙悟空本体**原地翻跟斗不隐藏**; IMPACT 时 dispatcher **循环每个敌人** FUN_004f3c73(victim) 各建
# coordinator → 每敌上方先冒烟 + 依次投放 4 分身(围着**那个敌人**上/下/左/右)落地攻击 → 依次退场.
# 分身=复制孙悟空本体(cson_e0 atlas2): 落下→落地播方向攻击帧(dir*4..+3)→升空喷烟消失. **每敌的末身**
# 退场时对**那个敌人**结算伤害 (exe -250). 每敌各伤害一次.
FENSHEN_ATLAS = 0               # 全局 fm 槽 0 = cson1_g0 孙悟空普攻图 (16 帧 = 四方向×4); 分身攻击 seq 的 fm04 slot 0
FENSHEN_FALL_SHEET = "ps_CSON102"   # 跳姿 (下落/升空): exe DAT_00670d04/08: slot 2|0x20000, 帧 dir×4+3
FENSHEN_PS_GRID = (4, 64, 96, 32, 84)
FENSHEN_SPAWN_INTERVAL = 16     # spawner FUN_004f3bdf: age&0xf==0 投 1 分身, 共 4
FENSHEN_CLONES = [              # FUN_004f3876 idx → (敌格偏移 px, 分身朝向)
    (0, -32, 1), (0, 32, 0), (-40, 0, 3), (40, 0, 2),
]
FENSHEN_DROP_HEIGHT = 64        # z = 敌 z + 64, 弹簧目标 0 加速度 2 (重力) 落地 8t
FENSHEN_LEAVE_Z = 64            # 升空: v 2 加速度 2 (目标 1000), z > 64 (7t) 喷烟消失
FENSHEN_ATK_COUNT = 6
SFX_FENSHEN_CHATTER = 0x106
SFX_FENSHEN_PUNCH = (0xea, 0xbd, 0xcd, 0xcc)      # dispatcher -200 (首敌) switch rand&3
_FS_FALL = 0
_FS_ATTACK = 1
_FS_RISE = 2


def _fenshen_set_stand(e, d):
    """分身跳姿 (ps_CSON102 列 3 = 帧 d*4+3)."""
    e.user_data['ps_sheet'] = FENSHEN_FALL_SHEET
    e.user_data['ps_grid'] = FENSHEN_PS_GRID
    e.frame_idx = d * 4 + 3


def _fenshen_on_signal(e: "Entity", sig: int) -> None:
    """分身攻击 seq 的 signal -200 → dispatcher case -200: 受击 seq + 两特效 + 首敌随机拳击音."""
    ud = e.user_data
    if sig != -200:
        return
    v, battle = ud['victim'], ud['battle']
    if not v.alive:
        return
    if ud.get('primary'):
        _sfx(battle, SFX_FENSHEN_PUNCH[battle.rng.randint(0, 3)])
    _ql_rain_react(battle, ud['caster'], v)


def fenshen_clone_think(e: "Entity", eng: "Engine") -> None:
    """分身 FUN_004f3693: 跳姿落下 (重力 2) → 落地挂攻击 seq (core.fenshen_seqs, 6 拳越打越快, 每拳 -200 受击)
    → 跳姿升空 z>64 → 喷烟; 末身 -250 = 飘字伤害 + 切断 0x106."""
    ud = e.user_data
    if 'clone' not in ud:
        return
    d = ud['dir']
    if e.state_code == _FS_FALL:
        ud['vz'] += BEAST_ACCEL if ud['ez'] < 0 else -BEAST_ACCEL
        ud['ez'] += ud['vz']
        e.z = -(ud['ez'] << 16)
        if ud['ez'] < 1:
            from core.fenshen_seqs import FENSHEN_ATTACK_SEQS
            ud['ez'] = 0
            e.z = 0
            ud.pop('ps_sheet', None)
            e.atlas_slot = FENSHEN_ATLAS
            e.frame_idx = d * 4
            ud['on_signal'] = _fenshen_on_signal
            eng.attach_seq(e, FENSHEN_ATTACK_SEQS[d])
            e.state_code = _FS_ATTACK
    elif e.state_code == _FS_ATTACK:
        if not e.is_playing():
            ud['vz'] = 2
            _fenshen_set_stand(e, d)
            e.state_code = _FS_RISE
    elif e.state_code == _FS_RISE:
        ud['vz'] += BEAST_ACCEL                     # 目标 z 1000 → 一直加速
        ud['ez'] += ud['vz']
        e.z = -(ud['ez'] << 16)
        if ud['ez'] > FENSHEN_LEAVE_Z:
            battle = ud['battle']
            _spawn_smoke_at(battle, e.x >> 16, e.y >> 16, z_px=ud['ez'])
            if ud['is_last']:
                _damage_only(battle, ud['caster'], ud['victim'])
                _sfx_stop(battle, SFX_FENSHEN_CHATTER)
                ud['coord'].user_data['fs_spawners'] -= 1
            eng.destroy(e)


def _spawn_clone(battle, caster, coord, victim, idx: int, primary: bool = False) -> None:
    """FUN_004f3876: 敌格偏移处 z+64 出一个分身 (跳姿), 喷烟 (z+128)."""
    ox, oy, d = FENSHEN_CLONES[idx]
    vx, vy = _victim_ground(victim)
    e = battle.engine.spawn(think_fn=fenshen_clone_think)
    e.flags |= 0x40
    e.x = vx + (ox << 16)
    e.y = vy + (oy << 16)
    e.user_data.update(kind='hit_effect', projectile=True, clone=True, shadow=True, behind_units=(oy < 0), draw_order=8,
                       dir=d, is_last=(idx == 3), primary=primary, battle=battle, caster=caster, coord=coord,
                       victim=victim, ez=FENSHEN_DROP_HEIGHT, vz=0)
    e.z = -(FENSHEN_DROP_HEIGHT << 16)
    _fenshen_set_stand(e, d)
    e.state_code = _FS_FALL
    _spawn_smoke_at(battle, (vx >> 16) + ox, (vy >> 16) + oy, z_px=FENSHEN_DROP_HEIGHT * 2)
    fenshen_clone_think(e, battle.engine)       # 出生当 tick 先走一步


def fenshen_spawner_think(e: "Entity", eng: "Engine") -> None:
    """每敌一个 spawner FUN_004f3bdf: age&0xf==0 投 1 分身 (idx 0..3), 第 4 个后自毁."""
    ud = e.user_data
    if 'fenshen' not in ud:
        return
    ud['tick'] += 1
    if ud['tick'] % FENSHEN_SPAWN_INTERVAL == 1:
        _spawn_clone(ud['battle'], ud['caster'], ud['coord'], ud['victim'], ud['round'], primary=ud['primary'])
        ud['round'] += 1
        if ud['round'] >= 4:
            eng.destroy(e)


def spawn_fenshen(battle, caster, coord: "Entity") -> None:
    """分身术 -100: 每敌一个 spawner + 播 0x106 吱吱叫 (末身结算时切断)."""
    coord.user_data['eson_done'] = False
    victims = _eson_collect_victims(battle, caster)
    coord.user_data['fs_spawners'] = len(victims)
    for i, v in enumerate(victims):
        e = battle.engine.spawn(think_fn=fenshen_spawner_think)
        e.flags = 0x800 | 0x10000
        e.user_data.update(kind='son_aoe', projectile=True, fenshen=True, battle=battle, caster=caster, coord=coord,
                           victim=v, primary=(i == 0), round=0, tick=0)
    if victims:
        _sfx(battle, SFX_FENSHEN_CHATTER)


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
    e.user_data['flip_tick'] = 0        # _CAST 施法姿帧计时 (翻跟头本身已改走 attach_seq)
    e.user_data['phase_ticks'] = 0
    # ps_CSON102 简短施法姿: **0x04 分身 (PTR_00671b0c) + 0x08 超亂舞 (PTR_00671db0, 同位帧2/6)**.
    # 其余技能 cast = 翻跟斗本身 (槽5=ps_CSON105), 直接进 FLIP_OUT.
    if skill_id == 0x08:
        from core.anim_engine.bytecode import tuple_to_bytecode
        if caster.entity is None:
            caster.entity = battle.engine.spawn()
        ent = caster.entity
        ent.x = ent.y = ent.z = 0
        def _on_cast_sig(src, sig, coord=e):
            if sig == LUANWU_SIG and coord.state_code == _CAST:
                spawn_luanwu(battle, caster, coord)      # exe -100: 协调实体出生 tick 就生成 16 滑板 (实录 +7)
                coord.state_code = _TRANSFORM
        ent.user_data = {'unit': caster, 'on_signal': _on_cast_sig}
        battle.engine.attach_seq(ent, tuple_to_bytecode(_luanwu_cast_seq(_caster_cson_row(caster))))
        caster.cast_hold = True
        e.state_code = _CAST
    elif skill_id == 0x04:
        e.user_data['cast_row'] = _caster_cson_row(caster)
        e.user_data['cast_pose_idx'] = 0
        e.state_code = _CAST
        caster.cast_pose_frame = e.user_data['cast_row'] * 4 + CAST_POSE_COLS[0]
    else:
        e.state_code = _FLIP_OUT
        _flip_attach(battle, caster)              # exe case 10 attach 0x670dc4 (音效/跳弧内嵌 seq)
    caster.pending_caster_coord = e
    return e


def is_son_transform_skill(skill_id: int | None) -> bool:
    return skill_id is not None and skill_id in SON_TRANSFORM_SKILLS
