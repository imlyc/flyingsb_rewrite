"""招式 37 施出大帝之踢 = FUN_004ec605, 38 使出上帝之掌 = FUN_004ecc0b, 39 使出神之拳 = FUN_004ed2b3.

三招 dispatcher 同骨架: 0 渐暗 → 10 施法者挂 seq 670624 (= 只等 12t 再 -100, 不清 0x10000 → 施法者保持待机)
  -100: 0x78 = 0 → 0x1e; 0x1e: dispatcher age%8 == 0 时给下一个目标生 1 个子实体 (0x78++), 全生完 → 0x28.
  0x28: 子实体全收 + 飘字/结算计数 + 受击 seq 全完 → 0x32 渐亮 → 自毁.

37 大帝之踢 (FUN_004ec54f / think 004ec44f): 脚 = 静态图 atlas 313 帧 0, 在目标 (x, y+1, z=600), z 匀速 -64 px/t:
   落地 (z<1) → 播 0xec, -200 (源 = 目标): 受击 6557f0[目标朝向] + 飘字 + 刺爆 655c10[施法者朝向] + et00 星爆;
   FUN_004d8c81(5, 5, 8) 地震; 然后等 DAT_0086a77c (dispatcher 在飘字计数 0x7a 回到 0 时置 1) → z 匀速 +64 升回 600
   → -250 (源 = 自己: dispatcher 0x78--) 自毁.
38 上帝之掌 (FUN_004ecba0 / think 004ecb25): 特效在目标 (x, y, z), seq 670634 (atlas 319 帧 0-5 各 1t) + 播 0xf6;
   age == 2 → -250: 受击 6557f0[目标朝向] + 刺爆 655c10[施法者朝向]; seq 完 → -200 (0x7a++, **不飘字**) + -300 (0x7c++).
   类别 1 异常: 结算只判定状态 (exe 此处不调 FUN_004d05d8, 不中也不出 MISS 字).
39 神之拳 (FUN_004ed227 / think 004ed05e): 拳 seq 670674 (atlas 314 帧 0-2 各 3t 循环), 在目标 (x, y+1, z=600), vz -32:
   0:    z ≤ 192 → az = -5 px/t² (弹簧朝 tz=0 → 减速), 播 0xce → 10.
   10:   vz > -2 px → -150 (dispatcher 0x7c++, 满目标数置 DAT_0086a780), vz = -2, az = 0 → 0x14.
   0x14: (不动) 等 DAT_0086a780 = 所有拳都悬停 → vz = -64 → 0x1e.
   0x1e: z<1 → 播 0xf6, -200 (源 = 目标): 受击 + 飘字 + 刺爆 + 星爆; 挂 seq 670694 (atlas 314 帧 3-15 各 1t), z = 0 → 0x28.
   0x28: seq 完 → -250 (0x78--) 自毁.
近似: 37 的 DAT_0086a77c 用 "已落地 ≥1 且 battle.float_pending == 0" 判定 (exe = 飘字计数回 0 的那一刻).
"""
from __future__ import annotations

from core.anim_engine.bytecode import tuple_to_bytecode
from core.enemy_spells.base import Spell, fx, FP, _pos, _sfx, _c3211, _motion, _getz, _set_z
from core.enemy_spells._ecommon import hit_unit, static_fx, shake

CAST = [('move', 0, 0, 0, 12), ('jump', -100), ('exit',)]          # 670624
PALM_SEQ = [('fm', 319, f, 1) for f in range(6)] + [('exit',)]     # 670634
FIST_SEQ = [('fm', 314, f, 3) for f in range(3)] + [('loop',)]     # 670674
FIST_HIT_SEQ = [('fm', 314, f, 1) for f in range(3, 16)] + [('exit',)]   # 670694
Z_TOP = 600
INTERVAL = 8


def _foot_think(e, eng) -> None:
    """FUN_004ec44f."""
    ud = e.user_data
    if 'foot' not in ud:
        return
    sp: GodKick = ud['spell']
    st = ud['st']
    if st == 0:
        _c3211(e)
        if _getz(e) < 1:
            _sfx(sp.battle, 0xec)
            sp.on_land(ud['victim'])
            shake(sp.battle, 5, 5, 8)
            _set_z(e, 0)
            ud['st'] = 10
    elif st == 10:
        if sp.flag:
            ud['tz'] = Z_TOP * FP
            ud['vz'] = -ud['vz']
            ud['st'] = 0x14
    elif st == 0x14:
        _c3211(e)
        if _getz(e) > Z_TOP * FP - 1:
            sp.live -= 1
            eng.destroy(e)


def _palm_think(e, eng) -> None:
    """FUN_004ecb25."""
    ud = e.user_data
    if 'palm' not in ud:
        return
    sp: GodPalm = ud['spell']
    ud['age'] += 1
    if ud['age'] == 2:
        hit_unit(sp, ud['victim'])
    if not e.is_playing():
        sp.on_palm_done(ud['victim'])
        eng.destroy(e)


def _fist_think(e, eng) -> None:
    """FUN_004ed05e."""
    ud = e.user_data
    if 'fist' not in ud:
        return
    sp: GodFist = ud['spell']
    st = ud['st']
    if st == 0:
        _c3211(e)
        if _getz(e) < 0xc00001:
            ud['az'] = -5 * FP
            ud['st'] = 10
            _sfx(sp.battle, 0xce)
    elif st == 10:
        _c3211(e)
        if ud['vz'] > -0x20001:
            sp.hovering += 1
            ud['vz'] = -2 * FP
            ud['az'] = 0
            ud['st'] = 0x14
    elif st == 0x14:
        if sp.hovering >= len(sp.targets):
            ud['vz'] = -64 * FP
            ud['st'] = 0x1e
    elif st == 0x1e:
        _c3211(e)
        if _getz(e) < 1:
            _sfx(sp.battle, 0xf6)
            sp.on_land(ud['victim'])
            eng.attach_seq(e, tuple_to_bytecode(FIST_HIT_SEQ))
            _set_z(e, 0)
            ud['st'] = 0x28
    elif st == 0x28:
        if not e.is_playing():
            sp.live -= 1
            eng.destroy(e)


class _GodBase(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.casting = False
        self.spawned = 0

    def cast_seq(self, d):
        return CAST

    def on_cast_impact(self) -> None:
        self.casting = True

    def spawn(self, v) -> None:
        raise NotImplementedError

    def think(self) -> None:
        if not self.casting:
            return
        if self.spawned < len(self.targets):
            if self.age % INTERVAL == 0:
                v = self.targets[self.spawned]
                self.spawned += 1
                self.live += 1
                self.spawn(v)
            return
        if self.live == 0 and not self._finishing:
            self.casting = False
            self.finish()


class GodKick(_GodBase):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.landed = 0
        self.flag = False

    def spawn(self, v) -> None:
        x, y = _pos(v)
        static_fx(self.battle, _foot_think, x, y + FP, Z_TOP * FP, 313, 0, foot=True, spell=self, victim=v, st=0,
                  **_motion(m=0x41, vz=-64 * FP, tz=0))

    def on_land(self, v) -> None:
        """-200."""
        hit_unit(self, v, star=True)
        self.settle(v)
        self.landed += 1

    def think(self) -> None:
        if self.landed and not self.flag and getattr(self.battle, 'float_pending', 0) == 0:
            self.flag = True
        super().think()


class GodPalm(_GodBase):
    def spawn(self, v) -> None:
        x, y = _pos(v)
        fx(self.battle, _palm_think, x, y, 0, PALM_SEQ, palm=True, spell=self, victim=v, age=0)
        _sfx(self.battle, 0xf6)

    def on_palm_done(self, v) -> None:
        """-200 / -300: 只判定异常, 不飘字."""
        from core import enemy_moves as EM
        self.live -= 1
        b, c = self.battle, self.caster
        if v.alive and self.m is not None:
            got = EM.resolve_status(b, c, v, self.m)
            b._log(f"{c.name} → {v.name}: " + (f"中了 {[hex(x) for x in got]}" if got else "异常未中"))


class GodFist(_GodBase):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.hovering = 0

    def spawn(self, v) -> None:
        x, y = _pos(v)
        fx(self.battle, _fist_think, x, y + FP, Z_TOP * FP, FIST_SEQ, fist=True, spell=self, victim=v, st=0,
           **_motion(m=0x41, vz=-32 * FP, tz=0))

    def on_land(self, v) -> None:
        """-200."""
        hit_unit(self, v, star=True)
        self.settle(v)


MOVES = {37: GodKick, 38: GodPalm, 39: GodFist}
