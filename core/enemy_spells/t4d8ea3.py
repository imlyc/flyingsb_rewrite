"""模板 FUN_004d8ea3 (10 招: 5 使用火力摧毀者 / 59 / 71 / 90 / 92 / 124 / 168 / 189 / 194 / 236, 单体火球),
reverse_engineering/enemy_spells_decomp.txt.

dispatcher: 渐暗 → 施法 seq → -100: FUN_004d8d5c 发一颗火球 (+0x78 ++, state 0x1e):
  火球 think FUN_004d8d04: 出生 = 施法者 (x, y, z+0x30), 静态帧 656130[施法者朝向] (= ef_fire 294 帧 65/62/53/58),
       FUN_004cdbc2 mode 0x31 匀速 (上下 24 / 左右 32 px/t, 只设朝向那一轴, 另一轴速度 0 = 首步直接钳到目标)
       飞向目标 0 (x, y); 两轴都到 → 播 0xd6, 发 -200, 自毁.
  -200: 目标 0 FUN_004c4f20 + 受击 6557f0[目标朝向] + ef010 刺爆 655c10[施法者朝向]
        + FUN_004d0d7b 火爆 655e10 (slot 290 帧 0,1,2,3,5,6,7) 于 (目标 x + rand%12-6, y+0x7c, z+0xac), 播完发 -210;
        +0x78 = 0, +0x7a ++.
  -210: 目标 0 飘字 (预算伤害), +0x7c ++, +0x7a --.   -20: +0x7c --.
  0x1e: 0x78/0x7a/0x7c 都 0 且目标 0 受击 seq 完 → 0x28 渐亮 → 自毁.
注: exe 只给目标表第 0 个受击/飘字 (单体模板); 我们也只结算 targets[0].
hook 招式 189 (FUN_004e2d83): -100 时先播 0xcb 再进模板.
实录校准 (wine/captures/en5_t2_F3566.log): 火球 -100 后 +16 出生, 8 tick 到达; 刺爆/火爆 +24, 火爆 31 tick, 飘字 +55,
  渐亮起点 +92 均吻合. 火爆位置以目标受击后退 4px 之后为准 (knocked_pos). 残差: 原版渐亮占 21 tick (我们 20, 帧率),
  施法者回待机晚 2 tick (框架); 飘字数字 spawner→数字 原版 2 tick 我们 1 tick (公共飘字系统).
189 实录 (en189_t143_F4470.log): 施法 seq / 火球 (+18, 6 tick) / 刺爆+火爆 (+24) / 飘字 / 渐亮起点 +92 逐 tick 吻合, 无需改动.
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _dir, _cdbc2, _motion, _unit_z

FIRE = 294
BALL_FRAME = (65, 62, 53, 58)                                   # 656130[dir] → (294, 帧)
BURST_SEQ = [('fm', 290, 0, 1), ('fm', 290, 1, 2), ('fm', 290, 2, 3), ('fm', 290, 3, 3), ('fm', 290, 5, 4),
             ('fm', 290, 6, 5), ('fm', 290, 7, 6), ('exit',)]   # 655e10
SFX_ARRIVE = 0xd6
PROJ_Z = 0x30
SPEED = {0: (0, -24), 1: (0, 24), 2: (-32, 0), 3: (32, 0)}      # FUN_004d8d5c / 4d9343 +0x16c/+0x170
KNOCK = {0: (0, 4), 1: (0, -4), 2: (4, 0), 3: (-4, 0)}          # 受击 seq 6557f0[目标朝向] 第一步 move (挂 seq 当场执行)


def knocked_pos(v) -> tuple[int, int]:
    """受击后的目标位置 (16.16). 实录 (en5_t2 / en3_t1): -200/-250 先挂受击 seq, 它第一步后退 4px 当场生效,
    随后生成的火爆以后退后的 x/y 为基准. 我们的受击位移不改单位坐标, 这里补上."""
    x, y = _pos(v)
    dx, dy = KNOCK[_dir(v)]
    return x + dx * FP, y + dy * FP


# ---------------- 公共子实体 (其它 A 组模块也用) ----------------
def _burst_think(e, eng) -> None:
    """FUN_004d0dcf: seq 播完 → 回调 (= 给 dispatcher 发 +400 信号), 自毁."""
    ud = e.user_data
    if 'burst_cb' not in ud or e.is_playing():
        return
    cb = ud.pop('burst_cb')
    eng.destroy(e)
    if cb is not None:
        cb()


def burst(battle, x: int, y: int, z: int, seq, cb=None):
    """FUN_004d0d7b(x, y, z, seq, sig): 世界坐标 (16.16, z 上正) 挂 seq, 播完调 cb()."""
    return fx(battle, _burst_think, x, y, z, seq, burst_cb=cb)


def _proj_think(e, eng) -> None:
    """FUN_004d8d04 / FUN_004d92dd: FUN_004cdbc2 到达 → 0xd6 + 回调."""
    ud = e.user_data
    if 'proj_cb' not in ud:
        return
    if not _cdbc2(e):
        return
    cb = ud.pop('proj_cb')
    _sfx(ud['battle'], SFX_ARRIVE)
    eng.destroy(e)
    cb()


def projectile(battle, caster, tx: int, ty: int, frames, cb):
    """FUN_004d8d5c / FUN_004d9343: 施法者 (x, y, z+0x30) 发静态帧火球, mode 0x31 匀速飞向 (tx, ty)."""
    d = _dir(caster)
    x, y = _pos(caster)
    vx, vy = SPEED[d]
    return fx(battle, _proj_think, x, y, _unit_z(caster) + PROJ_Z * FP, None, atlas=FIRE, frame=frames[d],
              battle=battle, proj_cb=cb,
              **_motion(m=0x31, vx=vx * FP, vy=vy * FP, tx=tx, ty=ty, tz=_unit_z(caster) + PROJ_Z * FP))


class FireBall(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.fired = False

    def on_cast_impact(self) -> None:
        """-100: FUN_004d8d5c."""
        self.fired = True
        self.live += 1
        v = self.targets[0] if self.targets else None
        if v is not None:
            tx, ty = _pos(v)
        else:
            from core.sprites.base import TILE_W, TILE_H
            cx, cy = self.caster.pending_attack_cursor or (self.caster.x, self.caster.y)
            tx, ty = (cx * TILE_W + TILE_W // 2) * FP, (cy * TILE_H + TILE_H // 2) * FP
        projectile(self.battle, self.caster, tx, ty, BALL_FRAME, lambda: self.on_arrive(v, tx, ty))

    def on_arrive(self, v, tx: int, ty: int) -> None:
        """-200: 受击 + 刺爆 + 火爆 655e10 (播完 -210 飘字)."""
        if v is not None:
            self.hit(v)
            tx, ty = knocked_pos(v)
        z = (_unit_z(v) if v is not None else 0) + 0xac * FP
        x = tx + ((_rand(self.battle) % 12 - 6) << 16)
        burst(self.battle, x, ty + 0x7c * FP, z, BURST_SEQ, lambda: self.on_burst_done(v))

    def on_burst_done(self, v) -> None:
        """-210."""
        self.live -= 1
        if v is not None:
            self.settle(v)

    def think(self) -> None:
        if self.fired and self.live == 0:
            self.fired = False
            self.finish()


class FireBall189(FireBall):
    """FUN_004e2d83: -100 先播 0xcb."""
    def on_cast_impact(self) -> None:
        _sfx(self.battle, 0xcb)
        super().on_cast_impact()


TEMPLATES = {0x4d8ea3: FireBall}
MOVES = {189: FireBall189}
