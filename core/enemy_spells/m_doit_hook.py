"""带 hook 的 DOIT_melee 招式 (FUN_004d0e18 外包一层拦截信号), reverse_engineering/enemy_spells_decomp.txt.
施法者 seq = exe 招式参数表 (core.enemy_moves.seq_for 同一张), 结算走普通 DOIT 路径 (combat.apply_pending_attack:
受击面朝施法者 + 命中特效 + 飘字). DOIT 无渐暗.

猛撞 (70 用猛撞攻擊 / 73 / 76 / 79 猛撞攻擊; FUN_004dcaa3 / 4dcb2a / 4dcbb1 / 4dcc38):
  seq 冲过目标共 2 格 (上下 96px / 左右 128px), -100 命中, -110 时 DOIT_melee 按像素位置重算格坐标 (x>>6, y/48)
  = 施法者落在目标身后第 2 格. hook 拦截 -2 (dispatcher 销毁): FUN_004c4f01 把当前位置存为归位点 (+0x7c ← +8),
  朝向 = 6418dc[朝向] (反向) → 施法者停在新格并转身.
  我们: -110 时若落点格在图内且空 → 单位移到落点 + 转身; 否则 (近似) 留原格不转身.
雙拳擊 (245; FUN_004ff223): state 0 置 DAT_006566c0 = 0xbd (命中音, DOIT -100 播); seq 的 -1001 (两次挥拳) → 播 0xb9.
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, SIG_CAST_IMPACT
from core.sprites.base import TILE_W, TILE_H

SIG_END = -110


class DoitHook(Spell):
    DIM = False
    FADE_IN = False

    def on_cast_impact(self) -> None:
        from core.battle import combat
        b = self.battle
        combat.apply_pending_attack(b, self.caster)
        if b.engine.swing_sound >= 0:             # DOIT -100: if (-1 < DAT_006566c0) 播
            b.engine._emit('sound_play', None, b.engine.swing_sound)

    def on_caster_signal(self, sig: int) -> bool:
        if sig == SIG_CAST_IMPACT:
            self.on_cast_impact()
            return True
        if sig == SIG_END:
            self.on_end()
            self.finish()
            return True
        return self.on_hook(sig)

    def on_hook(self, sig: int) -> bool:
        return False

    def on_end(self) -> None:
        pass

    def busy(self) -> bool:
        """DOIT 0x14: 等飘字 + 受击 seq (施法者 seq 已播完)."""
        if getattr(self.battle, 'float_pending', 0) > 0:
            return True
        from core.battle import combat  # noqa: F401
        return any(v.reaction_seq is not None for v in self._victims())

    def _victims(self) -> list:
        t = self.caster.pending_attack_target
        return list(self.targets) + ([t] if t is not None and t not in self.targets else [])


class Ram(DoitHook):
    def on_end(self) -> None:
        c, b = self.caster, self.battle
        ent = c.entity
        if ent is None:
            return
        dx = round((ent.x / 65536) / TILE_W)
        dy = round((ent.y / 65536) / TILE_H)
        if not (dx or dy):
            return
        nx, ny = c.x + dx, c.y + dy
        if not (b.map.in_bounds(nx, ny) and b.q.is_free(nx, ny, c)):
            b._log(f"{c.name} 猛撞落点 ({nx},{ny}) 不可站, 留原格")
            return
        c.x, c.y = nx, ny
        c.snap_render()
        ent.x = ent.y = 0
        c.facing = (-c.facing[0], -c.facing[1])   # -2: 朝向 = 6418dc[朝向]


class DoubleFist(DoitHook):
    SFX_SWING, SFX_HIT = 0xb9, 0xbd

    def _attach(self) -> None:
        self.battle.engine.swing_sound = self.SFX_HIT   # state 0: DAT_006566c0 = 0xbd
        super()._attach()

    def on_hook(self, sig: int) -> bool:
        if sig == -1001:
            self.battle.engine._emit('sound_play', None, self.SFX_SWING)
            return True
        return False


MOVES = {70: Ram, 73: Ram, 76: Ram, 79: Ram, 245: DoubleFist}
