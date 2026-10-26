"""招式 12 使用里可得毒藥 = custom dispatcher FUN_004e69cf (reverse_engineering/enemy_spells_decomp.txt).

dispatcher: 0 渐暗 → 10 施法者挂 66e948[朝向] (atlas 49, 4 帧, 第 3 帧 12t 中途 -100) → 0x1e 等计数 → 0x28 渐亮 → 自毁.
  -100: FUN_004e6874(目标0, 施法者) 毒瓶 1 发 + 播 0xa8:
        生在施法者 (x, y, z+48), 目标 = 目标0 (x, y, z+48), mode 0x31 (x/y 两轴, FUN_004cdbc2 匀速, 越过即钳);
        速度按施法者朝向 上 vy=-24 / 下 +24 / 左 vx=-32 / 右 +32 px/t (另一轴 v=0 → 首步直接钳到目标线);
        静态图 66e958[朝向] = atlas 297 帧 (11, 10, 9, 0); 出生先 FUN_004c3211 走 1 步. 两轴都到 → -200 自毁 (think FUN_004e6826).
  -200: 目标受击 6557f0[6418dc[施法者朝向]] (转向施法者) + ef010 刺爆 655c10[施法者朝向]
        + FUN_004d0d7b 毒雾 seq 66e978 (atlas 297 帧 1-3 + 298 帧 0-6 各 3t) 在 (目标 x + rand%12-6, y+124, z+172),
        播完发 -210.
  -210: 飘字 (FUN_004d05d8) — 结算.
实录校准 (wine/captures/en12_t5_F4558.log): 毒瓶 +20 出生 9 t / 刺爆+毒雾 +29 (40 t) / 飘字 +69 / 渐亮 +104 逐 tick 吻合, 无需改动.
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _dir, _c3211, _cdbc2, _motion
from core.enemy_spells._ecommon import hit_unit, static_fx

CAST = [[('fm', 49, b + 0, 3), ('move', *m1, 0, 0), ('fm', 49, b + 1, 3), ('move', *m1, 0, 0), ('fm', 49, b + 2, 12),
         ('move', *m2, 0, 0), ('jump', -100), ('fm', 49, b + 3, 3), ('exit',)]
        for b, m1, m2 in ((0, (0, 1), (0, -2)), (4, (0, -1), (0, 2)), (8, (1, 0), (-2, 0)), (12, (-1, 0), (2, 0)))]
VEL = ((0, -24), (0, 24), (-32, 0), (32, 0))
BOTTLE_ATLAS, BOTTLE_FRAMES = 297, (11, 10, 9, 0)
CLOUD_SEQ = ([('fm', 297, f, 3) for f in (1, 2, 3)] + [('fm', 298, f, 3) for f in range(7)] + [('exit',)])   # 66e978
SFX_THROW = 0xa8
Z_PROJ = 48


def _bottle_think(e, eng) -> None:
    """FUN_004e6826."""
    ud = e.user_data
    if 'bottle' not in ud:
        return
    if _cdbc2(e):
        ud['spell'].on_arrive(ud['victim'])
        eng.destroy(e)


def _cloud_think(e, eng) -> None:
    """FUN_004d0dcf: seq 播完发 +400 信号 (-210) 自毁."""
    ud = e.user_data
    if 'cloud' not in ud or e.is_playing():
        return
    ud['spell'].on_cloud_done(ud['victim'])
    eng.destroy(e)


class PoisonBottle(Spell):
    BOTTLE_VEL = VEL
    BOTTLE_ATLAS = BOTTLE_ATLAS
    BOTTLE_FRAMES = BOTTLE_FRAMES

    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.launched = False

    def cast_seq(self, d):
        return CAST[d]

    def on_cast_impact(self) -> None:
        self.launched = True
        if not self.targets:
            return
        b, c, v = self.battle, self.caster, self.targets[0]
        x, y = _pos(c)
        tx, ty = _pos(v)
        d = _dir(c)
        vx, vy = self.BOTTLE_VEL[d]
        e = static_fx(b, _bottle_think, x, y, Z_PROJ * FP, self.BOTTLE_ATLAS, self.BOTTLE_FRAMES[d], bottle=True,
                      spell=self, victim=v, **_motion(m=0x31, vx=vx * FP, vy=vy * FP, tx=tx, ty=ty, tz=Z_PROJ * FP))
        _c3211(e)
        _sfx(b, SFX_THROW)
        self.live += 1

    def on_arrive(self, v) -> None:
        """-200."""
        from core.pao_skills import hit_pos
        self.live -= 1
        hit_unit(self, v, face_caster=True)
        hx, hy = hit_pos(v)
        x = hx + ((_rand(self.battle) % 12 - 6) << 16)
        fx(self.battle, _cloud_think, x, hy + 124 * FP, 172 * FP, CLOUD_SEQ, cloud=True, spell=self, victim=v)
        self.live += 1

    def on_cloud_done(self, v) -> None:
        """-210."""
        self.live -= 1
        self.settle(v)

    def think(self) -> None:
        if self.launched and self.live == 0 and not self._finishing:
            self.finish()


MOVES = {12: PoisonBottle}
