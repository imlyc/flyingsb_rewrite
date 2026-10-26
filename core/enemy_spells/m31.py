"""招式 31 使用沒兆喜 (回复) = custom dispatcher FUN_004eba08.

dispatcher: 0 渐暗 → 10 施法者挂 66ffe4[朝向] (播 187, atlas 58 每方向 8 帧: 7×3t + 末帧 12t, 然后 -100)
  -100: FUN_004d074e(施法者, 预算回复量) 施法者头上回复数字, 0x78 = 1 → 0x1e.
  -20 (数字完): 施法者回待机, 0x78 = 0.  0x1e: 0x78 == 0 → 0x28 渐亮 → 自毁.
结算: 回复按 core.enemy_moves 类别 2 (框架 settle) 对目标表逐个; 目标表空时治施法者自己
  (exe 数字固定画在施法者头上, 值 = 目标0 的预算量; 目标 ≠ 施法者时我们把数字画在实际被治疗者头上, 差异).
实录校准 (wine/captures/en31_t11_F8326.log, 自疗): -100 白字 +40、渐亮 +98 吻合; 施法者在白字 -20 那 tick 回待机
  (渐亮前), 收尾不再保持施法帧. 白字寿命 79 vs 原版 81 属公共白字系统.
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

    def _finish_tick(self) -> None:
        c = self.caster
        if self._fade is None and c.cast_hold and not self.busy():
            self._release()                       # -20: 施法者回待机 (渐亮前)
        super()._finish_tick()

    def _release(self) -> None:
        c = self.caster
        c.cast_hold = False
        if c.entity is not None:
            c.entity.user_data.pop('hold_until_tick', None)

    def _end(self) -> None:
        super()._end()
        self._release()


MOVES = {31: MeiZhaoXi}
