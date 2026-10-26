"""122 用熱氣攻擊 (電熨斗): dispatcher FUN_004de3da (custom), reverse_engineering/enemy_spells_decomp.txt, 2026-10-26.

dispatcher:
  case 0  渐暗 → 10 挂施法 seq 65f9c0[朝向] (图 113 2 帧, -100) → 0x1e.
  -100    每个目标 FUN_004de2d9(目标, 施法者): 喷口实体在施法者 (x, y, z+20) + 朝向偏移 (上 y-8 / 下 y+12 / 左 x-20 / 右 x+20),
          seq 65fa30[朝向] (图 323 2 帧循环), +0x160 = 目标.
  喷口 think FUN_004de226 (age = +0x144): age%2==0 → FUN_004de062 喷一团热气; age%20==0 → 以目标为源发 -250;
          age%5==0 → 播 0xed; age==80 → -200, 自毁.  (→ 每个目标 4 次受击 + 1 次飘字)
  热气 FUN_004de062(喷口): 生在喷口 (z+4), mode 0x71 匀速 (FUN_004c3211, 加速度 0), vz = +(1 + rand%1000/1000) px/t,
          朝向: 上 y-32 起, vy = -(2 + r) / 下 y+32, vy = 2 + r, vz = 0 / 左 x-40, vx = -(3 + r) / 右 x+40, vx = 3 + r
          (r = rand%1000/1000 px, 先掷 vz 再掷水平); seq 65fa40 (图 323 6 帧各 1t) 播完自毁 (think FUN_004de022).
  -250    目标 FUN_004c4f20 + 受击 6557f0 + 655c10[反(目标朝向)] 刺爆 + 655b18 星爆 (无抖动) + 0xbd.
  -200    该目标飘字.
  0x1e    计数归零 + 受击播完 → 0x28 渐亮 → 自毁.
实录校准 (wine/captures/en122_t83_F5730.log): 喷口出生当 tick 不 think, 下一 tick age 0 (第 1 团热气 + 首次 -250, 共 5 次受击
  +1/+21/+41/+61/+81); 热气出生当 tick 已积分一步 (z 25, 喷口前 35px); 热气寿命 12 t、受击特效位置、飘字出生均逐 tick 吻合.
  收尾残差 2 t = 飘字位数 (原版 4 位, 我们 3 位).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _c3211, _motion, _dir, _unit_z
from core.enemy_spells.m203 import impact_fx, reset_hit, OPP

CAST_122 = [  # @0x65f9c0
    [('fm', 113, 0, 5), ('fm', 113, 1, 3), ('jump', -100), ('exit',)],
    [('fm', 113, 8, 5), ('fm', 113, 9, 3), ('jump', -100), ('exit',)],
    [('fm', 113, 16, 5), ('fm', 113, 17, 3), ('jump', -100), ('exit',)],
    [('fm', 113, 24, 5), ('fm', 113, 25, 3), ('jump', -100), ('exit',)],
]
NOZZLE = [  # @0x65fa30
    [('fm', 323, 0, 1), ('fm', 323, 1, 1), ('loop',)],
    [('fm', 323, 5, 1), ('fm', 323, 6, 1), ('loop',)],
    [('fm', 323, 10, 1), ('fm', 323, 11, 1), ('loop',)],
    [('fm', 323, 15, 1), ('fm', 323, 16, 1), ('loop',)],
]
PUFF = [('fm', 323, 2, 1), ('fm', 323, 8, 1), ('fm', 323, 12, 1), ('fm', 323, 3, 1), ('fm', 323, 4, 1), ('fm', 323, 14, 1), ('exit',)]  # @0x65fa40
NOZZLE_OFF = ((0, -8), (0, 12), (-20, 0), (20, 0))
SFX_HISS, SFX_HIT = 0xed, 0xbd


def _c_div(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def _frac(battle) -> int:
    """(rand%1000 << 16) / 1000: 0..1 px (16.16)."""
    return _c_div((_rand(battle) % 1000) << 16, 1000)


def _puff_think(e, eng) -> None:
    """FUN_004de022: 积分, seq 完自毁."""
    if 'puff' not in e.user_data:
        return
    _c3211(e)
    if not e.is_playing():
        eng.destroy(e)


def _puff(battle, nozzle, d: int) -> None:
    """FUN_004de062."""
    x, y, z = nozzle.x, nozzle.y, nozzle.user_data['ez'] + 4 * FP
    vx = vy = 0
    vz = _frac(battle) + 0x10000
    if d == 0:
        vy = -0x20000 - _frac(battle)
        y -= 32 * FP
    elif d == 1:
        vy = _frac(battle) + 0x20000
        y += 32 * FP
        vz = 0
    elif d == 2:
        vx = -0x30000 - _frac(battle)
        x -= 40 * FP
    else:
        vx = _frac(battle) + 0x30000
        x += 40 * FP
    e = fx(battle, _puff_think, x, y, z, PUFF, puff=True, **_motion(m=0x71, vx=vx, vy=vy, vz=vz))
    _c3211(e)                     # 实录 en122_t83: 热气出生当 tick 已积分一步 (z 25 / y 喷口-35)


def _nozzle_think(e, eng) -> None:
    """FUN_004de226."""
    ud = e.user_data
    if 'nozzle' not in ud:
        return
    sp: HotAir = ud['spell']
    age = ud['age']
    if age % 2 == 0:
        _puff(sp.battle, e, ud['d'])
    if age % 20 == 0:
        sp.on_hit(ud['victim'])
    if age % 5 == 0:
        _sfx(sp.battle, SFX_HISS)
    if age == 80:
        sp.on_settle(ud['victim'])
        eng.destroy(e)
        return
    ud['age'] = age + 1


class HotAir(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.fired = False

    def cast_seq(self, d: int):
        return CAST_122[d]

    def on_cast_impact(self) -> None:
        if self.fired:
            return
        self.fired = True
        c = self.caster
        d = _dir(c)
        x, y = _pos(c)
        ox, oy = NOZZLE_OFF[d]
        for v in self.targets:
            fx(self.battle, _nozzle_think, x + ox * FP, y + oy * FP, _unit_z(c) + 20 * FP, NOZZLE[d],
               nozzle=True, spell=self, victim=v, d=d, age=0)
            self.live += 1
        if not self.targets:
            self.finish()

    def on_hit(self, v) -> None:
        """-250."""
        reset_hit(v)
        impact_fx(self.battle, v, OPP[_dir(v)], jitter=False)
        _sfx(self.battle, SFX_HIT)

    def on_settle(self, v) -> None:
        """-200."""
        self.live -= 1
        self.settle(v)
        if self.live <= 0:
            self.finish()


MOVES = {122: HotAir}
