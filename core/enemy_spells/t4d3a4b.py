"""模板 FUN_004d3a4b (3 招 异常 咀咒类: 14 使用可斯攻擊 / 96 使用哥姿 / 169 使用哥姿), reverse_engineering/enemy_spells_decomp.txt
+ scratchpad B_decomp (FUN_004d3593). 演出 = e_curse 碎块从 600px 高空落到目标身上越堆越高, 全部堆完后向四周炸开.

dispatcher: -1 (生成时, 渐暗前) 播 0xb4, 清 DAT_0086a760.  渐暗 → 施法 seq → -100: 每目标 FUN_004d3a28 (+0x78 ++), 进 0x1e.
  -200 (碎块堆完): +0x7c ++, == 目标数 → DAT_0086a760 = 1 (全部炸开).
  -250: (首目标播 0xb5) 目标复位 + 受击 seq 6557f0[目标朝向] + ef010 刺爆 655c10[6418dc[目标朝向]].
  -0x104: +0x78 --.  0x1e: 计数清零 + 受击完 → 0x28 渐亮 → 自毁.  -2 (销毁): 停 0xb5.
发生器 FUN_004d395b: 首 tick (首目标) 播 0xc2; 偶数 age 生成碎块 FUN_004d3838(目标, age); age > 63 → (首目标) 停 0xc2,
  末块打 0x40000, 自毁 (共 33 块).
碎块 FUN_004d3838: c = min(age, 63), x = 目标 x + rand%(80-c) - (80-c)/2, y = 目标 y + 1, z = 600, flags 0x41 (z 弹簧目标 0,
  加速度 0), vz = -16, 地面 = c·4/3 + 8 (越晚越高 = 堆起来), e_curse 静帧 rand%13.
碎块 FUN_004d3593: 0: 落到地面 → 加 x 轴 (vx ±0.25), z = 地面+1, 弹簧目标 = 地面, vz 16, a 2 → 10: 弹一下落回地面 →
  (末块) -200 → 0x14: 等 DAT_0086a760 → 绕当前位置环 (flags 0x32, 随机相位, 半径 0) + (末块) -250 →
  0x1e: 半径 x +32 / y +24 每 t, > 400 → (末块) -0x104, 自毁.
异常结算 (Spell.settle) 放在 -250 (炸开) 时刻 (exe 的 -200 是 "堆完" 的全局计数, 不针对目标).
近似: 碎块出生 tick 即 think (发生器之后的池序).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _c3211, _motion, _getz, _set_z
from core.enemy_spells.b_common import react
from core.jet_skills import _sfx_stop

E_CURSE = 222
SFX_START, SFX_HIT, SFX_RAIN = 0xb4, 0xb5, 0xc2
LAST_AGE = 0x3f


def _chunk_think(e, eng) -> None:
    """FUN_004d3593."""
    ud = e.user_data
    if 'chunk' not in ud:
        return
    sp: Curse = ud['spell']
    b = sp.battle
    st = ud['state']
    if st == 0:
        _c3211(e)
        if _getz(e) <= ud['rz']:
            ud['m'] |= 0x10
            ud['vx'] = ((_rand(b) % 1000) << 16) // 2000 - 0x4000
            _set_z(e, ud['rz'] + FP)
            ud.update(tz=ud['rz'], vz=0x100000, az=0x20000, state=10)
    elif st == 10:
        _c3211(e)
        if _getz(e) <= ud['rz']:
            if ud['last']:
                sp.on_piled()                                         # -200
            ud['state'] = 0x14
    elif st == 0x14:
        if sp.burst:
            ph = (_rand(b) & 0xfff) << 4
            ud.update(m=0x32, tx=e.x, ty=e.y, px=ph, py=ph, rx=0, ry=0, state=0x1e)
            if ud['last']:
                sp.on_burst(ud['victim'])                             # -250
    elif st == 0x1e:
        _c3211(e)
        ud['rx'] += 0x20
        ud['ry'] += 0x18
        if ud['rx'] > 400:
            if ud['last']:
                sp.on_gone()                                          # -0x104
            eng.destroy(e)


def _spawn_chunk(sp, v, age: int):
    """FUN_004d3838."""
    b = sp.battle
    c = min(age, 0x3f)
    w = 0x50 - c
    x, y = _pos(v)
    cx = x + (_rand(b) % w) * FP - (w * FP) // 2
    e = fx(b, _chunk_think, cx, y + FP, 0x2580000, None, atlas=E_CURSE, frame=0, chunk=True, spell=sp, victim=v,
           state=0, last=False, **_motion(m=0x41, tz=0, vz=-0x100000, rz=(c << 18) // 3 + 0x80000))
    e.frame_idx = _rand(b) % 13
    _chunk_think(e, b.engine)
    return e


def _spawner_think(e, eng) -> None:
    """FUN_004d395b."""
    ud = e.user_data
    if 'spawner' not in ud:
        return
    sp: Curse = ud['spell']
    if not ud['started']:
        if ud['first']:
            _sfx(sp.battle, SFX_RAIN)
        ud['started'] = True
    age = ud['age']
    if age % 2 == 0:
        ud['chunk'] = _spawn_chunk(sp, ud['victim'], age)
    if age > LAST_AGE:
        if ud['first']:
            _sfx_stop(sp.battle, SFX_RAIN)
        ud['chunk'].user_data['last'] = True
        eng.destroy(e)
        return
    ud['age'] = age + 1


class Curse(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.casting = False
        self.burst = False                                            # DAT_0086a760
        self.piled = 0                                                # +0x7c

    def start(self) -> None:
        _sfx(self.battle, SFX_START)                                  # -1
        super().start()

    def on_cast_impact(self) -> None:
        for i, v in enumerate(self.targets):
            e = self.battle.engine.spawn(think_fn=_spawner_think)
            e.flags = 0x800 | 0x10000
            e.user_data.update(kind='enemy_spell_fx', projectile=True, spawner=True, spell=self, victim=v,
                               first=(i == 0), started=False, age=0)
            self.live += 1
        self.casting = True

    def think(self) -> None:
        if self.casting and self.live == 0:
            self.casting = False
            self.finish()

    def on_piled(self) -> None:
        """-200."""
        self.piled += 1
        if self.piled == len(self.targets):
            self.burst = True

    def on_burst(self, v) -> None:
        """-250."""
        if self.targets and v is self.targets[0]:
            _sfx(self.battle, SFX_HIT)
        react(self, v)
        self.settle(v)

    def on_gone(self) -> None:
        """-0x104."""
        self.live -= 1

    def _end(self) -> None:
        _sfx_stop(self.battle, SFX_HIT)                               # -2
        super()._end()


TEMPLATES = {0x4d3a4b: Curse}
