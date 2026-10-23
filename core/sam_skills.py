"""三藏法师 B 类技能的投射物/协调实体 (2026-10-22 原版实录 sz_15_F43182 + reverse_engineering/lifefire_decomp.txt).

0x15 生命之火 dispatcher FUN_004fe111:
  case 10 挂 cast seq 0x672bb8[dir] (csam_g0 帧 0..5); -100 → FUN_004fdfbf(光标格, 施法者): 光球 slot 0x10c=268 帧=朝向,
  生在施法者 (x, y, z+48), flags 0x31 = 匀速 (上 vy-12 / 下 +12 / 左 vx-16 / 右 +16 px/t) 飞到光标格中心 (FUN_004cdbc2 越过即钳),
  播 0x12b; 到达 → -200 + -250 自毁.
  -200: FUN_004d0d7b 火爆 (esum1 slot 299 seq 0x672bc8 帧 0..7 各 1t = 16 帧) 在 (光标格 x + rand%12-6, 光标格 y + 124,
  z = 172 + rand&15 - 8) → 画在光标格上方 48px; 播完发 -210.
  -250: 每个目标 (面前 1×3 列里的队友) 受击 seq + 方向 starburst 655c10.
  -210: 每个目标 回血白字 (FUN_004d074e) + 播 0x12d. 0x1e 等光球/火爆/飘字都完 → 渐亮 → 待机 (实录 +133).
实现: 光球 think → 火爆 → 协调实体 (jah_skills._spawn_coord/_coord_finish: SIG_IMPACT_2 → combat._apply_heal 飘字 → 等飘字落定 → SIG_END).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.sprites.base import TILE_W, TILE_H
from core.anim_engine.bytecode import tuple_to_bytecode

if TYPE_CHECKING:
    from core.anim_engine.engine import Engine
    from core.anim_engine.entity import Entity

FP = 1 << 16
LIFE_FIRE_ORB_ATLAS = 268
LIFE_FIRE_BURST_ATLAS = 299
LIFE_FIRE_ORB_Z = 48
LIFE_FIRE_ORB_SPEED = {0: (0, -12), 1: (0, 12), 2: (-16, 0), 3: (16, 0)}     # 朝向下标 (上/下/左/右) → (vx, vy) px/t
LIFE_FIRE_BURST_Y_OFF = 124
LIFE_FIRE_BURST_Z = 172
LIFE_FIRE_BURST_SEQ = [('fm', LIFE_FIRE_BURST_ATLAS, f, 1) for f in range(8)] + [('exit',)]   # @0x672bc8
SFX_LIFE_FIRE_ORB = 0x12b


def _sfx(battle, sid: int) -> None:
    battle.engine._emit('sound_play', None, sid)


def _burst_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'burst' not in ud:
        return
    if not e.is_playing():
        ud['coord'].user_data['pending'] = 0        # -210: 结算 (回血飘字 + 0x12d)
        eng.destroy(e)


def _orb_think(e: "Entity", eng: "Engine") -> None:
    ud = e.user_data
    if 'orb' not in ud:
        return
    battle, caster = ud['battle'], ud['caster']
    tx, ty = ud['target']
    e.x += ud['vx'] << 16
    e.y += ud['vy'] << 16
    arrived = ((ud['vx'] > 0 and e.x >= tx) or (ud['vx'] < 0 and e.x <= tx) or
               (ud['vy'] > 0 and e.y >= ty) or (ud['vy'] < 0 and e.y <= ty) or (ud['vx'] == 0 and ud['vy'] == 0))
    if not arrived:
        return
    e.x, e.y = tx, ty
    rng = battle.rng
    b = battle.engine.spawn(think_fn=_burst_think)
    b.atlas_slot, b.frame_idx = LIFE_FIRE_BURST_ATLAS, 0
    b.flags |= 0x40
    b.x = tx + ((rng.randint(0, 11) - 6) << 16)
    b.y = ty + (LIFE_FIRE_BURST_Y_OFF << 16)
    b.z = -((LIFE_FIRE_BURST_Z + rng.randint(0, 15) - 8) << 16)
    b.user_data.update(kind='hit_effect', projectile=True, burst=True, battle=battle, coord=ud['coord'])
    battle.engine.attach_seq(b, tuple_to_bytecode(LIFE_FIRE_BURST_SEQ))
    from core.jah_skills import _hit
    for v in ud['victims']:                          # -250: 受击 seq + 方向 starburst
        if v.alive:
            _hit(battle, caster, v, fx='dir')
    eng.destroy(e)


def _heal_targets(battle, caster) -> list:
    out = []
    tiles = getattr(battle, '_pending_damage_range', None)
    if tiles:
        for (x, y) in tiles:
            t = battle.q.occupant(x, y)
            if t is not None and t.alive and t.is_player == caster.is_player:
                out.append(t)
    else:
        t = caster.pending_attack_target
        if t is not None and t.alive:
            out.append(t)
    return out


def spawn_life_fire(battle, attacker, target_tile) -> "Entity":
    from core.jah_skills import _spawn_coord, _pillar_coord_think
    from core.attack_seq import facing_to_atk_index
    victims = _heal_targets(battle, attacker)
    coord = _spawn_coord(battle, attacker, victims, _pillar_coord_think)
    coord.user_data['pending'] = 1
    d = facing_to_atk_index(attacker.facing)
    vx, vy = LIFE_FIRE_ORB_SPEED[d]
    tx, ty = target_tile
    e = battle.engine.spawn(think_fn=_orb_think)
    e.atlas_slot, e.frame_idx = LIFE_FIRE_ORB_ATLAS, d
    e.flags |= 0x40
    ent = attacker.entity                            # 生在施法者**当前**位置 (cast seq 的 move 已把他推前 10px)
    e.x = ((attacker.x * TILE_W + TILE_W // 2) << 16) + (ent.x if ent is not None else 0)
    e.y = ((attacker.y * TILE_H + TILE_H // 2) << 16) + (ent.y if ent is not None else 0)
    e.z = -(LIFE_FIRE_ORB_Z << 16)
    e.user_data.update(kind='hit_effect', projectile=True, orb=True, battle=battle, caster=attacker, coord=coord,
                       victims=victims, vx=vx, vy=vy,
                       target=((tx * TILE_W + TILE_W // 2) << 16, (ty * TILE_H + TILE_H // 2) << 16))
    _sfx(battle, SFX_LIFE_FIRE_ORB)                  # 实录: 出生 tick 不走 (首帧 = 施法者偏移后的位置), 8t 飞 2 格
    return coord
