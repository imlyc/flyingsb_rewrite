"""模板 FUN_004e53a7 机关枪扫射 (1 招: 214 用機關槍掃射) = 八戒普攻 25-27 同一 dispatcher (core.ranged_attack 'pig_hitscan'),
reverse_engineering/enemy_spells_decomp.txt.

dispatcher (无渐暗): case 0 挂施法 seq 表[朝向] (66a860: 两轮 [播 245, 3 连 -100], 末尾 -110), +0x3c = 1.
  -100: 全体目标 复位 + 受击 6557f0[6418dc[施法者朝向]] (面朝施法者) + ef010 刺爆 655c10[施法者朝向] (不抖动)
        + FUN_004e52de 8 粒碎屑 (pao_skills._chiri; 由施法者 seq 信号生成 → 出生当 tick 不 think).
  -110: 全体目标飘字 (+0x40), +0x3c = 0.
  10:   +0x3c == 0 且 飘字完 → 自毁 (无渐亮).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, SIG_CAST_IMPACT

SIG_DONE = -110


class MachineGun(Spell):
    DIM = False
    FADE_IN = False

    def on_cast_impact(self) -> None:
        from core.ranged_attack import _hit
        for v in self.targets:
            _hit(self.battle, self.caster, v, face=True, chiri=1, birth=False)

    def on_caster_signal(self, sig: int) -> bool:
        if sig == SIG_CAST_IMPACT:
            self.on_cast_impact()
            return True
        if sig == SIG_DONE:
            for v in self.targets:
                self.settle(v)
            self.finish()
            return True
        return False

    def busy(self) -> bool:
        return self.live > 0 or getattr(self.battle, 'float_pending', 0) > 0


TEMPLATES = {0x4e53a7: MachineGun}
