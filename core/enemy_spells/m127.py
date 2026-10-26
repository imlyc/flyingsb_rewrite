"""127 以拳頭打擊 (吸塵機, 吸血): dispatcher FUN_004dee7f (custom), reverse_engineering/enemy_spells_decomp.txt, 2026-10-26.

dispatcher:
  case 0  渐暗 → 10 挂施法 seq 6600c0[朝向] (图 117 1 帧 1t, -100) → 0x1e.
  -100    每个目标 FUN_004dee2c(目标, 施法者): 计时实体 (无图), 播 0xb3.
  计时 think FUN_004ded29: age == next (初值 4) → 两粒 FUN_004de9f2 (目标 → 施法者); n++; next += max(1, 4 - n/16);
          n > 31 → 以目标为源发 -200, 自毁.  (共 32 轮 64 粒, 间隔 前 15 轮 4t 后 16 轮 3t)
  粒子 FUN_004de9f2(目标, 施法者): 生在 目标 (x + rand%48-24, y+1, z + rand&63), 飞向 施法者 (x, y+1, z+36)
          + 朝向偏移 (上 y-12 / 下 y+12 / 左 x-40 / 右 x+40); mode 0x71 FUN_004cdbc2 三轴匀速:
          |dx|<|dy|: 速 s = 1 + rand%2000/1000 px, vy = ±s, 步数 = max(1, |dx|/s), vx = dx/步数;
          否则:     速 s = 2 + rand%2000/1000 px, vx = ±s, 步数 = max(1, |dx|/s), vy = dy/步数;  vz = dz/步数.
          (exe 两支都用 |dx| 算步数, 照抄) seq 6564d8 (图 247 帧 30-32 循环); think FUN_004de9b2: 三轴都到 → 自毁.
  -200    目标 FUN_004c4f20 + 受击 6557f0 + 655c10[反(目标朝向)] 刺爆 (无星爆) + 目标飘字
          + FUN_004d074e(施法者, DAT_007da1ec) 施法者白字 (= 吸到的 HP) + 0x143.
数值: exe FUN_004a6efe 对招式 0x20 / 0x7f (= 127): DAT_007da1ec = 伤害 (≤ 施法者缺的 HP), 施法者 HP += 它.
落空 (DAT_007da1ec = -1) → 施法者白字 MISS 字形 (FUN_004d074e param<0).
实录校准 (wine/captures/en127_t88_F5694.log): 计时实体 (+1)、每轮粒子出生 tick、-200/刺爆/飘字 (+114)、施法者白字 "0"
  (满血吸 0 仍飘, 80 t, 它的 -20 决定收尾)、dispatcher 寿命 211 t 逐 tick 吻合; 粒子出生当 tick 已走第 1 步 (已改).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _cdbc2, _motion, _dir, _unit_z, _getz
from core.enemy_spells.m203 import impact_fx, reset_hit, OPP

CAST_127 = [  # @0x6600c0
    [('fm', 117, 4, 1), ('jump', -100), ('exit',)],
    [('fm', 117, 9, 1), ('jump', -100), ('exit',)],
    [('fm', 117, 14, 1), ('jump', -100), ('exit',)],
    [('fm', 117, 19, 1), ('jump', -100), ('exit',)],
]
DUST = [('fm', 247, 30, 1), ('fm', 247, 31, 1), ('fm', 247, 32, 1), ('loop',)]  # @0x6564d8
SUCK_OFF = ((0, -12), (0, 12), (-40, 0), (40, 0))
SFX_START, SFX_HIT = 0xb3, 0x143


def _c_div(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def aim_motion(battle, x: int, y: int, z: int, tx: int, ty: int, tz: int) -> dict:
    """FUN_004de9f2 / FUN_004df543 的速度计算 (mode 0x71). 返回 _motion dict."""
    dx, dy = tx - x, ty - y
    if abs(dx) < abs(dy):
        s = _c_div((_rand(battle) % 2000) << 16, 1000) + 0x10000
        steps = max(1, abs(dx) // s)
        vx = _c_div(dx, steps)
        vy = -s if dy <= 0 else s
    else:
        s = _c_div((_rand(battle) % 2000) << 16, 1000) + 0x20000
        steps = max(1, abs(dx) // s)
        vx = -s if dx <= 0 else s
        vy = _c_div(dy, steps)
    vz = _c_div(tz - z, steps)
    return _motion(m=0x71, vx=vx, vy=vy, vz=vz, tx=tx, ty=ty, tz=tz)


def _dust_think(e, eng) -> None:
    """FUN_004de9b2."""
    if 'dust' not in e.user_data:
        return
    if _cdbc2(e):
        eng.destroy(e)


def _dust(battle, victim, caster) -> None:
    """FUN_004de9f2(目标, 施法者)."""
    vx, vy = _pos(victim)
    x = vx + (_rand(battle) % 48 - 24) * FP
    y = vy + FP
    z = _unit_z(victim) + (_rand(battle) & 63) * FP
    cx, cy = _pos(caster)
    ox, oy = SUCK_OFF[_dir(caster)]
    tx, ty, tz = cx + ox * FP, cy + FP + oy * FP, _unit_z(caster) + 36 * FP
    e = fx(battle, _dust_think, x, y, z, DUST, dust=True, **aim_motion(battle, x, y, z, tx, ty, tz))
    if _cdbc2(e):                 # 实录 en127_t88: 粒子出生当 tick 已走第 1 步
        battle.engine.destroy(e)


def _timer_think(e, eng) -> None:
    """FUN_004ded29."""
    ud = e.user_data
    if 'suck' not in ud:
        return
    sp: Suck = ud['spell']
    if ud['age'] == ud['next']:
        _dust(sp.battle, ud['victim'], sp.caster)
        _dust(sp.battle, ud['victim'], sp.caster)
        ud['n'] += 1
        ud['next'] += max(1, 4 - ud['n'] // 16)
        if ud['n'] > 31:
            sp.on_settle(ud['victim'])
            eng.destroy(e)
            return
    ud['age'] += 1


class Suck(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.fired = False

    def cast_seq(self, d: int):
        return CAST_127[d]

    def on_cast_impact(self) -> None:
        if self.fired:
            return
        self.fired = True
        b = self.battle
        for v in self.targets:
            e = b.engine.spawn(think_fn=_timer_think)
            e.flags = 0x800 | 0x10000
            e.user_data.update(kind='hit_effect', projectile=True, suck=True, spell=self, victim=v, age=0, n=0, next=4)
            self.live += 1
            _sfx(b, SFX_START)
        if not self.targets:
            self.finish()

    def on_settle(self, v) -> None:
        """-200."""
        from core.battle import combat
        b, c = self.battle, self.caster
        self.live -= 1
        reset_hit(v)
        impact_fx(b, v, OPP[_dir(v)], None, jitter=False)
        before = v.hp
        n_ev = len(b.damage_events)
        self.settle(v)
        dealt = max(0, before - v.hp)
        miss = any(ev.miss for ev in b.damage_events[n_ev:])
        gain = min(dealt, max(0, c.max_hp - c.hp))
        c.hp += gain
        # exe 总是 FUN_004d074e(施法者, DAT_007da1ec): 落空 (-1) = 白字 MISS 字形, 否则吸到的量 (满血时 "0", 实录 en127_t88)
        combat.push_damage_event(b, c, combat.DamageEvent(gain, c.hp, c.x, c.y, miss=miss, heal=True))
        b._log(f"{c.name}: 吸取 HP +{gain} ({c.hp}/{c.max_hp})")
        _sfx(b, SFX_HIT)
        if self.live <= 0:
            self.finish()


MOVES = {127: Suck}
