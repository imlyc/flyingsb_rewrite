"""招式 31 使用沒兆喜 (回复) = custom dispatcher FUN_004eba08.

dispatcher: 0 渐暗 → 10 施法者挂 66ffe4[朝向] (播 187, atlas 58 每方向 8 帧: 7×3t + 末帧 12t, 然后 -100)
  -100: FUN_004d074e(施法者, 预算回复量) 施法者头上回复数字, 0x78 = 1 → 0x1e.
  -20 (数字完): 施法者回待机, 0x78 = 0.  0x1e: 0x78 == 0 → 0x28 渐亮 → 自毁.
结算: 回复按 core.enemy_moves 类别 2 (框架 settle) 对目标表逐个; 目标表空时治施法者自己
  (exe 数字固定画在施法者头上, 值 = 目标0 的预算量; 目标 ≠ 施法者时我们把数字画在实际被治疗者头上, 差异).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell

CAST = [[('sound', 187, 1041)] + [('fm', 58, d * 8 + k, 3) for k in range(7)] + [('fm', 58, d * 8 + 7, 12),
                                                                               ('jump', -100), ('exit',)]
        for d in range(4)]


class MeiZhaoXi(Spell):
    def cast_seq(self, d):
        return CAST[d]

    def on_cast_impact(self) -> None:
        for v in (self.targets or [self.caster]):
            self.settle(v)
        self.finish()


MOVES = {31: MeiZhaoXi}
