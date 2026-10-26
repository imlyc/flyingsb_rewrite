"""招式 30 施出電子衝擊 = custom dispatcher FUN_004eb5bb.

dispatcher: 0 渐暗 → 10 施法者挂 66fde0[朝向] (atlas 57, 前冲 + 播 176, 4 帧各 3t 后 -100)
  -100: 每个目标 复位 + **目标本体挂 seq 66fdf0** (触电: atlas 236 帧 1/2 交替各 8t × 6 = 96t, 然后 -200, -10),
        受击标记; 播 0xe9 (电流声), 0x78 = 1 → 0x1e.
  -200 (源 = 目标): 飘字; 施法者复位 + 回待机; 目标挂受击 6557f0[目标自身朝向] (无刺爆); 停 0xe9; 0x78 = 0.
  0x1e: 0x78 / 0x7a / 受击 全清 → 0x28 渐亮 → 自毁.
实录校准 (wine/captures/en30_t11_F5724.log): -200 在 -100 后 108 t (每帧 9 t), 飘字/渐亮随之吻合;
  施法者在 -200 已回待机, 收尾不再保持施法帧 (覆盖 _end 去掉 hold_until_tick).
实现: 触电 seq 去掉末尾两个信号 op 挂到目标 entity (cast_hold 让渲染走 entity 帧), dispatcher 自己数 96t 当 -200.
"""
from __future__ import annotations

from core.anim_engine.bytecode import tuple_to_bytecode
from core.enemy_spells.base import Spell, _sfx
from core.enemy_spells._ecommon import stop_sfx

_STEP = ((0, -1, 3), (0, 1, 3), (-1, 0, 4), (1, 0, 4))
_FRAMES = ((0, 2, 3, 4), (7, 9, 10, 11), (14, 16, 17, 18), (21, 23, 24, 25))


def _cast(d: int) -> list[tuple]:
    """66fde0[d]: 冲 6px + 播 176, 再 3 步各 3/4px, 4 帧各 3t, -100."""
    sx, sy, n = _STEP[d]
    f = _FRAMES[d]
    mv = ('move', sx * n, sy * n, 0, 0)
    return [('move', sx * 6, sy * 6, 0, 0), ('sound', 176, 1041), ('fm', 57, f[0], 3), mv, ('fm', 57, f[1], 3), mv,
            ('fm', 57, f[2], 3), mv, ('fm', 57, f[3], 3), ('jump', -100), ('exit',)]


CAST = [_cast(d) for d in range(4)]
SHOCK_SEQ = [('fm', 236, 1 + (k & 1), 8) for k in range(12)] + [('exit',)]     # 66fdf0 (去掉 -200 / -10)
SHOCK_TICKS = 12 * 9            # 实录 en30_t11: 单位 seq 的 fm n 每帧占 n+1 t → 12 帧 108 t (-100 @+15 → -200 @+123)
SFX_SHOCK = 0xe9


class ElectroShock(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.until = None

    def cast_seq(self, d):
        return CAST[d]

    def on_cast_impact(self) -> None:
        eng = self.battle.engine
        for v in self.targets:
            if not v.alive:
                continue
            if v.entity is None:                       # 玩家平时没 entity (同 jet_skills._attach_unit_seq)
                v.entity = eng.spawn()
                v.entity.user_data = {'unit': v}
            v.entity.x = v.entity.y = v.entity.z = 0
            v.entity.user_data.pop('idle_until_tick', None)
            v.reaction_seq = None
            v.cast_hold = True
            eng.attach_seq(v.entity, tuple_to_bytecode(SHOCK_SEQ))
        _sfx(self.battle, SFX_SHOCK)
        self.until = self.battle.engine._tick_id + SHOCK_TICKS     # 按引擎 tick (-100 在协调实体 think 之前/后都对)

    def think(self) -> None:
        if self.until is None or self.battle.engine._tick_id < self.until:
            return
        self.until = None
        from core.battle import combat
        c = self.caster
        for v in self.targets:            # -200 (每个目标的 seq 同时到)
            self.settle(v)
            c.cast_hold = False
            v.cast_hold = False
            if v.alive:
                combat.set_reaction(v, "hit", None)
        stop_sfx(self.battle, SFX_SHOCK)
        self.finish()

    def _end(self) -> None:
        super()._end()
        e = self.caster.entity
        if e is not None:                # 施法者 -200 时已复位回待机 (exe), 不再显示施法帧
            e.user_data.pop('hold_until_tick', None)


MOVES = {30: ElectroShock}
