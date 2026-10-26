"""招式 55 胡亂射擊 = FUN_004db759, 招式 102 使用老大神功 = FUN_004dd096 (同一 dispatcher 结构, 只差施法 seq 与子弹).

dispatcher (**无渐暗/渐亮**): 0 施法者挂 seq 表[朝向] (55: 6586cc atlas 76 / 102: 65d814 atlas 96), → 10;
  -100: 发 1 发子弹打目标0, 0x78++ → 0x14.
        55  FUN_004db63a: seq 658678 (atlas 237 帧 0-7 各 1t 循环) + 播 0xe2; 速度 上/下 ∓9 / 左/右 ∓12 px/t.
        102 FUN_004dcf54: 静态图 atlas 322 帧 = 施法者朝向; 速度 ∓24 / ∓32 px/t; dispatcher 播 0xde.
        子弹: 生在施法者 (x, y, z+48), 目标 (目标0 x, y, z+48), mode 0x31 FUN_004cdbc2 (越过即钳, 0 速轴首步钳);
        两轴都到 → -200 自毁 (think FUN_004db5ec / 004dcf06).
  -200: 目标受击 6557f0[目标自身朝向] + 刺爆 655c10[施法者朝向] 与 et00 星爆 655b18 (各自 x/y/z ±8 抖动)
        + 飘字 + 播 0xbd; 0x78--, 0x7a++.
  0x14: 0x78 == 0 且 飘字完 (0x7a == 0) → 自毁 (不等受击 seq; 我们框架 finish 仍会等受击播完, 差异可忽略).
实录校准 (wine/captures/en55_t21_F4702.log / en102_t65_F4226.log): 施法者帧、子弹出生 (+20 / +24) / 寿命 / 帧序列、
  受击+刺爆+星爆+飘字 (+28 / +30)、dispatcher 结束 (随飘字位数) 吻合, 无需改动.
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _sfx, _dir, _cdbc2, _motion
from core.enemy_spells._ecommon import hit_unit, static_fx


# 6586cc[dir] (atlas 76)
CAST_55 = [
    [('move', 0, -12, 0, 0), ('fm', 76, 0, 3), ('fm', 76, 1, 12), ('move', 0, -6, 0, 0), ('fm', 76, 2, 3),
     ('move', 0, -6, 0, 0), ('jump', -100), ('jump', -105), ('fm', 76, 3, 3), ('move', 0, -6, 0, 0), ('fm', 76, 4, 3),
     ('move', 0, 32, 0, 0), ('fm', 76, 0, 3), ('jump', -110), ('exit',)],
    [('move', 0, 12, 0, 0), ('fm', 76, 5, 3), ('fm', 76, 6, 12), ('move', 0, 6, 0, 0), ('fm', 76, 7, 3),
     ('move', 0, 6, 0, 0), ('jump', -100), ('jump', -105), ('fm', 76, 8, 3), ('move', 0, 6, 0, 0), ('fm', 76, 9, 3),
     ('move', 0, -32, 0, 0), ('fm', 76, 5, 3), ('jump', -110), ('exit',)],
    [('move', -16, 0, 0, 0), ('fm', 76, 10, 3), ('fm', 76, 11, 12), ('move', -8, 0, 0, 0), ('fm', 76, 12, 3),
     ('move', -8, 0, 0, 0), ('jump', -100), ('jump', -105), ('fm', 76, 13, 3), ('move', -8, 0, 0, 0), ('fm', 76, 14, 3),
     ('move', 40, 0, 0, 0), ('fm', 76, 10, 3), ('jump', -110), ('exit',)],
    [('move', 16, 0, 0, 0), ('fm', 76, 15, 3), ('fm', 76, 16, 12), ('move', 8, 0, 0, 0), ('fm', 76, 17, 3),
     ('move', 8, 0, 0, 0), ('jump', -100), ('jump', -105), ('fm', 76, 18, 3), ('move', 8, 0, 0, 0), ('fm', 76, 19, 3),
     ('move', -40, 0, 0, 0), ('fm', 76, 15, 3), ('jump', -110), ('exit',)],
]
# 65d814[dir] (atlas 96)
CAST_102 = [
    [('move', 0, 4, 0, 0), ('fm', 96, 0, 3), ('move', 0, 4, 0, 0), ('fm', 96, 1, 3), ('move', 0, 4, 0, 0),
     ('fm', 96, 2, 12), ('move', 0, -6, 0, 0), ('fm', 96, 3, 3), ('move', 0, -6, 0, 0), ('jump', -100),
     ('fm', 96, 4, 3), ('fm', 96, 5, 3), ('exit',)],
    [('move', 0, -4, 0, 0), ('fm', 96, 6, 3), ('move', 0, -4, 0, 0), ('fm', 96, 7, 3), ('move', 0, -4, 0, 0),
     ('fm', 96, 8, 12), ('move', 0, 6, 0, 0), ('fm', 96, 9, 3), ('move', 0, 6, 0, 0), ('jump', -100),
     ('fm', 96, 10, 3), ('fm', 96, 11, 3), ('exit',)],
    [('move', 6, 0, 0, 0), ('fm', 96, 12, 3), ('move', 6, 0, 0, 0), ('fm', 96, 13, 3), ('move', 6, 0, 0, 0),
     ('fm', 96, 14, 12), ('move', -10, 0, 0, 0), ('fm', 96, 15, 3), ('move', -8, 0, 0, 0), ('jump', -100),
     ('fm', 96, 16, 3), ('fm', 96, 17, 3), ('exit',)],
    [('move', -6, 0, 0, 0), ('fm', 96, 18, 3), ('move', -6, 0, 0, 0), ('fm', 96, 19, 3), ('move', -6, 0, 0, 0),
     ('fm', 96, 20, 12), ('move', 10, 0, 0, 0), ('fm', 96, 21, 3), ('move', 8, 0, 0, 0), ('jump', -100),
     ('fm', 96, 22, 3), ('fm', 96, 23, 3), ('exit',)],
]
BULLET_SEQ = [('fm', 237, f, 1) for f in range(8)] + [('loop',)]          # 658678
SFX_HIT = 0xbd
Z_PROJ = 48


def _bullet_think(e, eng) -> None:
    """FUN_004db5ec / 004dcf06."""
    ud = e.user_data
    if 'bullet' not in ud:
        return
    if _cdbc2(e):
        ud['spell'].on_arrive(ud['victim'])
        eng.destroy(e)


class Shot(Spell):
    DIM = False
    FADE_IN = False
    CAST = CAST_55
    VEL = ((0, -9), (0, 9), (-12, 0), (12, 0))

    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.launched = False

    def cast_seq(self, d):
        return self.CAST[d]

    def spawn_bullet(self, x, y, d, **ud):
        e = fx(self.battle, _bullet_think, x, y, Z_PROJ * FP, BULLET_SEQ, **ud)
        _sfx(self.battle, 0xe2)
        return e

    def on_cast_impact(self) -> None:
        self.launched = True
        if not self.targets:
            return
        c, v = self.caster, self.targets[0]
        x, y = _pos(c)
        tx, ty = _pos(v)
        d = _dir(c)
        vx, vy = self.VEL[d]
        self.spawn_bullet(x, y, d, bullet=True, spell=self, victim=v,
                          **_motion(m=0x31, vx=vx * FP, vy=vy * FP, tx=tx, ty=ty, tz=Z_PROJ * FP))
        self.live += 1

    def on_arrive(self, v) -> None:
        """-200."""
        self.live -= 1
        hit_unit(self, v, star=True, jitter=True)
        self.settle(v)
        _sfx(self.battle, SFX_HIT)

    def think(self) -> None:
        if self.launched and self.live == 0 and not self._finishing:
            self.finish()


class BossShot(Shot):
    CAST = CAST_102
    VEL = ((0, -24), (0, 24), (-32, 0), (32, 0))

    def spawn_bullet(self, x, y, d, **ud):
        _sfx(self.battle, 0xde)
        return static_fx(self.battle, _bullet_think, x, y, Z_PROJ * FP, 322, d, **ud)


MOVES = {55: Shot, 102: BossShot}
