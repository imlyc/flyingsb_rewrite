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
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _c3211, _motion, _getz

EICE = 300
BIG_FRAMES = (28, 31, 34)        # DAT_00656bb8
SFX_BIG = 0xae
RAIN_TICKS, RAIN_STEP, REACT_STEP, BIG_AT = 100, 2, 20, 0x80


def _big_cone_think(e, eng) -> None:
    """FUN_004d7058."""
    ud = e.user_data
    if 'big_cone' not in ud:
        return
    _c3211(e)
    if _getz(e) < 1:
        from core.son_transform import _spawn_ice_shatter
        _spawn_ice_shatter(ud['spell'].battle, e.x, e.y, big=True)
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
        from core.son_transform import _spawn_ice_cone, ICE_SHARD_HEIGHT
        vx, vy = _pos(v)
        x = vx - 12 * FP + ((_rand(b) & 63) - 32) * FP
        y = vy + (_rand(b) % 30 - 6) * FP
        _spawn_ice_cone(b, x, y, ICE_SHARD_HEIGHT, _rand(b) & 3, big=False)
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
