"""模板 FUN_004d194c (6 招 异常 睡眠类: 52 滑倒攻擊 / 81 使用斯里 / 111 滑倒攻擊 / 118 播放無趣卡通 / 179 用滑倒攻擊 /
223 使用滑倒攻擊), reverse_engineering/enemy_spells_decomp.txt + scratchpad B_decomp (FUN_004d1600).
演出 = 4 只羊 (e_sleep) 从屏幕右侧跑进来, 依次跳过目标, 跑出屏幕左侧; 目标头上落下 s3feel 睡眠符号.

dispatcher: 渐暗 → 施法 seq → -100: 每目标 FUN_004d17b3 (+0x78 ++), 进 0x1e.
  0x1e: +0x78 == 0 且 +0x7a == 0 且目标受击标记全清 → 0x28 渐亮 → 自毁.
  -250: FUN_004d18d5(目标): 符号实体 (目标 x, y+8, z+52, seq 656794 = s3feel 帧 2 每步下沉 1px, 5/5/5/5/8/12/15t) + 0xda;
        目标清 0x10000 (不挂受击 seq).
  -200: 目标回待机 (|= 0x10000), +0x78 --. (exe 无飘字; 这里在此刻做异常结算 Spell.settle.)
FUN_004d17b3: 4 只羊 FUN_004d16b9: 格 (屏中心 x/64 + 6 + i, 目标行), 停点 = 目标 x + 64, seq 6566c4 (帧 1,0 各 1t 循环),
  末只打 0x40000; 播 0xd8.
羊 FUN_004d16b9: state 0: x -= 8px/t, 每 t 脚下扬尘 FUN_004d1647 (x-24, y+1..4, z 0, emong seq 6567e8, 每 t 上升 1px);
  x == 停点 → 挂跳跃 seq 6566dc (seq MOVE 每步 x-8, z 弧 +24..+2 / -2..-24), state 10;
  屏幕 x < -120 → (末只) -250, 自毁.  state 10: 跳跃 seq 完 → 6566c4, state 0.
近似: 战斗画面宽取 640 (exe DAT_0054005c, 640×480 战斗框); headless 无 view_center_world 时以施法者 x 作屏中心.
"""
from __future__ import annotations

from core.anim_engine.bytecode import tuple_to_bytecode
from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _set_z, _getz
from core.enemy_spells.b_common import ground
from core.sprites.base import TILE_W

E_SLEEP, S3FEEL, EMONG = 219, 202, 248
RUN_SEQ = [('fm', E_SLEEP, 1, 1), ('fm', E_SLEEP, 0, 1), ('loop',)]                                      # 6566c4
_HOP = [(-8, 0, 24, 0), (-8, 0, 18, 1), (-8, 0, 16, 1), (-8, 0, 12, 1), (-8, 0, 8, 2), (-8, 0, 6, 2), (-8, 0, 4, 2),
        (-8, 0, 2, 3), (-8, 0, -2, 3), (-8, 0, -4, 2), (-8, 0, -6, 2), (-8, 0, -8, 2), (-8, 0, -12, 1),
        (-8, 0, -16, 1), (-8, 0, -18, 1), (-8, 0, -24, 1)]
# 6566dc: exe dz 上为正, 我们 e.z 上为负 → 取反
HOP_SEQ = ([('fm', E_SLEEP, 1, 3), ('move', -8, 0, -24, 0), ('fm', E_SLEEP, 0, 1)]
           + [('move', dx, dy, -dz, t) for dx, dy, dz, t in _HOP[1:]] + [('exit',)])
SIGN_SEQ = [('fm', S3FEEL, 2, 0)] + [('move', 0, 0, 1, t) for t in (5, 5, 5, 5, 8, 12, 15)] + [('exit',)]   # 656794
DUST_SEQ = [('fm', EMONG, f, 2) for f in (0, 6, 7, 8, 9, 10, 11)] + [('exit',)]                          # 6567e8
SFX_SHEEP, SFX_SIGN = 0xd8, 0xda
SHEEP = 4
RUN_SPEED = 8 * FP
SCREEN_W = 640
OFFSCREEN = -0x78


def _dust_think(e, eng) -> None:
    """FUN_004d1600: z += 1px/t, seq 完自毁."""
    if 'dust' not in e.user_data:
        return
    _set_z(e, _getz(e) + FP)
    if not e.is_playing():
        eng.destroy(e)


def _sheep_think(e, eng) -> None:
    """FUN_004d16b9."""
    ud = e.user_data
    if 'sheep' not in ud:
        return
    sp: Sleep = ud['spell']
    b = sp.battle
    if ud['state'] == 0:
        e.x -= RUN_SPEED
        ox = (_rand(b) & 3) + 1                                       # FUN_004d1647 扬尘
        fx(b, _dust_think, e.x - 24 * FP, e.y + ox * FP, 0, DUST_SEQ, dust=True)
        if e.x >> 16 == ud['stop']:
            eng.attach_seq(e, tuple_to_bytecode(HOP_SEQ))
            ud['state'] = 10
        if (e.x >> 16) - sp.screen_left < OFFSCREEN:
            if ud['last']:
                sp.on_passed(ud['victim'])                            # -250
            eng.destroy(e)
    elif ud['state'] == 10 and not e.is_playing():
        e.z = 0
        eng.attach_seq(e, tuple_to_bytecode(RUN_SEQ))
        ud['state'] = 0


def _sign_think(e, eng) -> None:
    """FUN_004d188b: seq 完 → -200, 自毁."""
    ud = e.user_data
    if 'sign' not in ud:
        return
    if not e.is_playing():
        ud['spell'].on_done(ud['victim'])
        eng.destroy(e)


class Sleep(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.casting = False
        view = getattr(battle, 'view_center_world', None)
        cx = view[0] if view is not None else (ground(caster)[0] >> 16)
        self.center_x = cx
        self.screen_left = cx - SCREEN_W // 2

    def on_cast_impact(self) -> None:
        b = self.battle
        col0 = self.center_x // TILE_W + 6
        for v in self.targets:
            gx, gy = ground(v)
            for i in range(SHEEP):
                x = ((col0 + i) * TILE_W + TILE_W // 2) << 16
                fx(b, _sheep_think, x, gy, 0, RUN_SEQ, sheep=True, spell=self, victim=v, state=0,
                   stop=(gx >> 16) + 64, last=(i == SHEEP - 1))
            _sfx(b, SFX_SHEEP)
            self.live += 1
        self.casting = True

    def think(self) -> None:
        if self.casting and self.live == 0:
            self.casting = False
            self.finish()

    def on_passed(self, v) -> None:
        """-250: FUN_004d18d5 睡眠符号."""
        x, y = _pos(v)
        fx(self.battle, _sign_think, x, y + 8 * FP, 52 * FP, SIGN_SEQ, sign=True, spell=self, victim=v)
        _sfx(self.battle, SFX_SIGN)

    def on_done(self, v) -> None:
        """-200."""
        self.live -= 1
        self.settle(v)


TEMPLATES = {0x4d194c: Sleep}
