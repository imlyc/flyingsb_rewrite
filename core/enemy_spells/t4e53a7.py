"""模板 FUN_004e53a7 机关枪扫射 (1 招: 214 用機關槍掃射) = 八戒普攻 25-27 同一 dispatcher (core.ranged_attack 'pig_hitscan'),
reverse_engineering/enemy_spells_decomp.txt.

dispatcher (无渐暗): case 0 挂施法 seq 表[朝向] (66a860: 两轮 [播 245, 3 连 -100], 末尾 -110), +0x3c = 1.
  -100: 全体目标 复位 + 受击 6557f0[6418dc[施法者朝向]] (面朝施法者) + ef010 刺爆 655c10[施法者朝向] (不抖动)
        + FUN_004e52de 8 粒碎屑 (pao_skills._chiri).
  -110: 全体目标飘字 (+0x40), +0x3c = 0.
  10:   +0x3c == 0 且 飘字完 → 自毁 (无渐亮).
实录校准 (wine/captures/en214_t168_F10478.log, 214 用機關槍掃射): 施法者帧序列、6 次 -100 (+12/17/22/40/45/50) 刺爆 + 8 碎屑、
  -110 +59 逐 tick 吻合. 修正: 碎屑出生当 tick 已挂 seq 但不 think (原版帧 8×1 起、首帧位置未动、寿命 11; 跟玩家八戒 25-27 不同). 残差: 飘字/收尾 ±1 (公共飘字系统).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, SIG_CAST_IMPACT

SIG_DONE = -110


class MachineGun(Spell):
    DIM = False
    FADE_IN = False

    def on_cast_impact(self) -> None:
        from core.battle import combat
        from core.pao_skills import _spark, _chiri, CHIRI_SEQ
        from core.anim_engine.bytecode import tuple_to_bytecode
        eng = self.battle.engine
        for v in self.targets:
            if not v.alive:
                continue
            combat.set_reaction(v, "hit", self.caster)
            _spark(self.battle, self.caster, v)
            before = set(map(id, eng.entities))
            _chiri(self.battle, v, False)
            for e in eng.entities:                # 实录: 出生当 tick 已挂 seq (首帧 8 只停 1t), 但不 think (首帧 z 436 未动)
                if id(e) not in before and e.user_data.pop('chiri_pending', False):
                    eng.attach_seq(e, tuple_to_bytecode(CHIRI_SEQ))

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
