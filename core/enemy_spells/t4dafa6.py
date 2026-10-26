"""模板 FUN_004dafa6 (6 招: 8 吹出旋風 / 34 使出超級旋風 / 63 用大暴風攻擊 / 131 用快攻(hook) / 170 快速攻擊 / 201 吹出旋風),
reverse_engineering/enemy_spells_decomp.txt. 与孙悟空白虎 (core/son_transform.py 风锚) 共用子实体 FUN_004dae7c / 4da9ed / 4da929.

dispatcher: 渐暗 → 施法 seq (招式参数表[朝向]) → -100: 每目标一个风锚 FUN_004dae7c (+0x78 ++), 进 0x1e.
  0x1e: +0x78 == 0 且飘字计数 +0x7a == 0 → 0x28 渐亮 → 自毁 (不等受击 seq 标记).
  -200: 飘字 FUN_004d05d8(目标, 预算伤害), +0x7a ++, +0x78 --.
  -250: 目标复位 + 受击 seq 6557f0[目标朝向] + ef010 刺爆 655c10[**施法者**朝向] + et00 星爆 655b18.
风锚 FUN_004dae7c (think FUN_004da9ed, 不可见): 偏目标 (±(16+rand&7), ±(12+rand%6)), flags 0x31 弹簧 a=1px 朝目标格.
  age==8: 目标挂旋转 seq 656ef8 + z 弹簧 0x71 (目标 0, a=2 = 重力), vz0 = (rand&7)/4;
  age<120 且 z<100: vz += 2.1; 120≤age<140: vz += 4 (抛飞, 首目标 age==120 播 0xf4);
  age<120 且 age%4==0: 锚走一步 + 相位 +0x1000, 锚两侧各一个旋涡环 FUN_004da929 (ehari00); age%64==0 首目标播 0xdc;
  age>120 且目标 z<1: 播 0xf0, 目标落地回待机, 发 -200 再发 -250, 锚自毁.
131 用快攻 的处理函数 FUN_004df3d1 包一层: -100 时施法者改挂 6604b0[朝向] (cfan_g1 5 帧循环), -200 时施法者清 0x20000
  (seq 定格在当前帧).
近似: 风锚沿用 son_transform 的实现; 目标旋转/腾空用 BattleUnit.wind_lift / wind_spin_col 渲染.
实录校准 (wine/captures/en8_t4_F10892.log, 8 吹出旋風): 风锚出生 +16 / 每 4 tick 一对旋涡环 / 环位置 / 腾空 z 曲线 (vz0=0 时逐 tick
  相同, 落地 tick 只取决于 rand) / 落地当 tick 出 et00+ef010 + 飘字 spawner, 下一 tick 首位数字 均吻合.
  旋涡环帧序列改为按 exe 挂 seq (son_transform.whirlwind_ring_think 的帧序列与实录不符, 本模块用自己的 _ring_think).
  0x1e 不等受击 seq (busy 只看风锚 + 飘字). 残差: 渐亮起点 落地+37 (原版 +36, 飘字池序 ±1).
"""
from __future__ import annotations

from core.anim_engine.bytecode import tuple_to_bytecode
from core.enemy_spells.base import Spell, _pos, _rand, _sfx, _dir
from core.enemy_spells.b_common import react
from core.son_transform import (WIND_ATLAS, WIND_BANDS, WIND_TOP, BH_RING_RX, BH_RING_RY, SFX_BH_WIND, SFX_BH_FLING, SFX_BH_SLAM, BH_LIFT_START, BH_LIFT_END,
                                BH_FLING_END, BH_LIFT_HEIGHT, BH_LIFT_ACCEL, BH_FLING_ACCEL, BH_GRAVITY, BH_SPIN_COLS,
                                BH_SPIN_FRAME_TICKS, BH_ANCHOR_STEP)

CFAN_G1 = 119
QUICK_LOOP_SEQS = [[('fm', CFAN_G1, b + k, 1) for k in range(1, 6)] + [('loop',)] for b in (0, 6, 12, 18)]   # 6604b0


def _ring_think(e, eng) -> None:
    """旋涡环 FUN_004da929: 先按**移动前** z>>4 选帧组 seq PTR_DAT_00656ed8[段] (段变了才重挂), 再 FUN_004c3211 匀速上升,
    z>128 自毁. 帧组 seq = 3 帧 ticks=1 循环. 实录校准 (wine/captures/en8_t4_F10892.log): 挂上当 tick 显示首帧 1 tick,
    之后每帧 2 tick (18 19×2 20×2 18 | 15 16×2 17×2 | ...)."""
    ud = e.user_data
    if 'ring' not in ud:
        return
    band = min(7, max(0, (-(e.z >> 16)) >> 4))
    if min(band, 6) != ud['band']:                          # 段 6/7 是同一个 seq 指针, 不重挂
        ud['band'], ud['o'] = min(band, 6), 0
    e.frame_idx = WIND_BANDS[band][((ud['o'] + 1) // 2) % 3]
    ud['o'] += 1
    e.z -= ud['vz'] << 16
    if -(e.z >> 16) > WIND_TOP:
        eng.destroy(e)


def _spawn_wind_pair(battle, ax: int, ay: int, phase: int) -> None:
    """锚位两侧 (相位差半圈) 各一个旋涡环: (sin φ × 16, -cos φ × 12); vz 随机 3|4, 出生当 tick 即 think (同 son_transform)."""
    import math
    for ph in (phase, (phase + 0x8000) & 0xffff):
        a = ph / 0x10000 * 2 * math.pi
        e = battle.engine.spawn(think_fn=_ring_think)
        e.atlas_slot = WIND_ATLAS
        e.frame_idx = WIND_BANDS[0][0]
        e.flags |= 0x40
        e.x = ax + int(math.sin(a) * BH_RING_RX * 65536)
        e.y = ay - int(math.cos(a) * BH_RING_RY * 65536)
        e.z = 0
        e.user_data.update(kind='hit_effect', projectile=True, ring=True, band=-1, o=0,
                           vz=(battle.rng.randint(0, 1) + 3))
        _ring_think(e, battle.engine)


def _anchor_think(e, eng) -> None:
    """FUN_004da9ed."""
    ud = e.user_data
    if 'anchor' not in ud:
        return
    sp: Tornado = ud['spell']
    b, v = sp.battle, ud['victim']
    t = ud['t']
    if t == BH_LIFT_START and v.alive:
        ud['lifted'] = True
        ud['z'] = 0
        ud['vz'] = ((_rand(b) & 7) << 16) >> 2
        ud['spin'] = 0
    if ud.get('lifted'):
        if t < BH_LIFT_END and ud['z'] < BH_LIFT_HEIGHT:
            ud['vz'] += BH_LIFT_ACCEL
        if BH_LIFT_END <= t < BH_FLING_END:
            ud['vz'] += BH_FLING_ACCEL
        if t == BH_LIFT_END and ud['first']:
            _sfx(b, SFX_BH_FLING)
        ud['vz'] += BH_GRAVITY if ud['z'] < 0 else -BH_GRAVITY      # FUN_004c3211 flags 0x71: 目标 z=0
        ud['z'] += ud['vz']
        v.wind_lift = max(0.0, ud['z'] / 65536)
        v.wind_spin_col = BH_SPIN_COLS[(ud['spin'] // BH_SPIN_FRAME_TICKS) % 4]
        ud['spin'] += 1
    if t < BH_LIFT_END and t % BH_ANCHOR_STEP == 0:
        if t % 64 == 0 and ud['first']:
            _sfx(b, SFX_BH_WIND)
        for k in ('x', 'y'):                                          # flags 0x31: v += ±1px 朝目标, pos += v
            ud['v' + k] += 1 if ud[k] < ud['t' + k] else -1
            ud[k] += ud['v' + k]
        ud['phase'] = 0 if ud['phase'] + 0x1000 >= 0x10000 else ud['phase'] + 0x1000
        e.x, e.y = ud['x'] << 16, ud['y'] << 16
        _spawn_wind_pair(b, e.x, e.y, ud['phase'])
    if t > BH_LIFT_END and (not ud.get('lifted') or ud['z'] < (1 << 16)):
        _sfx(b, SFX_BH_SLAM)
        v.wind_lift = 0.0
        v.wind_spin_col = -1
        sp.on_land(v)
        eng.destroy(e)
        return
    ud['t'] = t + 1


class Tornado(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.casting = False

    def on_cast_impact(self) -> None:
        """-100: 每目标一个风锚."""
        b = self.battle
        for i, v in enumerate(self.targets):
            x, y = _pos(v)
            tx, ty = x >> 16, y >> 16
            ox = 16 + (_rand(b) & 7) if _rand(b) & 1 else None
            if ox is None:
                ox = -(16 + (_rand(b) & 7))
            oy = 12 + _rand(b) % 6 if _rand(b) & 1 else None
            if oy is None:
                oy = -(12 + _rand(b) % 6)
            e = b.engine.spawn(think_fn=_anchor_think)
            e.flags = 0x800 | 0x10000
            e.x, e.y = (tx + ox) << 16, (ty + oy) << 16
            e.user_data.update(kind='wind_anchor', projectile=True, anchor=True, spell=self, victim=v,
                               first=(i == 0), t=0, phase=0, x=tx + ox, y=ty + oy, tx=tx, ty=ty, vx=0, vy=0)
            self.live += 1
        self.casting = True

    def think(self) -> None:
        if self.casting and self.live == 0:                          # 0x1e
            self.casting = False
            self.finish()

    def busy(self) -> bool:
        """0x1e 只等风锚 (+0x78) 与飘字 (+0x7a), 不等受击 seq 标记."""
        return self.live > 0 or getattr(self.battle, 'float_pending', 0) > 0

    def on_land(self, v) -> None:
        """风锚落地: -200 (飘字) 再 -250 (受击 + 刺爆 655c10[施法者朝向] + 星爆)."""
        self.settle(v)
        self.live -= 1
        react(self, v, d=_dir(self.caster), starburst=True)

    def _end(self) -> None:
        for v in self.targets:
            v.wind_lift = 0.0
            v.wind_spin_col = -1
        super()._end()


class QuickAttack(Tornado):
    """131 用快攻: 处理函数 FUN_004df3d1 = hook + FUN_004dafa6(参数 6603d0)."""

    def on_cast_impact(self) -> None:
        c = self.caster
        if c.entity is not None:                                      # -100: 挂 6604b0[朝向] 循环
            self.battle.engine.attach_seq(c.entity, tuple_to_bytecode(QUICK_LOOP_SEQS[_dir(c)]))
            c.cast_hold = True
        super().on_cast_impact()

    def on_land(self, v) -> None:
        c = self.caster
        if c.entity is not None:                                      # -200: 施法者 &= ~0x20000 (定格)
            c.entity.seq = b''
            c.entity.flags &= ~0x20000
        super().on_land(v)


TEMPLATES = {0x4dafa6: Tornado}
MOVES = {131: QuickAttack}
