"""模板 FUN_004d72b1 (5 招: 21 使用波里渣德, 43 使用伏里加得, 116 以拳頭打擊, 135 使用波里姿, 233 使用部利加得),
reverse_engineering/enemy_spells_decomp.txt (+ 4d6f1e 补反编译, 4d7058/4d6dc3 见 icedragon_decomp.txt).
= 玩家 紫河 冰河醉雨 (core.jah_skills 0x3c) / 孙悟空 青龙 冰锥雨 (core.son_transform, 已实录校准, 小冰锥/碎冰直接复用).

dispatcher: 渐暗 → 施法 seq → -100: 每目标一个控制体 FUN_004d728e (think FUN_004d71ce), +0x78 计数.
  控制体: age<100 且偶数 → 小冰锥 FUN_004d6f6a (目标 x-12+(rand&63)-32, y+rand%30-6, z128; eice 帧 rand&3; flags 0x51
          x +4 px/t, z -24 px/t 匀速; 0xad); 落地 (z<1) → FUN_004d6dc3 4 片碎冰.
          age<100 且 %20==0 → -250.  age==0x80 → 大冰锥 FUN_004d70fc, 控制体自毁.
  大冰锥: 目标 (x, y+1, z500), vz -48 px/t, eice 帧 656bb8[rand%3] = 28/31/34, 0xae; think FUN_004d7058: 落地 →
          6×FUN_004d6dc3 (24 片碎冰) → -200 → -250 → 自毁.
  -250: 受击 6557f0[目标朝向] + 655c10[6418dc[目标朝向]] 刺爆 + 655b18 红刺 (= Spell.hit fx='both'), 无音.
  -200: 飘字, +0x78--.  0x1e: 计数归零 + 飘字/受击完 → 0x28 渐亮.
实录校准 (wine/captures/en21_t7_F4854.log): dispatcher 各 state 时长 (0x1e 177 t → 渐亮 @+193)、控制体 (+16, 129 t)、
  小冰锥 (+17 起每 2 t, 寿命 5)、刺爆 (+17/37/57/77/97 + 落地)、大冰锥 (+145, 寿命 11)、飘字出生 (+156) 吻合.
  碎冰: exe FUN_004d6d46 age 10 → state 10, 之后每 tick XOR 可见 (age 11 起闪), 记到 age 17, 下一 think 自毁. 实录 3/4 碎冰
  出生在低槽 (出生当 tick 不 think, 寿命 18), 1/4 高槽 (寿命 17) — 池序效应; 我们出生不 think → 按多数 (18) 自写碎冰,
  不用 son_transform 的 17 tick 版. 残差: 池序导致的个别冰锥/碎冰/飘字 ±1 tick.
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _c3211, _motion, _getz

EICE = 300
BIG_FRAMES = (28, 31, 34)        # DAT_00656bb8
SFX_BIG = 0xae
RAIN_TICKS, RAIN_STEP, REACT_STEP, BIG_AT = 100, 2, 20, 0x80


def _shatter_think(e, eng) -> None:
    """FUN_004d6d46 碎冰: 匀速直线; age 10 → state 10, age>10 每 tick XOR 可见; age 17 之后的 think 自毁."""
    ud = e.user_data
    if 'shatter' not in ud:
        return
    e.x += e.vx
    e.y += e.vy
    e.z += e.vz
    ud['tick'] += 1
    if ud['tick'] >= 10:
        e.state_code = 10
    if ud['tick'] > 10:
        e.flags ^= 0x40
    if ud['tick'] > 17:
        eng.destroy(e)


def _spawn_shatter(battle, x, y, n: int) -> None:
    """FUN_004d6dc3 × (n/4): 同 son_transform._spawn_ice_shatter (速度分布), think 换成 _shatter_think."""
    from core.son_transform import EICE_SHATTER
    rng = battle.rng
    for _ in range(n):
        e = battle.engine.spawn(think_fn=_shatter_think)
        e.atlas_slot = EICE
        e.frame_idx = EICE_SHATTER[rng.randint(0, len(EICE_SHATTER) - 1)]
        e.flags |= 0x40
        e.x, e.y, e.z = x, y, 0
        e.vx = (rng.randint(0, 2999) << 16) // 500 - (3 << 16)
        e.vy = (rng.randint(0, 1999) << 16) // 500 - (2 << 16)
        e.vz = -((rng.randint(0, 2999) << 16) // 1000)
        e.user_data.update(kind='hit_effect', projectile=True, shatter=True, tick=0)


def _cone_think(e, eng) -> None:
    """FUN_004d6f1e 小冰锥: x +4 / z -24 px/t 匀速, 落地 → 4 片碎冰, 自毁."""
    from core.son_transform import ICE_SHARD_VZ, ICE_SHARD_VX
    ud = e.user_data
    if 'cone' not in ud:
        return
    e.z += ICE_SHARD_VZ << 16
    e.x += ICE_SHARD_VX << 16
    if e.z >= 0:
        e.z = 0
        _spawn_shatter(ud['battle'], e.x, e.y, 4)
        eng.destroy(e)


def _spawn_cone(battle, x, y, frame) -> None:
    """FUN_004d6f6a (= son_transform._spawn_ice_cone 小锥, 落地碎冰换成本模块的)."""
    from core.son_transform import ICE_SHARD_HEIGHT, SFX_QL_ICE_SMALL, _sfx as _sfx_solo
    _sfx_solo(battle, SFX_QL_ICE_SMALL, solo=True)
    e = battle.engine.spawn(think_fn=_cone_think)
    e.atlas_slot = EICE
    e.frame_idx = frame
    e.flags |= 0x40
    e.x, e.y, e.z = x, y, -(ICE_SHARD_HEIGHT << 16)
    e.user_data.update(kind='hit_effect', projectile=True, cone=True, battle=battle)
    _cone_think(e, battle.engine)          # 出生当 tick 先走一步 (实录首帧 z=104)


def _big_cone_think(e, eng) -> None:
    """FUN_004d7058."""
    ud = e.user_data
    if 'big_cone' not in ud:
        return
    _c3211(e)
    if _getz(e) < 1:
        _spawn_shatter(ud['spell'].battle, e.x, e.y, 24)
        ud['spell'].on_big_land(ud['victim'])
        eng.destroy(e)


def _ctrl_think(e, eng) -> None:
    """FUN_004d71ce."""
    ud = e.user_data
    if 'rain' not in ud:
        return
    sp: IceRain = ud['spell']
    b, v = sp.battle, ud['victim']
    age = ud['age']
    if age < RAIN_TICKS and age % RAIN_STEP == 0:
        vx, vy = _pos(v)
        x = vx - 12 * FP + ((_rand(b) & 63) - 32) * FP
        y = vy + (_rand(b) % 30 - 6) * FP
        _spawn_cone(b, x, y, _rand(b) & 3)
    if age < RAIN_TICKS and age % REACT_STEP == 0:
        sp.hit(v, fx='both')
    if age == BIG_AT:
        vx, vy = _pos(v)
        fx(b, _big_cone_think, vx, vy + 1, 500 * FP, atlas=EICE, frame=BIG_FRAMES[_rand(b) % 3], big_cone=True,
           spell=sp, victim=v, **_motion(m=0x41, vz=-48 * FP))
        _sfx(b, SFX_BIG)
        eng.destroy(e)
        return
    ud['age'] += 1


class IceRain(Spell):
    def on_cast_impact(self) -> None:
        for v in self.targets:
            e = self.battle.engine.spawn(think_fn=_ctrl_think)
            e.flags = 0x800 | 0x10000
            e.user_data.update(kind='enemy_ice_rain', projectile=True, rain=True, spell=self, victim=v, age=0)
            self.live += 1
        if not self.targets:
            self.finish()

    def on_big_land(self, v) -> None:
        self.live -= 1
        self.settle(v)                  # -200
        self.hit(v, fx='both')          # -250
        if self.live <= 0:
            self.finish()


TEMPLATES = {0x4d72b1: IceRain}
