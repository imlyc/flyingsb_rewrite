"""模板 FUN_004d7c8e (5 招: 42 用冰摧毀, 65 使出冰衝突, 77 召來火牆, 114 發射冰塊 (hook), 134 使用得利冰),
reverse_engineering/enemy_spells_decomp.txt (+ 4d77e6 / 4dda82 补反编译).  = 玩家 紫河 流星冰鑽 (core.jah_skills 0x39).

dispatcher: 渐暗 → 施法 seq → -100: 每目标一个发射器 FUN_004d7c45 (think FUN_004d7b6b), +0x78 计数.
  发射器: age 4 起 8 颗冰钻 (间隔 (8-n)*4: 4,32,56,76,92,104,112,116), 第 8 颗标 0x40000 (末颗), 自毁.
  冰钻 FUN_004d788d: 施法者 (x-8+rand&15, y-2+rand&7, z+0x500000 ≈ 80px), 目标 = 目标 (x, y, z 48px), flags 0x71
    (FUN_004cdbc2 三轴匀速, 加速 0): 施法者朝向上/下 → y 轴 ∓24 px/t 主轴, 左/右 → x 轴 ∓32 px/t, 其他轴 = 位移/(主轴步数) (C 截断);
    seq 656c18 (上下: ds_ice 3,2,1,0,5,6,7,4,8 各 1t) / 656bbc (左右: ...,4,11); 0xce.
  冰钻 think FUN_004d77e6: state 0 等 seq 播完 → state 10 每 t FUN_004cdbc2, 三轴都到 → -250; 末颗再 -200; 自毁.
  -250: 0xbd + 受击 6557f0[目标朝向] + 655c10[6418dc[目标朝向]] 刺爆 + 655b18 红刺 (= Spell.hit fx='both').
  -200: 飘字, +0x78--.  0x1e: 计数归零 + 飘字/受击完 → 0x28 渐亮.
114 發射冰塊 (FUN_004ddebb): 只换掉 -100 → 每目标发射器 FUN_004dde72/4ddd98 (同时序), 冰钻 FUN_004dda82:
  从施法者原位 z+48 出发 (无随机), 按朝向偏移: 上 y-9 / 下 y+12 / 左 x-20,y+1 / 右 x+20,y+1; 其余同上.
近似: 冰钻起始高 LAB_004fffff_1 按 0x500000 (80px) 取 (同玩家版).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _dir, _cdbc2, _motion, _getz, _unit_z

DS_ICE = 232
DRILL_SEQ_UD = [('fm', DS_ICE, f, 1) for f in (3, 2, 1, 0, 5, 6, 7, 4, 8)] + [('exit',)]      # 656c18
DRILL_SEQ_LR = [('fm', DS_ICE, f, 1) for f in (3, 2, 1, 0, 5, 6, 7, 4, 11)] + [('exit',)]     # 656bbc
SFX_DRILL, SFX_HIT = 0xce, 0xbd
MAJOR_V = (-24 * FP, 24 * FP, -32 * FP, 32 * FP)        # 上 下 左 右 (主轴速度)


def _cdiv(a: int, b: int) -> int:
    """C 整除 (向 0 截断); 除数 0 按 1 (exe 会除零, 实际不会出现)."""
    if b == 0:
        return a
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def spawn_drill(sp: Spell, victim, x: int, y: int, z: int, d: int, last: bool):
    """FUN_004d788d / 4dda82 后半: 主轴定速, 其他轴按步数均分."""
    tx, ty = _pos(victim)
    tz = 0x300000
    mv = _motion(m=0x71, tx=tx, ty=ty, tz=tz)
    if d < 2:
        mv['vy'] = MAJOR_V[d]
        n = _cdiv(ty - y, mv['vy']) or 1
        mv['vx'] = _cdiv(tx - x, n)
        mv['vz'] = _cdiv(tz - z, n)
    else:
        mv['vx'] = MAJOR_V[d]
        n = _cdiv(tx - x, mv['vx']) or 1
        mv['vy'] = _cdiv(ty - y, n)
        mv['vz'] = _cdiv(tz - z, n)
    e = fx(sp.battle, _drill_think, x, y, z, DRILL_SEQ_UD if d < 2 else DRILL_SEQ_LR,
           drill=True, spell=sp, victim=victim, last=last, st=0, **mv)
    _sfx(sp.battle, SFX_DRILL)
    sp.live += 1
    return e


def _drill_think(e, eng) -> None:
    """FUN_004d77e6."""
    ud = e.user_data
    if 'drill' not in ud:
        return
    sp = ud['spell']
    if ud['st'] == 0:
        if not e.is_playing():
            ud['st'] = 10
        return
    if _cdbc2(e):
        sp.on_drill_hit(ud['victim'], ud['last'])
        eng.destroy(e)


def _launcher_think(e, eng) -> None:
    """FUN_004d7b6b / 4ddd98."""
    ud = e.user_data
    if 'launcher' not in ud:
        return
    if ud['age'] == ud['next']:
        ud['n'] += 1
        ud['spell'].launch(ud['victim'], last=ud['n'] > 7)
        ud['next'] += max((8 - ud['n']) * 4, 1)
        if ud['n'] > 7:
            eng.destroy(e)
            return
    ud['age'] += 1


class IceDrill(Spell):
    def on_cast_impact(self) -> None:
        for v in self.targets:
            e = self.battle.engine.spawn(think_fn=_launcher_think)
            e.flags = 0x800 | 0x10000
            e.user_data.update(kind='enemy_drill_launcher', projectile=True, launcher=True, spell=self, victim=v,
                               age=0, next=4, n=0)
            self.live += 1           # +0x78 (末颗 -200 减)
        if not self.targets:
            self.finish()

    def launch(self, v, last: bool) -> None:
        """FUN_004d788d: 施法者身前随机."""
        c, b = self.caster, self.battle
        cx, cy = _pos(c)
        x = cx - 8 * FP + (_rand(b) & 15) * FP
        y = cy - 2 * FP + (_rand(b) & 7) * FP
        spawn_drill(self, v, x, y, _unit_z(c) + 0x500000, _dir(c), last)

    def on_drill_hit(self, v, last: bool) -> None:
        self.live -= 1
        _sfx(self.battle, SFX_HIT)
        self.hit(v, fx='both')                          # -250
        if last:
            self.live -= 1
            self.settle(v)                              # -200
        if self.live <= 0:
            self.finish()


class IceShot(IceDrill):
    """114 發射冰塊 (FUN_004ddebb hook): 冰钻 FUN_004dda82 从施法者原位按朝向偏移出发."""
    OFFS = ((0, -9), (0, 12), (-20, 1), (20, 1))

    def launch(self, v, last: bool) -> None:
        c = self.caster
        d = _dir(c)
        cx, cy = _pos(c)
        ox, oy = self.OFFS[d]
        spawn_drill(self, v, cx + ox * FP, cy + oy * FP, _unit_z(c) + 0x300000, d, last)


TEMPLATES = {0x4d7c8e: IceDrill}
MOVES = {114: IceShot}
