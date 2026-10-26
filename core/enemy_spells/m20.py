"""招式 20 把愛情送給妳 = FUN_004e7c77, 招式 107 把愛情給妳 = FUN_004dd509 (同结构, 只差施法 seq 表).

dispatcher: 0 渐暗 → 10 施法者挂 seq (20: 66f264 atlas 52 / 107: 65e174 atlas 103; 第 2 帧 12t 后 -100)
  -100: 每个目标 FUN_004e7a7d 生 1 颗爱心, 0x78++ → 0x1e.
  -200 (源 = 目标): 受击 6557f0[6418dc[施法者朝向]] + 刺爆 655c10[施法者朝向] + et00 星爆 655b18; 0x78--.
  -210: 飘字 (结算), 0x7a++.  0x1e: 0x78 == 0 且 0x7a == 0 → 0x28 渐亮 → 自毁.
爱心 (seq 66f274 = atlas 294 帧 68 (1t), 69 (39t) 循环), 生在施法者 (x, y, z+48), 目标 = 目标 (x, y, z+48):
  出生 (FUN_004e7a7d): 加速度 a = (rand%1024)·32 + 0x8000 (两轴各掷), v = 8a; 背离目标 (v 反向, a 朝目标); state 10.
  think FUN_004e76d8:
    10:  p += v; v += a; 任一轴 v == 0 (8 t 后) → v = -a, 定时 8 t → 0xf.
    0xf: p += v, 到时 → 0.
    0:   播 0xcc; xy 距离 < 96 px → v = (t - p) / 4, a = 0 → 0x14;
         否则重掷 a, v = 8a 朝目标 (a 反向减速) → 10 (一跳约 36a + 8a ≈ 20..45 px).
    0x14: FUN_004cdbc2 匀速到达 → 播 0xcd, 发 -200 + -210 (源 = 目标), 自毁.
实录校准 (wine/captures/en20_t7_F4716.log): 爱心 +16 出生 / 寿命 90 t / 帧序列, 受击+星爆 +106, 飘字 +106 吻合;
  渐亮差 1 t 来自飘字位数 (原版 4 位, 我们 3 位), 非本模块.
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _cdbc2, _motion
from core.enemy_spells._ecommon import hit_unit, dist_xy


def _cast(atlas: int, n: int) -> list[list[tuple]]:
    """[帧0 3t, 帧1 12t, -100, 其余各 3t]."""
    out = []
    for d in range(4):
        b = d * n
        out.append([('fm', atlas, b, 3), ('fm', atlas, b + 1, 12), ('jump', -100)]
                   + [('fm', atlas, b + k, 3) for k in range(2, n)] + [('exit',)])
    return out


CAST_20 = _cast(52, 4)          # 66f264
CAST_107 = _cast(103, 5)        # 65e174
HEART_SEQ = [('fm', 294, 68, 1), ('fm', 294, 69, 39), ('loop',)]       # 66f274
SFX_HOP, SFX_ARRIVE = 0xcc, 0xcd
Z_HEART = 48


def _ctrunc4(v: int) -> int:
    return -((-v) >> 2) if v < 0 else v >> 2


def _rand_a(b) -> int:
    return ((_rand(b) % 1024) << 16 >> 11) + 0x8000


def _heart_think(e, eng) -> None:
    """FUN_004e76d8."""
    ud = e.user_data
    if 'heart' not in ud:
        return
    sp: LoveHeart = ud['spell']
    b = sp.battle
    ud['age'] += 1
    st = ud['st']
    if st != 0x14 and ud['age'] > 600:                 # 保险 (exe 无): 异常久不到 → 直接进最后冲刺
        st = 0
        e.x, e.y = ud['tx'] - FP, ud['ty'] - FP
    if st == 0:
        _sfx(b, SFX_HOP)
        if dist_xy(e, ud['tx'], ud['ty']) < 0x600000:
            ud['vx'] = _ctrunc4(ud['tx'] - e.x)
            ud['vy'] = _ctrunc4(ud['ty'] - e.y)
            ud['ax'] = ud['ay'] = 0
            ud['st'] = 0x14
        else:
            ud['ax'], ud['ay'] = _rand_a(b), _rand_a(b)
            ud['vx'], ud['vy'] = ud['ax'] << 3, ud['ay'] << 3
            if _rand(b) & 1:
                ud['tx'] += 1
            if _rand(b) & 1:
                ud['ty'] += 1
            if ud['tx'] - e.x <= 0:
                ud['vx'] = -ud['vx']
            else:
                ud['ax'] = -ud['ax']
            if ud['ty'] - e.y <= 0:
                ud['vy'] = -ud['vy']
            else:
                ud['ay'] = -ud['ay']
            ud['st'] = 10
    elif st == 10:
        e.x += ud['vx']
        e.y += ud['vy']
        ud['vx'] += ud['ax']
        ud['vy'] += ud['ay']
        if ud['vx'] == 0 or ud['vy'] == 0:
            ud['vx'], ud['vy'] = -ud['ax'], -ud['ay']
            ud['until'] = ud['age'] + 8
            ud['st'] = 0xf
    elif st == 0xf:
        e.x += ud['vx']
        e.y += ud['vy']
        if ud['age'] == ud['until']:
            ud['st'] = 0
    elif st == 0x14:
        if _cdbc2(e):
            _sfx(b, SFX_ARRIVE)
            sp.on_arrive(ud['victim'])
            eng.destroy(e)


class LoveHeart(Spell):
    CAST = CAST_20

    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.launched = False

    def cast_seq(self, d):
        return self.CAST[d]

    def on_cast_impact(self) -> None:
        self.launched = True
        b = self.battle
        x, y = _pos(self.caster)
        for v in self.targets:
            tx, ty = _pos(v)
            ax, ay = _rand_a(b), _rand_a(b)
            vx, vy = ax << 3, ay << 3
            if _rand(b) & 1:
                tx -= 1
            if _rand(b) & 1:
                ty -= 1
            if tx - x < 0:
                ax = -ax
            else:
                vx = -vx
            if ty - y < 0:
                ay = -ay
            else:
                vy = -vy
            fx(b, _heart_think, x, y, Z_HEART * FP, HEART_SEQ, heart=True, spell=self, victim=v, age=0, st=10,
               **_motion(m=0x31, vx=vx, vy=vy, ax=ax, ay=ay, tx=tx, ty=ty, tz=Z_HEART * FP))
            self.live += 1

    def on_arrive(self, v) -> None:
        """-200 + -210."""
        self.live -= 1
        hit_unit(self, v, face_caster=True, star=True)
        self.settle(v)

    def think(self) -> None:
        if self.launched and self.live == 0 and not self._finishing:
            self.finish()


class LoveHeart107(LoveHeart):
    CAST = CAST_107


MOVES = {20: LoveHeart, 107: LoveHeart107}
