"""模板 FUN_004d2769 (6 招 异常 痲痺类: 16 施展超級波拉姿 / 22 使用波拉姿 / 78 使用波羅拉斯 / 115 / 145 / 186 使用波拉姿),
reverse_engineering/enemy_spells_decomp.txt. 子实体与乐神杰特 重金屬 (core/jet_skills.py 0x25) 相同.

dispatcher: 渐暗 → 施法 seq → -100: 每目标 FUN_004d2746 光爆发生器 (+0x78 ++), 进 0x1e.
  0x1e: +0x78 == 0 且 +0x7a == 0 且所有目标受击 seq 完 → 0x28 渐亮 → 自毁.
  -250: 目标复位 + 受击 seq 6557f0[目标朝向] + ef010 刺爆 655c10[6418dc[目标朝向]].
  -200: 仅 +0x78 -- (exe 无飘字; 这里在此刻做异常结算 Spell.settle, 未中飘 MISS).
发生器 FUN_004d26b0: age 0,4,8,12 各 FUN_004d2632: 目标位置光爆 (e_para seq 6568f8[rand%5], 2 帧各 1t) + 0xc1; 第 4 个打 0x40000.
光爆 FUN_004d2418: seq 播完 → -250, 化为碎片: 目标 ±(24+rand&7) / +8±(6+rand%6), flags 0x31 弹簧回 (目标, 目标+8)
  a=0.5/0.375, seq 656a08[rand%3] (8 帧各 3t 循环), 每 t 1/4 概率隐身; age > 0x3b → (打标记的) -200, 自毁.
近似: 出生 think 时机同杰特实现 (发生器由 -100 生成, 不在出生 tick think).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _set_z
from core.enemy_spells.b_common import react
from core.anim_engine.bytecode import tuple_to_bytecode
from core.jet_skills import HEAVY_SEQS, SHARD_SEQS

SFX_BURST = 0xc1
BURST_STEP = 4
BURSTS = 4
SHARD_LIFE = 0x3b


def _shard_think(e, eng) -> None:
    """FUN_004d2418."""
    ud = e.user_data
    if 'shard' not in ud:
        return
    sp: Paralyze = ud['spell']
    b, v = sp.battle, ud['victim']
    if ud['state'] == 0:
        ud['age'] += 1
        if e.is_playing():
            return
        react(sp, v)                                                  # -250
        vx, vy = _pos(v)
        ox = (_rand(b) & 7) * FP + 24 * FP if _rand(b) & 1 else None
        if ox is None:
            ox = -((_rand(b) & 7) * FP + 24 * FP)
        oy = (_rand(b) % 6) * FP + 6 * FP if _rand(b) & 1 else None
        if oy is None:
            oy = -((_rand(b) % 6) * FP + 6 * FP)
        e.x, e.y = vx + ox, vy + 8 * FP + oy
        _set_z(e, 0)
        ud.update(state=10, tx=vx, ty=vy + 8 * FP, vx=0, vy=0, ax=0x8000, ay=0x6000)
        eng.attach_seq(e, tuple_to_bytecode(SHARD_SEQS[_rand(b) % 3]))
        return
    for axis, vk, tk, ak in (('x', 'vx', 'tx', 'ax'), ('y', 'vy', 'ty', 'ay')):   # FUN_004c3211 flags 0x31
        ud[vk] += ud[ak] if getattr(e, axis) < ud[tk] else -ud[ak]
        setattr(e, axis, getattr(e, axis) + ud[vk])
    if _rand(b) & 3 == 0:
        e.flags &= ~0x40
    else:
        e.flags |= 0x40
    ud['age'] += 1
    if ud['age'] > SHARD_LIFE:
        if ud.get('last'):
            sp.on_done(v)                                             # -200
        eng.destroy(e)


def _spawner_think(e, eng) -> None:
    """FUN_004d26b0."""
    ud = e.user_data
    if 'spawner' not in ud:
        return
    sp: Paralyze = ud['spell']
    b, v = sp.battle, ud['victim']
    if ud['age'] == ud['next']:
        x, y = _pos(v)
        s = fx(b, _shard_think, x, y, 0, HEAVY_SEQS[_rand(b) % 5], shard=True, spell=sp, victim=v, state=0, age=0)
        _sfx(b, SFX_BURST)
        ud['n'] += 1
        if ud['n'] == BURSTS:
            s.user_data['last'] = True
            eng.destroy(e)
            return
        ud['next'] += BURST_STEP
    ud['age'] += 1


class Paralyze(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.casting = False

    def on_cast_impact(self) -> None:
        for v in self.targets:
            e = self.battle.engine.spawn(think_fn=_spawner_think)
            e.flags = 0x800 | 0x10000
            e.user_data.update(kind='enemy_spell_fx', projectile=True, spawner=True, spell=self, victim=v,
                               age=0, next=0, n=0)
            self.live += 1
        self.casting = True

    def think(self) -> None:
        if self.casting and self.live == 0:
            self.casting = False
            self.finish()

    def on_done(self, v) -> None:
        """-200."""
        self.live -= 1
        self.settle(v)


TEMPLATES = {0x4d2769: Paralyze}
