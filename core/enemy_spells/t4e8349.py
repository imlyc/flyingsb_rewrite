"""模板 FUN_004e8349 新音功 (3 招, 全带 hook: 23 使用新音功 / 110 施出新音功 / 119 播放鎖碼頻道),
reverse_engineering/enemy_spells_decomp.txt (+ FUN_004e8152 补反编译).

hook (FUN_004e87db / 4dda08 / 4ddfb8): -100 时先播音 (23 → 0xeb, 110 → 0xff, 119 → 0xf8), 再交给模板.
dispatcher: 渐暗 → 施法 seq 表[朝向] → -100: 每个目标一个隐形控制实体 FUN_004e8260 (+0x78 计数) → 0x1e.
  控制实体: age > 0x3c 起每 tick 一次, 共 0x20 次:
      首目标首次播 0xd4; FUN_004e8192 在目标处 (z+72) 生成 2 个音符 (seq 66f2dc ds 227 帧 8..11 各 2t, 12..15 各 1t),
      think FUN_004e8152: c3211 (m=0x51 弹簧 x/z: vx ±1, vz 8, az 0.5 朝 tz=0 → 上抛回落), seq 完自毁;
      对 dispatcher 发 -200: 目标复位 + 受击 seq 66f2cc[目标朝向] (atlas06 帧 12+dir 停 20t, 然后 -15 回待机)
      + ef010 刺爆 655c10[施法者朝向] (每 tick 一个);
      第 0x20 次再发 -250: 飘字 (+0x7a), 控制实体自毁 (+0x78 --).
  0x1e: 控制实体全完 + 飘字全完 → 0x28 渐亮 → 自毁 (不等目标受击 seq).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _sfx, _c3211, _motion, _unit_z
from core.enemy_spells._d_fx import spark, custom_reaction, ctl

HOOK_SFX = {23: 0xeb, 110: 0xff, 119: 0xf8}
SFX_NOTE = 0xd4
NOTE_SEQ = [('fm', 227, f, 2) for f in range(8, 12)] + [('fm', 227, f, 1) for f in range(12, 16)] + [('exit',)]
DELAY, COUNT = 0x3c, 0x20
HOLD = 20                                         # 66f2cc: ('idle', 6, 12+dir, 20)


def _note_think(e, eng) -> None:
    """FUN_004e8152."""
    ud = e.user_data
    if 'note' not in ud:
        return
    _c3211(e)
    if not e.is_playing():
        eng.destroy(e)


def _ctl_think(e, eng) -> None:
    """FUN_004e8260."""
    ud = e.user_data
    if 'sing' not in ud:
        return
    ud['age'] += 1
    if ud['age'] <= DELAY:
        return
    sp: NewSound = ud['spell']
    v = ud['victim']
    if ud['n'] == 0 and ud['first']:
        _sfx(sp.battle, SFX_NOTE)
    sp.notes(v)
    sp.on_tick(v)                                 # -200
    ud['n'] += 1
    if ud['n'] == COUNT:
        sp.on_ctl_done(v)                         # -250
        eng.destroy(e)


class NewSound(Spell):
    def on_cast_impact(self) -> None:
        snd = HOOK_SFX.get(self.mid)
        if snd is not None:
            _sfx(self.battle, snd)
        for i, v in enumerate(self.targets):
            ctl(self.battle, _ctl_think, sing=True, spell=self, victim=v, first=(i == 0), age=0, n=0)
            self.live += 1
        if not self.targets:
            self.finish()

    def notes(self, v) -> None:
        """FUN_004e8192: 2 个音符, vx = -1 / +1."""
        x, y = _pos(v)
        z = _unit_z(v) + 72 * FP
        for i in range(2):
            fx(self.battle, _note_think, x, y, z, NOTE_SEQ, note=True,
               **_motion(m=0x51, vx=(FP if i else -FP), vz=8 * FP, az=0x8000, tz=0))

    def on_tick(self, v) -> None:
        if not v.alive:
            return
        from core.reaction_seq import facing_to_seq_index
        d = facing_to_seq_index(v.facing)
        custom_reaction(v, [('frame', 12 + d), ('move', 0, 0, HOLD), ('frame', d)])
        spark(self.battle, self.caster, v)

    def on_ctl_done(self, v) -> None:
        self.live -= 1
        self.settle(v)
        if self.live <= 0:
            self.finish()

    def busy(self) -> bool:
        """exe 0x1e 只等控制实体 + 飘字, 不等受击 seq."""
        return self.live > 0 or getattr(self.battle, 'float_pending', 0) > 0


TEMPLATES = {0x4e8349: NewSound}
