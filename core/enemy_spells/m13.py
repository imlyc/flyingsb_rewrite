"""招式 13 使用米斯特毒藥 = custom dispatcher FUN_004e7150.

dispatcher: 0 渐暗 → 10 施法者挂 66e948[朝向] (同 12 里可得毒藥) → -100 → 0x1e 等计数 → 0x28 渐亮 → 自毁.
  -100: FUN_004e6fdc(光标格 = 施法者格 + DAT_007e3d08/0c) → 0x78++.
        24 团毒雾 (think FUN_004e6e13): 生在光标格中心 (x, y+96, z=128), 目标 = 3×3 格内随机点
        (tx = 左缘 + rand%192, ty = 上缘 + rand%144 + 96), 速度 ±16 / ±12 px/t 朝目标 (mode 0x31, FUN_004cdbc2 钳);
        出生 (state -1) 挂 seq 66e9e0 (atlas 298 帧 1-6 不等时长循环) 并随机起始于第 rand%12 条指令.
        到达 → 目标 ±(rand%4-2, rand%2-1) px, v = 0, a = (0x3333, 0x1999) 弹簧抖动 (FUN_004c3211); age > 80 自毁.
        + 控制实体 FUN_004e6f6d (age%30 == 0 → -250; age > 80 → 停 0xc2, -200, 自毁) + 播 0xc2.
  -250: 所有目标 受击 6557f0[目标自身朝向] + 刺爆 655c10[施法者朝向] (共 3 次: age 0 / 30 / 60).
  -200: 所有目标飘字 (结算), 0x78--.
实录校准 (wine/captures/en13_t5_F4214.log): 毒雾出生/寿命 82 t、-250 @+21/+51/+81、-200 @+102、渐亮 @+139 逐 tick 吻合.
近似: 毒雾 seq 随机起点用 "从第 k 帧开始的展开 seq" 表示 (exe 循环回 seq 开头; 寿命内差别只在首轮之后的相位).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _rand, _sfx, _c3211, _cdbc2, _motion
from core.enemy_spells._ecommon import hit_unit, stop_sfx
from core.enemy_spells.m12 import CAST
from core.sprites.base import TILE_W, TILE_H

CLOUD = [('fm', 298, f, t) for f, t in ((2, 4), (3, 5), (4, 5), (1, 4), (6, 7), (3, 4), (2, 6), (4, 4), (1, 7), (3, 4),
                                        (2, 5), (4, 4), (5, 6))]                         # 66e9e0
N_CLOUD = 24
LIFE = 0x50
SFX_MIST = 0xc2


def _cloud_seq(k: int) -> list[tuple]:
    return CLOUD[k:] + CLOUD * 3 + [('loop',)]


def _cloud_think(e, eng) -> None:
    """FUN_004e6e13."""
    ud = e.user_data
    if 'mist' not in ud:
        return
    b = ud['spell'].battle
    age = ud['age']                 # exe +0x144 (本 tick 判定用旧值; 实录 en13_t5: 寿命 82 tick)
    ud['age'] += 1
    if ud['st'] == 0:
        if _cdbc2(e):
            ud['m'] = 0x31
            e.x = ud['tx'] + ((_rand(b) % 4 - 2) << 16)
            e.y = ud['ty'] + ((_rand(b) % 2 - 1) << 16)
            ud['vx'] = ud['vy'] = 0
            ud['ax'], ud['ay'] = 0x3333, 0x1999
            ud['st'] = 10
    else:
        _c3211(e)
        if age > LIFE:
            eng.destroy(e)


class MistPoison(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.ctrl = None            # 控制实体 age (FUN_004e6f6d); None = 未开始 / 已结束

    def cast_seq(self, d):
        return CAST[d]

    def on_cast_impact(self) -> None:
        """FUN_004e6fdc."""
        b, c = self.battle, self.caster
        cur = c.pending_attack_cursor or ((self.targets[0].x, self.targets[0].y) if self.targets else (c.x, c.y))
        px, py = cur
        left, right = (px - 1) * TILE_W, (px + 1) * TILE_W + TILE_W
        top, bottom = (py - 1) * TILE_H, (py + 1) * TILE_H + TILE_H
        x0 = (left + (right - left) // 2) * FP
        y0 = (top + (bottom - top) // 2) * FP + 96 * FP
        for _ in range(N_CLOUD):
            k = _rand(b) % 12
            tx = (_rand(b) % (right - left) + left) * FP
            ty = (_rand(b) % (bottom - top) + top) * FP + 96 * FP
            vx = -16 * FP if tx <= x0 else 16 * FP
            vy = -12 * FP if ty <= y0 else 12 * FP
            fx(b, _cloud_think, x0, y0, 128 * FP, _cloud_seq(k), mist=True, spell=self, age=0, st=0,
               **_motion(m=0x31, vx=vx, vy=vy, tx=tx, ty=ty, tz=128 * FP))
        _sfx(b, SFX_MIST)
        self.ctrl = 0

    def think(self) -> None:
        if self.ctrl is None:
            return
        age = self.ctrl
        self.ctrl += 1
        if age % 30 == 0:                   # -250
            for v in self.targets:
                hit_unit(self, v)
        if age > LIFE:                      # -200
            stop_sfx(self.battle, SFX_MIST)
            for v in self.targets:
                self.settle(v)
            self.ctrl = None
            self.finish()


MOVES = {13: MistPoison}
