"""模板 FUN_004dc4e3 地震落石 (2 招: 69 快速攻擊 / 112 使用猛男攻擊), reverse_engineering/enemy_spells_decomp.txt.
子实体与 孙悟空 玄武 落石同一套 (FUN_004dc42f / 4dc371, 见 core.son_transform 玄武段).

dispatcher: 渐暗 → 施法 seq 表[朝向] → -100: 记 +0x16c = age + 0x50, FUN_004d8c81(10, 10, 1000) 地震
  (单例 FUN_004d8b0c: 播 0xe3, 每 tick 相机原点 ±10px 随机 (rand % 20 - 10), 1000t 超时) → 0x19 等到 age >= +0x16c
  → 0x1e: dispatcher age%16==0 时给下一个目标落一块石头 (FUN_004dc42f):
      目标 (x, y), z = 目标 z + 600, m=0x41 (z 弹簧, vz -64 无加速 = 匀速下落), 朝向 = rand&1 → seq 6599c8[dir]
      (eba00 320 / eba01 321 帧 0 2t, 定格);
      think FUN_004dc371: c3211; z < 1 → 播 0xf6, z = 0, -250, 挂落地 seq 659a1c[dir] (320: 帧 1..3 / 321: 帧 1..4 各 2t);
      播完 → -200 并自毁.
  -250: 目标复位 + 受击 6557f0[目标朝向] + ef010 刺爆 655c10[施法者朝向] + et00 星爆 655b18 (不抖动).
  -200: 计数 +0x7c; 满目标数 → 全体飘字 + FUN_004d8ce1 停地震 (停 0xe3, 相机复位).
  0x28: 全部落完 + 飘字完 + 受击完 → 0x32 渐亮 → 自毁.
石头出生当 tick 先走一步 (同 玄武 实录首帧 z=536).
实录校准 (wine/captures/en69_t35_F4716.log, 69 快速攻擊): 石头 dispatcher age 128 出生 (z 536, 320 帧 0×9 1×2 2×3 3×4 寿命 18)、
  -250 刺爆/星爆 +9、-200 → 飘字 逐 tick 吻合 (相对 dispatcher age; 该实录原版渐暗 19t 比常见 18t 多 1, 绝对 tick 整体差 1).
  修正: 刺爆/星爆以目标受击后退 4px 后的位置为准 (b_common.react). 残差: 渐亮起点相对末位飘字数字 ±1 (公共飘字系统).
"""
from __future__ import annotations

from core.anim_engine.bytecode import tuple_to_bytecode
from core.enemy_spells.base import Spell, _dir, fx, FP, _pos, _rand, _sfx, _c3211, _motion, _getz, _set_z, _unit_z
from core.enemy_spells.b_common import react

ROCK = (320, 321)
ROCK_FALL = [[('fm', a, 0, 2), ('exit',)] for a in ROCK]                                     # 6599c8
ROCK_LAND = [[('fm', 320, f, 2) for f in (1, 2, 3)] + [('exit',)],                           # 659a1c
             [('fm', 321, f, 2) for f in (1, 2, 3, 4)] + [('exit',)]]
SFX_QUAKE, SFX_ROCK = 0xe3, 0xf6
QUAKE_AMP, QUAKE_MAX = 10, 1000
DELAY, INTERVAL = 0x50, 0x10


def _rock_think(e, eng) -> None:
    """FUN_004dc371."""
    ud = e.user_data
    if 'rock' not in ud:
        return
    sp: Quake = ud['spell']
    if ud['st'] == 0:
        _c3211(e)
        if _getz(e) < 1:
            _sfx(sp.battle, SFX_ROCK)
            _set_z(e, 0)
            sp.on_rock_hit(ud['victim'])
            eng.attach_seq(e, tuple_to_bytecode(ROCK_LAND[ud['dir']]))
            ud['st'] = 10
    elif ud['st'] == 10 and not e.is_playing():
        sp.on_rock_done(ud['victim'])
        eng.destroy(e)


class Quake(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.phase = 0
        self.spawned = 0
        self.landed = 0
        self.wait_until = 0
        self.quake = False
        self.quake_end = 0

    # ---- 地震 FUN_004d8c81 / 4d8b0c / 4d8ce1 ----
    def _quake_start(self) -> None:
        if not self.quake:
            _sfx(self.battle, SFX_QUAKE)
        self.quake = True
        self.quake_end = self.age + QUAKE_MAX

    def _quake_stop(self) -> None:
        if not self.quake:
            return
        self.quake = False
        self.battle.shake_offset = (0, 0)
        from core.son_transform import _sfx_stop
        _sfx_stop(self.battle, SFX_QUAKE)

    def _quake_tick(self) -> None:
        if not self.quake:
            return
        b = self.battle
        b.shake_offset = (_rand(b) % (QUAKE_AMP * 2) - QUAKE_AMP, _rand(b) % (QUAKE_AMP * 2) - QUAKE_AMP)
        if self.age >= self.quake_end:
            self._quake_stop()

    # ---- dispatcher ----
    def on_cast_impact(self) -> None:
        self.wait_until = self.age + DELAY
        self.phase = 0x19
        self._quake_start()

    def think(self) -> None:
        self._quake_tick()
        if self.phase == 0x19:
            if self.wait_until <= self.age:
                self.phase = 0x1e
        if self.phase == 0x1e:
            if self.spawned < len(self.targets):
                if self.age % INTERVAL == 0:
                    v = self.targets[self.spawned]
                    self.spawned += 1
                    self._spawn_rock(v)
            else:
                self.phase = 0x28
                if not self.targets:
                    self._quake_stop()
        if self.phase == 0x28 and self.live <= 0:
            self.phase = 0x32
            self.finish()

    def _spawn_rock(self, v) -> None:
        """FUN_004dc42f."""
        b = self.battle
        x, y = _pos(v)
        d = _rand(b) & 1
        e = fx(b, _rock_think, x, y, _unit_z(v) + 600 * FP, ROCK_FALL[d], rock=True, spell=self, victim=v, dir=d,
               st=0, **_motion(m=0x41, vz=-64 * FP, tz=0))
        self.live += 1
        _rock_think(e, b.engine)                  # 出生当 tick 先走一步

    def on_rock_hit(self, v) -> None:
        """-250."""
        react(self, v, d=_dir(self.caster), starburst=True)   # 实录: 刺爆/星爆以目标受击后退 4px 后的位置为准

    def on_rock_done(self, v) -> None:
        """-200: 落满 → 全体飘字 + 停地震."""
        self.live -= 1
        self.landed += 1
        if self.landed == len(self.targets):
            for t in self.targets:
                self.settle(t)
            self._quake_stop()

    def _end(self) -> None:
        self._quake_stop()
        super()._end()


TEMPLATES = {0x4dc4e3: Quake}
