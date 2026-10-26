"""模板 FUN_004d9c9e (5 招: 6 施放火牆 / 60 / 93 召來火牆 / 148 召來火炎牆 / 195 用火炎牆, 每目标一道火柱),
reverse_engineering/enemy_spells_decomp.txt.

dispatcher: 渐暗 → 施法 seq → -100: 每个目标 FUN_004d9c37 生成火柱 (+0x78 ++), state 0x1e.
  火柱 think FUN_004d9ad1: 出生 = 目标 (x, y+1px, z), +400 = 目标; seq 656cd0 (播 0xd7, ef 296 帧 0..13 各 1t);
       state 0: age%20==0 → 对目标发 -200; seq 完 → 挂循环 656d64 (帧 8..13), 记 age → 10;
       state 10: age%20==0 → -200; age > 记录+20 → 挂收尾 656da4 (帧 13,11,..,1,0) → 0x14;
       state 0x14: age%20==0 → -200; seq 完 → 发 -210, 自毁.
  -200: 该目标 FUN_004c4f20 + 受击 6557f0[目标朝向] + ef010 刺爆 655c10[施法者朝向] (可多次: age 0/20/40).
  -210: 该目标飘字, +0x7a ++, +0x78 --.   -20: +0x7a --.
  0x1e: 0x78/0x7a 都 0 → 0x28 渐亮 → 自毁 (exe 不等受击 seq; 框架 finish 仍等, 差别仅收尾 1-2t).
近似: 子实体 age 取 "先判后加" (出生后第一次 think age=0 → 立即一次 -200).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _unit_z
from core.anim_engine.bytecode import tuple_to_bytecode

WALL = 296
START_SEQ = [('sound', 215, 1041)] + [('fm', WALL, f, 1) for f in range(14)] + [('exit',)]     # 656cd0
LOOP_SEQ = [('fm', WALL, f, 1) for f in range(8, 14)] + [('loop',)]                             # 656d64
END_SEQ = [('fm', WALL, f, 1) for f in (13, 11, 9, 7, 5, 3, 1, 0)] + [('exit',)]                 # 656da4
HIT_EVERY = 20
LOOP_TICKS = 20


def _wall_think(e, eng) -> None:
    """FUN_004d9ad1."""
    ud = e.user_data
    if 'wall' not in ud:
        return
    sp: FireWall = ud['spell']
    age, st = ud['age'], ud['state']
    if age % HIT_EVERY == 0:
        sp.hit(ud['victim'])
    if st == 0:
        if not e.is_playing():
            eng.attach_seq(e, tuple_to_bytecode(LOOP_SEQ))
            ud['t0'] = age
            ud['state'] = 10
    elif st == 10:
        if age > ud['t0'] + LOOP_TICKS:
            eng.attach_seq(e, tuple_to_bytecode(END_SEQ))
            ud['state'] = 0x14
    elif not e.is_playing():
        eng.destroy(e)
        sp.on_wall_done(ud['victim'])
        return
    ud['age'] = age + 1


class FireWall(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.fired = False

    def on_cast_impact(self) -> None:
        """-100: FUN_004d9c37 × 目标数."""
        self.fired = True
        for v in self.targets:
            x, y = _pos(v)
            fx(self.battle, _wall_think, x, y + FP, _unit_z(v), START_SEQ, wall=True, spell=self, victim=v,
               age=0, state=0, t0=0)
            self.live += 1

    def on_wall_done(self, v) -> None:
        """-210."""
        self.live -= 1
        self.settle(v)

    def think(self) -> None:
        if self.fired and self.live == 0:
            self.fired = False
            self.finish()


TEMPLATES = {0x4d9c9e: FireWall}
