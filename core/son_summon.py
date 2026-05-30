"""孙悟空召唤技能演出框架 (skill 0x00..0x09).

exe dispatcher (e.g. 大金刚 FUN_004f460a) 是多阶段召唤演出, 我们用 coordinator entity
驱动 caster 的翻跟头隐现 + 神兽 spawn + AOE 伤害 + 收尾.

演出流程 (对应 exe state 流):
  FLIP_OUT: caster 翻跟头 (ps_CSON105 0..7) + emong 烟雾 → 翻完 caster 隐身
  SUMMON:   神兽攻击阶段 (L1 占位: 直接 AOE 伤害; 后续接 eson01 从天而降逐敌)
  FLIP_IN:  caster 现身 + 翻跟头 (0..7) + emong → 翻完
  DONE:     post_attack_anim 收尾 + 销毁 coordinator

caster 召唤期间不走标准 attack seq (caster.entity 不 attach skill seq), 全由 coordinator
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

# 哪些 skill 走孙悟空召唤演出. L1 先做大金刚, 逐个加.
SON_SUMMON_SKILLS: set[int] = {0x00}

# coordinator 状态码 (避开 20 = PROJ_STATE_DONE, units_animating 用它判投射物结束)
_FLIP_OUT = 100
_SUMMON = 110
_FLIP_IN = 120
_DONE = 130

FLIP_HOLD_TICKS = 3        # 翻跟头每帧 hold (8 帧 × 3 = 24 tick ≈ 720ms)
SUMMON_TICKS = 40          # 神兽攻击阶段时长 (占位, 后续 eson01 下落逐敌取代)
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


def son_summon_think(e: "Entity", eng: "Engine") -> None:
    """孙悟空召唤 coordinator. 驱动翻跟头隐现 + 神兽 + 伤害 + 收尾."""
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
                e.state_code = _SUMMON
                e.user_data['phase_ticks'] = 0
                _do_summon_damage(e, battle, caster)
            else:
                caster.cast_flip_frame = idx
    elif e.state_code == _SUMMON:
        # L1 占位: 等 SUMMON_TICKS (神兽攻击演出时长). 后续接 eson01 下落逐敌.
        e.user_data['phase_ticks'] += 1
        if e.user_data['phase_ticks'] >= SUMMON_TICKS:
            # caster 现身, 开始翻跟头出现
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


def _do_summon_damage(e: "Entity", battle, caster) -> None:
    """神兽攻击阶段结算伤害 (L1: 直接 AOE; 后续 eson01 逐敌时移到每次落地)."""
    from core.battle import combat
    caster.pending_impact_count = 0   # total=1 → 首即末, 走 AOE 结算
    combat.apply_pending_attack(battle, caster)


def start_son_summon(battle, caster, target_tile, skill_id: int) -> "Entity":
    """启动孙悟空召唤 coordinator. caster 不走标准 attack seq, 全由 coord 控制.
    调用前 confirm_attack_aim 已设好 caster.pending_* + battle._pending_damage_range."""
    from core.sprites.base import TILE_W, TILE_H
    eng = battle.engine
    e = eng.spawn(think_fn=son_summon_think)
    e.flags = 0x800 | 0x10000           # alive + has-think-fn, 不渲染 (无 visible bit)
    e.x = (target_tile[0] * TILE_W + TILE_W // 2) << 16
    e.y = (target_tile[1] * TILE_H + TILE_H // 2) << 16
    e.z = 0
    e.user_data['kind'] = 'son_summon_coord'
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


def is_son_summon_skill(skill_id: int | None) -> bool:
    return skill_id is not None and skill_id in SON_SUMMON_SKILLS
