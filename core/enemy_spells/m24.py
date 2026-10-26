"""招式 24 使用超級阿巴藍 = custom dispatcher FUN_004e913d.

dispatcher: 0 渐暗 → 10 施法者挂 66f264[朝向] (同 20 爱心的施法 seq, atlas 52) → -100 → 0x1e.
  0x1e: dispatcher age%4 != 0 的每 t: 每个目标 FUN_004e9043 生 1 颗上升光点 + 播 0xfb; 计数 0x16c 每 t +1,
        计数 > 14 的那 t 生的光点打标记 (每目标 1 颗, 0x78++) 并转 0x28 (不再生).
  0x28: 0x78 / 0x7a / 受击 全清 → 0x32 渐亮 → 自毁.
  光点 (think FUN_004e8fe3): 生在施法者 (x - 16 + rand&31, y - 8 + rand&15, z=0), seq 66f330 (atlas 304 帧 16),
        z 匀速 +24 px/t; z > 500 → (有标记) 发 -150 (源 = 目标), 自毁.
  -150: FUN_004e8ea6(目标): 10 颗环绕光球 (seq 66f33c = atlas 304 帧 9) 在目标上空 z=640,
        相位 k·0x1999, 椭圆半径 32×24 (mode 0x32 绝对环绕目标); 末颗带标记, 目标=目标0 时播 0xfa.
     think FUN_004e89e9 (每 t 相位 += 0x800):
        0:    z -= 32 px/t 降到 128 → 弹簧 tz=128 vz=+2 az=0.25 → 10.
        10:   半径 = r>>16 (r 起 32.0 / 24.0, 每 t +1.0 / +0.75) 环绕 + z 弹簧; r ≥ 48 → 第 1 次 0x14, 第 2 次 0x1e.
        0x14: 半径每 t -1.0 / -0.75; r ≤ 24 → 10.
        0x1e: 半径收缩 + z -= 24 px/t; 落地 → FUN_004e888e 4 粒火花 (atlas 304 帧 12-14 随机, 匀速 vx ±3 / vy ±2 /
              vz 0..3 px, 8t 后闪烁, 16t 自毁); 有标记 → (目标0: 停 0xfa, 播 0xec) 发 -200 + -250 (源 = 目标); 自毁.
实录校准 (wine/captures/en24_t8_F4784.log): 上升光点出生当 tick 即 think (首帧 z=24, 寿命 20 t); 改后光点/光球 (+58)/
  落地火花与飘字 (+144)/渐亮 (+181, 同位数 seed) 逐 tick 吻合.
  -250: 受击 6557f0[目标自身朝向] + 刺爆 655c10[6418dc[目标朝向]] + et00 星爆.  -200: 飘字, 0x78--.
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, FP, _pos, _rand, _sfx, _dir, _c3211, _motion, _getz, _set_z
from core.enemy_spells._ecommon import hit_unit, static_fx, stop_sfx, OPP
from core.enemy_spells.m20 import CAST_20

ATLAS = 304
SFX_RISE, SFX_ORBIT, SFX_LAND = 0xfb, 0xfa, 0xec


def _rise_think(e, eng) -> None:
    """FUN_004e8fe3."""
    ud = e.user_data
    if 'rise' not in ud:
        return
    _c3211(e)
    if _getz(e) > 0x1f40000:
        if ud['marked']:
            ud['spell'].spawn_orbit(ud['victim'])
        eng.destroy(e)


def _phase(ud) -> None:
    ud['py'] = (ud['py'] + 0x800) & 0xffff
    ud['px'] = ud['py']


def _orbit_think(e, eng) -> None:
    """FUN_004e89e9."""
    ud = e.user_data
    if 'orbit' not in ud:
        return
    sp: SuperAbalan = ud['spell']
    st = ud['st']
    _phase(ud)
    if st == 0:
        ud['m'] = 0x32
        _set_z(e, _getz(e) - 0x200000)
        _c3211(e)
        if _getz(e) < 0x800001:
            _set_z(e, 0x800000)
            ud.update(tz=0x800000, vz=0x20000, az=0x4000)
            ud['st'] = 10
        return
    ud['rx'], ud['ry'] = ud['r'] >> 16, ud['r2'] >> 16
    if st == 10:
        ud['r'] += 0x10000
        ud['r2'] += 0xc000
    else:
        ud['r'] -= 0x10000
        ud['r2'] -= 0xc000
    ud['m'] = 0x32
    if st == 0x1e:
        _set_z(e, _getz(e) - 0x180000)
        _c3211(e)
        if _getz(e) < 1:
            _set_z(e, 0)
            _sparks(sp.battle, e)
            if ud['marked']:
                v = ud['victim']
                if sp.targets and v is sp.targets[0]:
                    stop_sfx(sp.battle, SFX_ORBIT)
                    _sfx(sp.battle, SFX_LAND)
                sp.on_land(v)
            eng.destroy(e)
        return
    _c3211(e)
    ud['m'] = 0x41
    _c3211(e)
    if st == 10 and ud['r'] > 0x2fffff:
        ud['st'] = 0x1e if ud['n'] == 1 else 0x14
        ud['n'] += 1
    elif st == 0x14 and ud['r'] < 0x180001:
        ud['st'] = 10


def _spark_think(e, eng) -> None:
    """FUN_004e8811."""
    ud = e.user_data
    if 'aspark' not in ud:
        return
    ud['age'] += 1
    _c3211(e)
    if ud['age'] > 8:
        e.flags ^= 0x40
    if ud['age'] > 0x10:
        eng.destroy(e)


def _sparks(b, src) -> None:
    """FUN_004e888e."""
    z = _getz(src)
    for _ in range(4):
        vx = ((_rand(b) % 3000) << 16) // 500 - 0x30000
        vy = ((_rand(b) % 2000) << 16) // 500 - 0x20000
        vz = ((_rand(b) % 3000) << 16) // 1000
        static_fx(b, _spark_think, src.x, src.y, z, ATLAS, _rand(b) % 3 + 12, aspark=True, age=0,
                  **_motion(m=0x71, vx=vx, vy=vy, vz=vz, tx=src.x, ty=src.y, tz=z))


class SuperAbalan(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.casting = False
        self.count = 0
        self.spawning = False

    def cast_seq(self, d):
        return CAST_20[d]

    def on_cast_impact(self) -> None:
        self.casting = self.spawning = True

    def think(self) -> None:
        if not self.casting:
            return
        if self.spawning:
            if self.age % 4:
                b = self.battle
                x, y = _pos(self.caster)
                for v in self.targets:
                    rx = (_rand(b) & 31) - 16
                    ry = (_rand(b) & 15) - 8
                    marked = self.count > 14
                    e = static_fx(b, _rise_think, x + rx * FP, y + ry * FP, 0, ATLAS, 16, rise=True, spell=self,
                                  victim=v, marked=marked, **_motion(m=0x41, vz=0x180000, tz=0))
                    _rise_think(e, b.engine)       # 实录 en24_t8: 出生当 tick 即 think (首帧 z=24, 寿命 20 t)
                    _sfx(b, SFX_RISE)
                    if marked:
                        self.live += 1
                        self.spawning = False
                self.count += 1
            return
        if self.live == 0 and not self._finishing:
            self.casting = False
            self.finish()

    def spawn_orbit(self, v) -> None:
        """-150: FUN_004e8ea6."""
        b = self.battle
        x, y = _pos(v)
        phase = 0
        for k in range(10):
            last = k == 9
            static_fx(b, _orbit_think, x, y, 640 * FP, ATLAS, 9, orbit=True, spell=self, victim=v, marked=last, st=0,
                      n=0, r=0x200000, r2=0x180000,
                      **_motion(m=0x32, tx=x, ty=y, rx=0x20, ry=0x18, px=phase, py=phase))
            phase += 0x1999
        if self.targets and v is self.targets[0]:
            _sfx(b, SFX_ORBIT)

    def on_land(self, v) -> None:
        """-200 + -250."""
        self.live -= 1
        self.settle(v)
        hit_unit(self, v, spark_dir=OPP[_dir(v)], star=True)


MOVES = {24: SuperAbalan}
