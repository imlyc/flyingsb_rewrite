"""模板 FUN_004da489 (9 招: 7 施放魔法風暴 / 62 / 74 / 98 / 99 / 128 / 130 / 150 / 151, 每目标一团旋风),
reverse_engineering/enemy_spells_decomp.txt.

dispatcher: 渐暗 → 施法 seq → -100: 每个目标 FUN_004da35f 生成旋风控制体 (+0x78 ++), state 0x1e.
  控制体 (不可见) think FUN_004da1d8: 出生 = 目标 (x ± (16 + rand&15), y ± (12 + rand%12)) px, z 0
       (掷骰顺序: rand&1, rand&15, rand&1, rand%12), +0x198 = 目标; FUN_004c3211 mode 0x31 弹簧朝目标 (a = 1 px/t², 无阻尼).
       age%4==0: 积分一步 (只有这时动) + 生成一粒风 (FUN_004da114, 在控制体 x/y, z 0, mode 0x41: vz = 3|4 px/t 匀速上升);
       age%30==0 且 age>10: 对目标发 -200 (第 0 目标的控制体另播 0xbd);
       age%66==0 且 age<120 且是第 0 目标: 播 0xdc (age 0 / 66);
       age>120: 发 -210, 自毁.
  风粒 think FUN_004da114: seq = 656ed8[min(z/16, 7)] (ef 295, 每档 3 帧循环, 越高帧号越小), z > 128 自毁.
  -200: 该目标 FUN_004c4f20 + 受击 6557f0[目标朝向] + ef010 刺爆 655c10[施法者朝向] + 星爆 655b18 (et00 帧 14,15).
  -210: 该目标飘字, +0x7a ++, +0x78 --.   -20: +0x7a --.
  0x1e: 0x78/0x7a 都 0 → 0x28 渐亮 → 自毁.
hook 招式 (FUN_004df363 = 130, FUN_004e11c1 = 150, FUN_004e1246 = 151): -100 时施法者改挂循环 seq
  (130: 6604b0[朝向]; 150/151: 662364[朝向]); -210 时施法者清 0x20000 (seq 停在当前帧), 150/151 另置 0x10000 (回待机).
实录校准 (wine/captures/en7_t3_F10564.log, 逐 tick 吻合): 控制体在 -100 当 tick 出生、下一 tick 首次 think (age 0);
  风粒由控制体 think 生成, 出生当 tick 就 think (首帧 z 已 +3/4, 寿命 32/42 tick); -200 于 +47/77/107/137, -210 于 +137,
  渐亮起点/施法者回待机均与实录一致.
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _dir, _c3211, _motion, _getz
from core.anim_engine.bytecode import tuple_to_bytecode

WIND = 295
WIND_SEQS = [[('fm', WIND, f, 1), ('fm', WIND, f + 1, 1), ('fm', WIND, f + 2, 1), ('loop',)]
             for f in (18, 15, 12, 9, 6, 3, 0, 0)]                                       # 656ed8[0..7]
SFX_HIT, SFX_WIND = 0xbd, 0xdc
LIFE = 0x78


def _particle_think(e, eng) -> None:
    """FUN_004da114."""
    ud = e.user_data
    if 'wind' not in ud:
        return
    idx = min((_getz(e) >> 16) >> 4, 7)
    if ud['cur'] != idx:
        ud['cur'] = idx
        eng.attach_seq(e, tuple_to_bytecode(WIND_SEQS[idx]))
    _c3211(e)
    if (_getz(e) >> 16) > 0x80:
        eng.destroy(e)


def _ctrl_think(e, eng) -> None:
    """FUN_004da1d8."""
    ud = e.user_data
    if 'storm' not in ud:
        return
    sp: Storm = ud['spell']
    b = sp.battle
    age, v = ud['age'], ud['victim']
    first = v is sp.targets[0]
    if age % 4 == 0:
        _c3211(e)
        p = fx(b, _particle_think, e.x, e.y, 0, None, atlas=WIND, frame=WIND_SEQS[0][0][2], wind=True, cur=-1,
               **_motion(m=0x41, vz=(3 + (_rand(b) & 1)) * FP, tz=0x3e8 * FP))
        _particle_think(p, eng)                                 # 实录: 风粒出生当 tick 就 think (首帧 z 已 +3/4)
    if age % 30 == 0 and age > 10:
        sp.on_hit(v)
        if first:
            _sfx(b, SFX_HIT)
    if age % 66 == 0 and age < LIFE and first:
        _sfx(b, SFX_WIND)
    if age > LIFE:
        eng.destroy(e)
        sp.on_ctrl_done(v)
        return
    ud['age'] = age + 1


class Storm(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.fired = False

    def on_cast_impact(self) -> None:
        """-100: FUN_004da35f × 目标数."""
        self.fired = True
        b = self.battle
        for v in self.targets:
            x, y = _pos(v)
            sx = 1 if _rand(b) & 1 else -1
            ox = sx * (0x10 + (_rand(b) & 0xf))
            sy = 1 if _rand(b) & 1 else -1
            oy = sy * (0xc + _rand(b) % 12)
            e = fx(b, _ctrl_think, x + ox * FP, y + oy * FP, 0, None, atlas=WIND, frame=0, storm=True, spell=self,
                   victim=v, age=0, **_motion(m=0x31, ax=FP, ay=FP, tx=x, ty=y))
            e.flags &= ~0x40                                    # 控制体不可见
            self.live += 1

    def on_hit(self, v) -> None:
        """-200."""
        from core.bosan_skills import _starburst
        if not v.alive:
            return
        self.hit(v)
        _starburst(self.battle, v)

    def on_ctrl_done(self, v) -> None:
        """-210."""
        self.live -= 1
        self.settle(v)

    def think(self) -> None:
        if self.fired and self.live == 0:
            self.fired = False
            self.finish()


class StormHook(Storm):
    """FUN_004df363 (130) / FUN_004e11c1 (150) / FUN_004e1246 (151): 施法者循环 seq."""
    LOOP_TABLE: list = []
    IDLE_AFTER = False

    def on_cast_impact(self) -> None:
        c = self.caster
        if c.entity is not None:
            self.battle.engine.attach_seq(c.entity, tuple_to_bytecode(self.LOOP_TABLE[_dir(c)]))
            c.cast_hold = True
        super().on_cast_impact()

    def _stop_loop(self) -> None:
        c = self.caster
        if c.entity is not None:
            c.entity.flags &= ~0x20000                          # 清 0x20000: seq 停
        if self.IDLE_AFTER:
            c.cast_hold = False                                 # 置 0x10000: 回待机

    def on_ctrl_done(self, v) -> None:
        self._stop_loop()
        super().on_ctrl_done(v)

    def finish(self) -> None:
        self._stop_loop()                                       # 保险: 没目标时也别让循环 seq 挂着
        super().finish()


class Storm130(StormHook):
    LOOP_TABLE = [[('fm', 119, f, 1) for f in range(b, b + 5)] + [('loop',)] for b in (1, 7, 13, 19)]       # 6604b0


class Storm150(StormHook):
    LOOP_TABLE = [[('fm', 132, b, 3), ('fm', 132, b + 1, 3), ('fm', 132, b + 2, 3), ('fm', 132, b + 3, 5),
                   ('fm', 132, b + 4, 8), ('loop',)] for b in (0, 7, 14, 21)]                            # 662364
    IDLE_AFTER = True


TEMPLATES = {0x4da489: Storm}
MOVES = {130: Storm130, 150: Storm150, 151: Storm150}
