"""模板 FUN_004d30e0 (3 招 异常 毒: 154 使用毒藥 / 166 使用毒藥 / 183 用毒魔法), reverse_engineering/enemy_spells_decomp.txt
+ scratchpad B_decomp (FUN_004d2dd1 / 4d2c99 / 4d2c1c). 演出 = 目标周围冒出 10 个毒泡 (e_toxic), 升到半空浮动, 一齐破裂溅出毒滴.

dispatcher: 渐暗 → 施法 seq → -100: 每目标 FUN_004d30b0 毒泡发生器 (+0x78 ++), 进 0x1e.
  0x1e: +0x78 == 0 且 +0x7a == 0 且受击标记全清 → 0x28 渐亮 → 自毁.
  -200: +0x78 -- (exe 无飘字; 这里在此刻做异常结算 Spell.settle).
  -250: 目标复位 + 受击 seq 6557f0[目标朝向] + ef010 刺爆 655c10[6418dc[目标朝向]].
发生器 FUN_004d2faa (-1 清 DAT_0086a75c): age 4,20,..,148 各一个毒泡 FUN_004d2ed4 (第 10 个打 0x40000), 再过 16+28t (age 192)
  → DAT_0086a75c = 1 (全部破裂), 自毁.
毒泡 FUN_004d2ed4: 目标 x-24+rand%48, y-4+rand%20, z 0; flags 0x41 (z 弹簧) 目标 z = 48+rand&7, vz 2, a 0; seq 656a14
  (e_toxic 8..15 各 1t) + 0xc3.  think FUN_004d2dd1: 0: seq 完 → 挂 656a68 (帧 0..7 各 2t 循环) → 10: 匀速上升,
  z > 48 → a = 0.1 (绕目标高度上下浮动) → 0x14: 等 DAT_0086a75c → (末泡) 0xc4 + -200 + -250; 6 滴毒滴, 自毁.
毒滴 FUN_004d2c99: 静帧 e_toxic 16+rand&7, flags 0x51 (x/z 弹簧, x 加速度 0, z 目标 0 加速度 0.25),
  vx = rand%3000/1000 - 1.5, vz = rand%3000/1000 - 1; think FUN_004d2c1c: age > 8 起每 t 闪烁, age > 24 自毁.
"""
from __future__ import annotations

from core.anim_engine.bytecode import tuple_to_bytecode
from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _c3211, _motion, _getz
from core.enemy_spells.b_common import react

E_TOXIC = 218
FORM_SEQ = [('fm', E_TOXIC, f, 1) for f in range(8, 16)] + [('exit',)]          # 656a14
FLOAT_SEQ = [('fm', E_TOXIC, f, 2) for f in range(8)] + [('loop',)]             # 656a68
SFX_BUBBLE, SFX_POP = 0xc3, 0xc4
BUBBLES = 10
FIRST_AGE, STEP, POP_WAIT = 4, 0x10, 0x1c


def _drop_think(e, eng) -> None:
    """FUN_004d2c1c."""
    ud = e.user_data
    if 'drop' not in ud:
        return
    _c3211(e)
    age = ud['age']
    if ud['state'] == 0:
        if age > 8:
            ud['state'] = 10
    else:
        e.flags ^= 0x40
        if age > 0x18:
            eng.destroy(e)
            return
    ud['age'] = age + 1


def _splash(b, e) -> None:
    """FUN_004d2c99: 6 滴毒滴."""
    for _ in range(6):
        vx = ((_rand(b) % 3000) << 16) // 1000 - 0x18000
        vz = ((_rand(b) % 3000) << 16) // 1000 - 0x10000
        d = fx(b, _drop_think, e.x, e.y, _getz(e), None, atlas=E_TOXIC, frame=0, drop=True, state=0, age=0,
               **_motion(m=0x51, tx=e.x, tz=0, vx=vx, vz=vz, az=0x4000))
        d.frame_idx = 0x10 + (_rand(b) & 7)


def _bubble_think(e, eng) -> None:
    """FUN_004d2dd1."""
    ud = e.user_data
    if 'bubble' not in ud:
        return
    sp: Poison = ud['spell']
    b = sp.battle
    st = ud['state']
    if st == 0:
        if not e.is_playing():
            eng.attach_seq(e, tuple_to_bytecode(FLOAT_SEQ))
            ud['state'] = 10
    elif st == 10:
        _c3211(e)
        if _getz(e) > 0x2fffff:
            ud['az'] = 0x1999
            ud['state'] = 0x14
    elif st == 0x14:
        _c3211(e)
        if sp.pop:
            if ud['last']:
                _sfx(b, SFX_POP)
                sp.on_pop(ud['victim'])                               # -200 + -250
            _splash(b, e)
            eng.destroy(e)


def _spawner_think(e, eng) -> None:
    """FUN_004d2faa."""
    ud = e.user_data
    if 'spawner' not in ud:
        return
    sp: Poison = ud['spell']
    b, v = sp.battle, ud['victim']
    age = ud['age']
    if ud['state'] == 0:
        if age == ud['next']:
            x, y = _pos(v)
            bx = x - 0x180000 + (_rand(b) % 0x30) * FP
            by = y - 0x40000 + (_rand(b) % 0x14) * FP
            tz = (_rand(b) & 7) * FP + 0x300000
            bub = fx(b, _bubble_think, bx, by, 0, FORM_SEQ, bubble=True, spell=sp, victim=v, state=0, last=False,
                     **_motion(m=0x41, tz=tz, vz=0x20000))
            _sfx(b, SFX_BUBBLE)
            ud['next'] += STEP
            ud['n'] += 1
            if ud['n'] == BUBBLES:
                bub.user_data['last'] = True
                ud['next'] += POP_WAIT
                ud['state'] = 10
    elif age == ud['next']:
        sp.pop = True
        eng.destroy(e)
        return
    ud['age'] = age + 1


class Poison(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.casting = False
        self.pop = False                                              # DAT_0086a75c

    def on_cast_impact(self) -> None:
        self.pop = False
        for v in self.targets:
            e = self.battle.engine.spawn(think_fn=_spawner_think)
            e.flags = 0x800 | 0x10000
            e.user_data.update(kind='enemy_spell_fx', projectile=True, spawner=True, spell=self, victim=v,
                               state=0, age=0, next=FIRST_AGE, n=0)
            self.live += 1
        self.casting = True

    def think(self) -> None:
        if self.casting and self.live == 0:
            self.casting = False
            self.finish()

    def on_pop(self, v) -> None:
        self.live -= 1
        self.settle(v)                                                # -200
        react(self, v)                                                # -250


TEMPLATES = {0x4d30e0: Poison}
