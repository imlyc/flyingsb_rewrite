"""205 發射弓箭 (火箭, 落点 AOE): dispatcher FUN_004e3aa0 (custom), reverse_engineering/enemy_spells_decomp.txt, 2026-10-26.

dispatcher:
  case 0   → 10 (**无渐暗**, 只空一拍); 10: 施法者挂 668f0c[朝向] (同 203 放箭的拉弓 seq) → 0x1e.
  -100     FUN_004e3971(瞄准格): 火箭生在施法者 (x, y, z+48), 目标 = 瞄准格中心 (z 48), mode 0x31 匀速 24/32 px/t
           (只给朝向那一轴速度, 另一轴首步钳到), seq 6691cc[朝向] (eobj 3 帧各 2t), 播 200 (0xc8).
  箭 think LAB_004e390b: FUN_004cdbc2 两轴到 → 播 0xd6, 发 -200 再发 -250 (同步), 自毁.
  -200     大爆炸 FUN_004d0d7b(格 x + rand%12-6, 格 y+124, z 172 + (rand&15)-8, seq 655eac (图 292 帧 0-10), 完发 -0xd2).
  -250     每个目标: FUN_004c4f20 + 受击 6557f0[目标朝向] + 刺爆 655c10[施法者朝向] (x, y+400, z+448)
           + 小爆炸 FUN_004d0d7b(x + rand%12-6, y+24, z 72 + (rand&15)-8, seq 655e58 (图 291 帧 0-7), 完发 -0x104).
  -0xd2    (大爆炸播完) 全部目标飘字.     -0x104 小爆炸计数 --.
  0x1e     箭/爆炸/飘字计数归零 + 全部受击播完 → 0x28 (下一 tick) 自毁 (不渐亮).
实录校准 (wine/captures/en205_t161_F3538.log): 箭 (出生当 tick 不 think, 10 t)、大/小爆炸 (+44, 49/35 t)、刺爆、-0xd2 飘字 (+93)
  逐 tick 吻合; 0x28 多停的一拍已补 (_finish_tick), 收尾 = 末位 -20 后第 3 tick 施法者回待机, 吻合.
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _cdbc2, _motion, _dir, _unit_z
from core.enemy_spells.m203 import CAST_203, SPARK, reset_hit
from core.sprites.base import TILE_W, TILE_H

FIRE_ARROW = [  # @0x6691cc
    [('fm', 330, 3, 2), ('fm', 330, 4, 2), ('fm', 330, 5, 2), ('exit',)],
    [('fm', 330, 0, 2), ('fm', 330, 1, 2), ('fm', 330, 2, 2), ('exit',)],
    [('fm', 330, 6, 2), ('fm', 330, 7, 2), ('fm', 330, 8, 2), ('exit',)],
    [('fm', 330, 9, 2), ('fm', 330, 10, 2), ('fm', 330, 11, 2), ('exit',)],
]
BIG_BOOM = [('fm', 292, 0, 1), ('fm', 292, 1, 1), ('fm', 292, 2, 2), ('fm', 292, 3, 2), ('fm', 292, 4, 2), ('fm', 292, 3, 2), ('fm', 292, 5, 3), ('fm', 292, 6, 4), ('fm', 292, 7, 5), ('fm', 292, 8, 5), ('fm', 292, 9, 5), ('fm', 292, 10, 5), ('exit',)]  # @0x655eac
SMALL_BOOM = [('fm', 291, 0, 1), ('fm', 291, 1, 1), ('fm', 291, 2, 3), ('fm', 291, 3, 3), ('fm', 291, 4, 3), ('fm', 291, 5, 4), ('fm', 291, 6, 6), ('fm', 291, 7, 6), ('exit',)]  # @0x655e58
SFX_SHOOT, SFX_LAND = 200, 0xd6
SPEED = (24, 32)


def end_fx(battle, cb, x, y, z, seq):
    """FUN_004d0d7b: 特效, seq 播完 → cb() (= 发信号给 dispatcher), 自毁."""
    def think(e, eng):
        if 'end_fx' in e.user_data and not e.is_playing():
            cb()
            eng.destroy(e)
    return fx(battle, think, x, y, z, seq, end_fx=True)


def tile_center(tx: int, ty: int) -> tuple[int, int]:
    return (tx * TILE_W + TILE_W // 2) * FP, (ty * TILE_H + TILE_H // 2) * FP


def _arrow_think(e, eng) -> None:
    ud = e.user_data
    if 'fire_arrow' not in ud:
        return
    _cdbc2(e)
    if ud['m'] & 0x30:
        return
    sp: FireArrow = ud['spell']
    _sfx(sp.battle, SFX_LAND)
    sp.live -= 1
    sp.on_land(ud['tx'], ud['ty'])
    eng.destroy(e)


class FireArrow(Spell):
    DIM = False
    FADE_IN = False

    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.fired = False

    def cast_seq(self, d: int):
        return CAST_203[d]

    def on_cast_impact(self) -> None:
        """-100: FUN_004e3971."""
        if self.fired:
            return
        self.fired = True
        b, c = self.battle, self.caster
        d = _dir(c)
        cur = getattr(c, 'pending_attack_cursor', None) or (c.x, c.y)
        tx, ty = tile_center(*cur)
        x, y = _pos(c)
        vud, vlr = SPEED
        vx, vy = ((0, -vud), (0, vud), (-vlr, 0), (vlr, 0))[d]
        fx(b, _arrow_think, x, y, _unit_z(c) + 48 * FP, FIRE_ARROW[d], fire_arrow=True, spell=self,
           **_motion(m=0x31, vx=vx * FP, vy=vy * FP, tx=tx, ty=ty, tz=48 * FP))
        self.live += 1
        _sfx(b, SFX_SHOOT)

    def on_land(self, tx: int, ty: int) -> None:
        b = self.battle
        # -200: 大爆炸 (rand 顺序: z 抖动 → x 抖动)
        jz = ((_rand(b) & 15) - 8) * FP
        jx = (_rand(b) % 12 - 6) * FP
        self.live += 1
        end_fx(b, self._big_done, tx + jx, ty + 124 * FP, 172 * FP + jz, BIG_BOOM)
        # -250: 全部目标受击 + 刺爆 + 小爆炸
        from core.pao_skills import hit_pos
        d = _dir(self.caster)
        for v in self.targets:
            reset_hit(v)
            x, y = hit_pos(v)
            fx(b, None, x, y + 400 * FP, 448 * FP, SPARK[d])
            jz = ((_rand(b) & 15) - 8) * FP
            jx = (_rand(b) % 12 - 6) * FP
            self.live += 1
            end_fx(b, self._small_done, x + jx, y + 24 * FP, 72 * FP + jz, SMALL_BOOM)

    def _big_done(self) -> None:
        """-0xd2: 全部目标飘字."""
        self.live -= 1
        for v in self.targets:
            self.settle(v)
        self._check_end()

    def _small_done(self) -> None:
        self.live -= 1
        self._check_end()

    def _check_end(self) -> None:
        if self.live <= 0 and not self._finishing:
            self.finish()
            self._held = False

    def _finish_tick(self) -> None:
        """exe 0x1e 计数归零 → 0x28 (停一拍) 才自毁: 比框架多 1 tick (实录 en205_t161: 末位 -20 后第 3 tick 回待机)."""
        if self._fade is None and not self._held and not self.busy():
            self._held = True
            return
        super()._finish_tick()


MOVES = {205: FireArrow}
