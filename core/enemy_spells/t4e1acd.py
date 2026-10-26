"""模板 FUN_004e1acd 声波 (2 招: 156 使賽亞安攻擊 / 165 使用聲波攻擊), reverse_engineering/enemy_spells_decomp.txt
(+ FUN_004e18b8 补反编译). 只打首目标 DAT_00869c48.

dispatcher (无渐暗): case 0 挂施法 seq 表[朝向] → -100: FUN_004e19ae 声波 (+0x78) → 0x14.
  声波: 施法者 (x, y), z = 施法者 z + 32; m=0x31 (x/y 弹簧, 无加速度), 目标 = 首目标 (x, y);
      速度按施法者朝向: 上 vy -9 / 下 vy +9 / 左 vx -12 / 右 vx +12 (另一轴速度 0 → 首 tick 吸附到目标);
      seq 662bd4 (atlas 328 帧 2 2t, 定格); 播 0xe4.
      think FUN_004e1943: cdbc2 (越过目标即钳位) + 每 tick 原地留残影 FUN_004e18ee (seq 662be0 帧 2,1,0 各 1t, 完自毁);
      x/y 都到 → 停 0xe4, 播 0xbd, -200, 自毁.
  -200: 首目标复位 + 受击 6557f0[目标朝向] + ef010 刺爆 655c10[施法者朝向] + et00 星爆 655b18 (两个都三轴抖动 rand&15-8)
        + 飘字 (+0x7a), +0x78 --.
  0x14: +0x78 == 0 且 飘字完 → 自毁 (不等受击 seq, 无渐亮).
实录校准 (wine/captures/en165_t121_F5924.log, 165 使用聲波攻擊): 声波 +11 出生 (出生当 tick 不 think) 寿命 16, 残影 +12..+27
  每 tick 一个 (帧 2 1×2 0×3), -200 +27、飘字 +28 起逐 tick 吻合; 修正: 刺爆/星爆基准 = 目标受击后退 4px 后的位置,
  施法者在 dispatcher 自毁后第 2 tick 才回待机. dispatcher 结束 = 末位飘字数字 +31 (原版 4 位数字所以晚 2 tick, 数值差异).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _sfx, _cdbc2, _motion, _dir, _unit_z, _getz
from core.enemy_spells._d_fx import starburst, spark

WAVE = 328
WAVE_SEQ = [('fm', WAVE, 2, 2), ('exit',)]                                   # 662bd4
TRAIL_SEQ = [('fm', WAVE, f, 1) for f in (2, 1, 0)] + [('exit',)]           # 662be0
SFX_WAVE, SFX_HIT = 0xe4, 0xbd
VEL = {0: (0, -9), 1: (0, 9), 2: (-12, 0), 3: (12, 0)}


def _trail_think(e, eng) -> None:
    """FUN_004e18b8."""
    if 'trail' in e.user_data and not e.is_playing():
        eng.destroy(e)


def _wave_think(e, eng) -> None:
    """FUN_004e1943."""
    ud = e.user_data
    if 'wave' not in ud:
        return
    sp: SoundWave = ud['spell']
    _cdbc2(e)
    fx(sp.battle, _trail_think, e.x, e.y, _getz(e), TRAIL_SEQ, trail=True)
    if ud['m'] & 0x30 == 0:
        from core.son_transform import _sfx_stop
        _sfx_stop(sp.battle, SFX_WAVE)
        _sfx(sp.battle, SFX_HIT)
        sp.on_wave_hit()
        eng.destroy(e)


class SoundWave(Spell):
    DIM = False
    FADE_IN = False

    def on_cast_impact(self) -> None:
        if not self.targets:
            self.finish()
            return
        c, v = self.caster, self.targets[0]
        x, y = _pos(c)
        tx, ty = _pos(v)
        d = _dir(c)
        vx, vy = VEL[d]
        fx(self.battle, _wave_think, x, y, _unit_z(c) + 32 * FP, WAVE_SEQ, wave=True, spell=self,
           **_motion(m=0x31, vx=vx * FP, vy=vy * FP, tx=tx, ty=ty))
        _sfx(self.battle, SFX_WAVE)
        self.live += 1

    def on_wave_hit(self) -> None:
        """-200."""
        v = self.targets[0]
        self.hit(v, fx=None)
        if v.alive:
            spark(self.battle, self.caster, v, jitter=True, knock=True)      # 实录: 以受击后退 4px 后为基准
            starburst(self.battle, v, jitter=True, knock=True)
        self.live -= 1
        self.settle(v)
        self.finish()

    def busy(self) -> bool:
        """exe 0x14 只等声波 + 飘字."""
        return self.live > 0 or getattr(self.battle, 'float_pending', 0) > 0

    def _end(self) -> None:
        """实录: dispatcher 自毁后第 2 tick 施法者才回待机 (框架无渐亮路径只留 1 tick)."""
        super()._end()
        c = self.caster
        if c.entity is not None:
            c.entity.user_data['hold_until_tick'] = self.battle.engine._tick_id + 2


TEMPLATES = {0x4e1acd: SoundWave}
