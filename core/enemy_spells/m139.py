"""139 用眼淚攻勢: dispatcher FUN_004e0763 (custom), reverse_engineering/enemy_spells_decomp.txt, 2026-10-26.

dispatcher 同 core.enemy_spells.m203.Shot (无渐暗; 施法 seq 661114[朝向] 帧 3×3t + -100; -200 = 受击 + 两特效抖动 + 飘字 + 0xbd;
0x14 计数归零自毁, 不渐亮), 只是 -100 的弹不同:
  -100 FUN_004e062b(第一个目标): 泪滴生在 **目标头顶** (x, y+1, z+196), seq 661124 (图 325 帧 0-5 各 5t 循环), 播 0xf9 (循环音).
       mode 0x51 (x, z 两轴 FUN_004c3211 弹簧, 目标 0x27100000 = 永远够不到): vx = ±(1 + rand%1000/2000) px/t
       (rand&1 偶 → 负), vz = -(4 + rand%2000/1000) px/t, az = 0x5999 (≈0.35 px/t² 向上减速).
  think FUN_004e0538: 积分; vz ≥ 0 (摆到底) → vx 反向重掷, vz 重掷 (像落叶左右飘); z ≤ 64 px → 停 0xf9, -200, 自毁.
"""
from __future__ import annotations

from core.enemy_spells.base import fx, FP, _pos, _rand, _sfx, _c3211, _motion, _getz, _unit_z
from core.enemy_spells.m203 import Shot

CAST_139 = [  # @0x661114
    [('fm', 125, 0, 3), ('fm', 125, 1, 3), ('fm', 125, 2, 3), ('jump', -100), ('exit',)],
    [('fm', 125, 3, 3), ('fm', 125, 4, 3), ('fm', 125, 5, 3), ('jump', -100), ('exit',)],
    [('fm', 125, 6, 3), ('fm', 125, 7, 3), ('fm', 125, 8, 3), ('jump', -100), ('exit',)],
    [('fm', 125, 9, 3), ('fm', 125, 10, 3), ('fm', 125, 11, 3), ('jump', -100), ('exit',)],
]
DROP = [('fm', 325, 0, 5), ('fm', 325, 1, 5), ('fm', 325, 2, 5), ('fm', 325, 3, 5), ('fm', 325, 4, 5), ('fm', 325, 5, 5), ('loop',)]  # @0x661124
SFX_TEAR = 0xf9
TEAR_Z, TEAR_END_Z = 196, 64


def _c_div(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def _swing_vx(battle) -> int:
    return _c_div((_rand(battle) % 1000) << 16, 2000) + 0x10000


def _swing_vz(battle) -> int:
    return -(_c_div((_rand(battle) % 2000) << 16, 1000) + 0x40000)


def _tear_think(e, eng) -> None:
    """FUN_004e0538."""
    ud = e.user_data
    if 'tear' not in ud:
        return
    sp: Tear = ud['spell']
    b = sp.battle
    _c3211(e)
    if ud['vz'] > -1:
        if ud['vx'] < 1:
            ud['vx'] = _swing_vx(b)
        else:
            ud['vx'] = -_swing_vx(b)
        ud['vz'] = _swing_vz(b)
    if _getz(e) < TEAR_END_Z * FP + 1:
        b.engine._emit('sound_stop', None, SFX_TEAR)
        sp.on_arrive(ud['victim'])
        eng.destroy(e)


class Tear(Shot):
    CAST, SFX_HIT = CAST_139, 0xbd

    def spawn(self, v) -> None:
        """FUN_004e062b."""
        b = self.battle
        x, y = _pos(v)
        vx = _swing_vx(b) if (_rand(b) & 1) else -_swing_vx(b)
        # exe: 先掷 rand&1 再掷大小 (同一表达式里两次 rand); vz 后掷
        vz = _swing_vz(b)
        fx(b, _tear_think, x, y + FP, _unit_z(v) + TEAR_Z * FP, DROP, tear=True, spell=self, victim=v,
           **_motion(m=0x51, vx=vx, vz=vz, az=0x5999, tx=0x27100000, tz=0x27100000))
        self.live += 1
        _sfx(b, SFX_TEAR)


MOVES = {139: Tear}
