"""招式 26 用雷射射擊 = FUN_004e9c62, 27 使用霹靂雷射 = FUN_004ea6cc, 28 使用火炎噴射 = FUN_004eb0ac
(FUN_004eb0ac Ghidra 未建函数, 反编译见 reverse_engineering/enemy_moves_decomp_missing.txt).

三招共用施法 seq 66f828[朝向] (atlas 54, 每方向 6 帧各 3t, 然后 -100) 与 渐暗/渐亮 骨架.

26 雷射: -100 → FUN_004e9b95 枪口闪光: 施法者 (x, y, z+56) 朝向偏 8px, seq 66f890 (atlas 234 帧 24-27, 含播/停 264),
          播完 → -150 → FUN_004e9b16 控制实体 (寿命 0x80, 0x78++):
          出生播 0xdb (长音); 每 t 生 1 段光束 FUN_004e981e; age%20 == 0 → 播 0xbd + -250; age == 128 → 停 0xdb, -200.
     光束段 (think FUN_004e9725): 生在施法者 (x, y+600, z+656) 再朝向偏 (上下 32 / 左右 40 px), 速度 上下 ∓48 / 左右 ∓64 px/t
          (mode 0x31, a = 0 → 匀速), 静态图 atlas 234 帧 = 全局帧计数%4 + 16 (上下) / +20 (左右), 每 t 刷新;
          出生那 t 不动; 出屏 (屏幕坐标 x∉[-100, 740] 或 y∉[-100, 580]) 自毁 — 我们用 "离出生点 |dx|>800 或 |dy|>600" **近似**.
     -250: 全部目标 受击 6557f0[6418dc[施法者朝向]] + 刺爆 655c10[施法者朝向] + 碎屑 FUN_004e52de. -200: 全部飘字.
27 霹靂雷射: -100 → 0x1e: dispatcher age%16 == 0 时给下一个目标 FUN_004ea61d 发射器 (全发完 → 0x28).
     发射器 (FUN_004ea54f): 基角 = 6418dc[施法者朝向] 对应角 (背向目标: 下 0x8000 / 上 0 / 右 0x4000 / 左 0xc000);
          自身 age%4 == 0: 张角 += 0xccc, 发 2 枚导弹 (基角 ± 张角), 4 轮 = 8 枚后自毁.
     导弹 (FUN_004ea483 / think 004ea1c4): 生在施法者 (x, y, z+56), 速度 16 px 起, 播 0xe8;
          state 0: 每 t 朝目标角转 0x400 (走近的一侧), 速度 -2 px (≥1 px), 按角前进 (x += sin·v, y -= cos·v);
                   (角 - 目标角) mod 0x10000 ≤ 0x800 → 记下到目标的距离与 目标→自身 的角, 播 0xe7 → 10;
                   图 = atlas 317 帧 66f93c[角·24 >> 16] (24 向).
          state 10: 位置 = 目标 + 极坐标(角, 距离), 距离每 t -16 px; < 0 → 播 0xbf, -250 (源 = 目标), 自毁.
     -250: 受击 (转向施法者) + 刺爆 + 碎屑; 该目标命中计数 +1, 满 8 → 飘字, 0x78--.
28 火炎噴射: -100 → FUN_004eafe0 喷火控制实体 (0x78++): 角 = 施法者朝向 (上 0 / 下 0x8000 / 左 0xc000 / 右 0x4000),
          出生播 0xba; 每 t: age<6 或 age%3==0 → 在施法者 (x, y, z+56) 朝向偏 8px 生 1 团火 (FUN_004ead1e);
          角 += 0x147, |角 - 基角| > 0x1555 (±30°) 反向扫; age%32 == 0 → -250; age == 128 → 停 0xba, -200, 自毁.
     火团 (think FUN_004eaca2): 以出生点为心沿角外推 (mode 0x32 绝对环绕, 半径 rx = (age/3)·24, ry = (age/3)·18),
          seq 66f954 (atlas 305 帧 0-11 各 1t) 播完自毁.
     -250: 全部目标 受击 (转向施法者) + 刺爆 + et00 星爆 + 碎屑. -200: 全部飘字.
控制实体 / 发射器的 age 都按 "首次 think = 0" 计.
"""
from __future__ import annotations

import math

from core.enemy_spells.base import Spell, fx, FP, _pos, _sfx, _dir, _c3211, _motion, _i32
from core.enemy_spells._ecommon import hit_unit, static_fx, stop_sfx, angle_to, OPP

CAST = [[('fm', 54, d * 6 + k, 3) for k in range(6)] + [('jump', -100), ('exit',)] for d in range(4)]   # 66f828
DIR_OFF = ((0, -1), (0, 1), (-1, 0), (1, 0))
DIR_ANGLE = (0, 0x8000, 0xc000, 0x4000)

# ---------------- 26 雷射 ----------------
MUZZLE_SEQ = ([('fm', 234, 24, 3), ('sound', 264, 1041), ('fm', 234, 25, 3), ('fm', 234, 26, 3), ('fm', 234, 27, 3)]
              + [('fm', 234, 24 + k, 2) for _ in range(3) for k in range(4)] + [('sound', 264, 1042), ('exit',)])
LASER_ATLAS = 234
BEAM_VEL = ((0, -48), (0, 48), (-64, 0), (64, 0))
BEAM_OFF = ((0, -32), (0, 32), (-40, 0), (40, 0))
SFX_BEAM, SFX_BEAM_HIT = 0xdb, 0xbd
BEAM_LIFE = 0x80


def _muzzle_think(e, eng) -> None:
    """FUN_004e9b51: seq 完 → -150."""
    ud = e.user_data
    if 'muzzle' not in ud or e.is_playing():
        return
    ud['spell'].on_muzzle_done()
    eng.destroy(e)


def _beam_think(e, eng) -> None:
    """FUN_004e9725."""
    ud = e.user_data
    if 'beam' not in ud:
        return
    tick = eng._tick_id
    if ud['born'] == tick:
        return
    _c3211(e)
    e.frame_idx = tick % 4 + (0x10 if ud['d'] < 2 else 0x14)
    if abs(e.x - ud['x0']) > 800 * FP or abs(e.y - ud['y0']) > 600 * FP:
        eng.destroy(e)


class LaserShot(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.ctrl = None
        self.launched = False

    def cast_seq(self, d):
        return CAST[d]

    def on_cast_impact(self) -> None:
        """-100: FUN_004e9b95."""
        self.launched = True
        c = self.caster
        x, y = _pos(c)
        dx, dy = DIR_OFF[_dir(c)]
        fx(self.battle, _muzzle_think, x + dx * 8 * FP, y + dy * 8 * FP, 56 * FP, MUZZLE_SEQ, muzzle=True, spell=self)
        self.live += 1

    def on_muzzle_done(self) -> None:
        """-150: FUN_004e9b16."""
        self.live -= 1
        self.ctrl = 0
        _sfx(self.battle, SFX_BEAM)

    def spawn_beam(self) -> None:
        """FUN_004e981e."""
        b, c = self.battle, self.caster
        d = _dir(c)
        x, y = _pos(c)
        ox, oy = BEAM_OFF[d]
        vx, vy = BEAM_VEL[d]
        x, y = x + ox * FP, y + 600 * FP + oy * FP
        tick = b.engine._tick_id
        static_fx(b, _beam_think, x, y, 656 * FP, LASER_ATLAS, tick % 4 + (0x10 if d < 2 else 0x14), beam=True, d=d,
                  born=tick, x0=x, y0=y, **_motion(m=0x31, vx=vx * FP, vy=vy * FP))

    def think(self) -> None:
        if self.ctrl is not None:
            age = self.ctrl
            self.ctrl += 1
            self.spawn_beam()
            if age % 20 == 0:
                _sfx(self.battle, SFX_BEAM_HIT)
                for v in self.targets:
                    hit_unit(self, v, face_caster=True, chiri=True)
            if age == BEAM_LIFE:
                stop_sfx(self.battle, SFX_BEAM)
                self.ctrl = None
                for v in self.targets:
                    self.settle(v)
        if self.launched and self.ctrl is None and self.live == 0 and not self._finishing:
            self.finish()


# ---------------- 27 霹靂雷射 ----------------
MISSILE_ATLAS = 317
MISSILE_FRAMES = (6, 7, 8, 9, 10, 11, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 0, 1, 2, 3, 4, 5)     # 66f93c
SFX_LAUNCH, SFX_LOCK, SFX_MISSILE_HIT = 0xe8, 0xe7, 0xbf


def _fsin(a: int) -> float:
    return math.sin((a & 0xffff) / 65536 * 2 * math.pi)


def _fcos(a: int) -> float:
    return math.cos((a & 0xffff) / 65536 * 2 * math.pi)


def _missile_think(e, eng) -> None:
    """FUN_004ea1c4."""
    ud = e.user_data
    if 'missile' not in ud:
        return
    sp: HomingLaser = ud['spell']
    tx, ty = ud['tx'], ud['ty']
    if ud['st'] == 0:
        ta = angle_to(tx - e.x, ty - e.y)
        a = ud['a']
        if a < ta:
            a = (a + 0x400) & 0xffff if ta - a < 0x8001 else (a + 0xfc00) & 0xffff
        else:
            a = (a + 0xfc00) & 0xffff if a - ta < 0x8001 else (a + 0x400) & 0xffff
        ud['a'] = a
        ud['r'] = max(0x10000, ud['r'] - 0x20000)
        e.x = _i32(e.x + int(_fsin(a) * ud['r']))
        e.y = _i32(e.y - int(_fcos(a) * ud['r']))
        if ((a - ta) + 0x10000) & 0xffff < 0x801:
            ud['r'] = int(math.hypot(e.x - tx, e.y - ty))
            ud['a'] = angle_to(e.x - tx, e.y - ty)
            ud['st'] = 10
            _sfx(sp.battle, SFX_LOCK)
        e.frame_idx = MISSILE_FRAMES[((a & 0xffff) * 0x18) >> 16]
    else:
        a, r = ud['a'], ud['r']
        e.x = _i32(tx + int(_fsin(a) * r))
        e.y = _i32(ty - int(_fcos(a) * r))
        ud['r'] = r - 16 * FP
        if ud['r'] < 0:
            _sfx(sp.battle, SFX_MISSILE_HIT)
            sp.on_missile_hit(ud['victim'])
            eng.destroy(e)


def _launcher_think(e, eng) -> None:
    """FUN_004ea54f."""
    ud = e.user_data
    if 'launcher' not in ud:
        return
    age = ud['age']
    ud['age'] += 1
    if age % 4:
        return
    sp: HomingLaser = ud['spell']
    ud['spread'] += 0xccc
    for a in (ud['base'] + ud['spread'], ud['base'] - ud['spread']):
        sp.spawn_missile(ud['victim'], a)
    ud['n'] += 1
    if ud['n'] == 4:
        eng.destroy(e)


class HomingLaser(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.casting = False
        self.spawned = 0
        self.hits: dict[int, int] = {}

    def cast_seq(self, d):
        return CAST[d]

    def on_cast_impact(self) -> None:
        self.casting = True
        self.t0 = self.age

    def spawn_missile(self, v, ang: int) -> None:
        """FUN_004ea483."""
        b = self.battle
        x, y = _pos(self.caster)
        tx, ty = _pos(v)
        static_fx(b, _missile_think, x, y, 56 * FP, MISSILE_ATLAS, MISSILE_FRAMES[(((ang + 0x10000) & 0xffff) * 0x18) >> 16],
                  missile=True, spell=self, victim=v, tx=tx, ty=ty, a=(ang + 0x10000) & 0xffff, r=0x100000, st=0)
        _sfx(b, SFX_LAUNCH)

    def on_missile_hit(self, v) -> None:
        """-250."""
        hit_unit(self, v, face_caster=True, chiri=True)
        n = self.hits.get(id(v), 0) + 1
        self.hits[id(v)] = n
        if n == 8:
            self.settle(v)
            self.live -= 1

    def think(self) -> None:
        if not self.casting:
            return
        if self.spawned < len(self.targets):
            if (self.age - self.t0) % 16 == 0:
                v = self.targets[self.spawned]
                self.spawned += 1
                self.live += 1
                base = DIR_ANGLE[OPP[_dir(self.caster)]]
                e = self.battle.engine.spawn(think_fn=_launcher_think)       # 不可见控制实体
                e.user_data.update(kind='enemy_spell_ctrl', launcher=True, spell=self, victim=v, base=base, spread=0,
                                   n=0, age=0)
            return
        if self.live == 0 and not self._finishing:
            self.casting = False
            self.finish()


# ---------------- 28 火炎噴射 ----------------
FLAME_SEQ = [('fm', 305, f, 1) for f in range(10)] + [('fm', 305, 11, 1), ('fm', 305, 10, 1), ('exit',)]   # 66f954
SFX_FLAME = 0xba
FLAME_LIFE = 0x80


def _flame_think(e, eng) -> None:
    """FUN_004eaca2."""
    ud = e.user_data
    if 'flame' not in ud:
        return
    k = ud['age'] // 3
    ud['age'] += 1
    ud['rx'], ud['ry'] = k * 0x18, k * 0x12
    _c3211(e)
    if not e.is_playing():
        eng.destroy(e)


class FlameJet(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.ctrl = None
        self.launched = False

    def cast_seq(self, d):
        return CAST[d]

    def on_cast_impact(self) -> None:
        """FUN_004eafe0."""
        self.launched = True
        self.base = self.phase = DIR_ANGLE[_dir(self.caster)]
        self.omega = 0x147
        self.ctrl = 0
        _sfx(self.battle, SFX_FLAME)

    def think(self) -> None:
        if self.ctrl is not None:
            age = self.ctrl
            self.ctrl += 1
            b, c = self.battle, self.caster
            if age < 6 or age % 3 == 0:
                x, y = _pos(c)
                dx, dy = DIR_OFF[_dir(c)]
                x, y = x + dx * 8 * FP, y + dy * 8 * FP
                fx(b, _flame_think, x, y, 56 * FP, FLAME_SEQ, flame=True, age=0,
                   **_motion(m=0x32, tx=x, ty=y, px=self.phase, py=self.phase))
            self.phase += self.omega
            if abs(self.phase - self.base) > 0x1555:
                self.omega = -self.omega
            if age % 32 == 0:
                for v in self.targets:
                    hit_unit(self, v, face_caster=True, star=True, chiri=True)
            if age == FLAME_LIFE:
                stop_sfx(b, SFX_FLAME)
                for v in self.targets:
                    self.settle(v)
                self.ctrl = None
        if self.launched and self.ctrl is None and not self._finishing:
            self.finish()


MOVES = {26: LaserShot, 27: HomingLaser, 28: FlameJet}
