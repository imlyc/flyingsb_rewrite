"""模板 FUN_004d948f (3 招: 3 召來巨大火炎彈 / 9 用強力火炎攻擊 / 125 用強力風乾, 落点 AOE 大火球),
reverse_engineering/enemy_spells_decomp.txt.

dispatcher: 渐暗 → 施法 seq → -100: FUN_004d9343 发一颗大火球 (+0x78 ++, state 0x1e):
  大火球 think FUN_004d92dd: 出生 = 施法者 (x, y, z+0x30), 静态帧 6560f0[施法者朝向] (ef_fire 294 帧 67/60/55/56),
       FUN_004cdbc2 mode 0x31 匀速 (上下 24 / 左右 32 px/t) 飞向**光标格中心** (施法者 +0x128/+0x12c = 光标格);
       到 → 播 0xd6, 发 -200, 再发 -250, 自毁.
  -200: 光标格中心火爆 655eac (slot 292 帧 0..10, 共 37t) 于 (格 x + rand%12-6, 格 y + 0x7c, z 0xac + rand%16-8)
        (exe 先掷 z 再掷 x), 播完发 -210; +0x78 = 0, +0x7a ++.
  -250: 每个目标 FUN_004c4f20 + 受击 6557f0[目标朝向] + ef010 刺爆 655c10[施法者朝向]
        + 小火爆 655e58 (slot 291 帧 0..7, 27t) 于 (目标 x + rand%12-6, y + 0x18, z 0x48 + rand%16-8) 播完发 -260; 各 +0x7a ++.
  -210: 全部目标飘字, 各 +0x7c ++; +0x7a --.   -260: +0x7a --.   -20: +0x7c --.
  0x1e: 计数都 0 且所有目标受击 seq 完 → 0x28 渐亮 → 自毁.
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, FP, _pos, _rand
from core.enemy_spells.t4d8ea3 import burst, projectile

BALL_FRAME = (67, 60, 55, 56)                                   # 6560f0[dir] → (294, 帧)
CENTER_BURST_SEQ = [('fm', 292, 0, 1), ('fm', 292, 1, 1), ('fm', 292, 2, 2), ('fm', 292, 3, 2), ('fm', 292, 4, 2),
                    ('fm', 292, 3, 2), ('fm', 292, 5, 3), ('fm', 292, 6, 4), ('fm', 292, 7, 5), ('fm', 292, 8, 5),
                    ('fm', 292, 9, 5), ('fm', 292, 10, 5), ('exit',)]       # 655eac
TARGET_BURST_SEQ = [('fm', 291, 0, 1), ('fm', 291, 1, 1), ('fm', 291, 2, 3), ('fm', 291, 3, 3), ('fm', 291, 4, 3),
                    ('fm', 291, 5, 4), ('fm', 291, 6, 6), ('fm', 291, 7, 6), ('exit',)]   # 655e58


class BigFireBall(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.fired = False

    def _cursor_center(self) -> tuple[int, int]:
        from core.sprites.base import TILE_W, TILE_H
        c = self.caster
        cx, cy = c.pending_attack_cursor or ((self.targets[0].x, self.targets[0].y) if self.targets else (c.x, c.y))
        return (cx * TILE_W + TILE_W // 2) * FP, (cy * TILE_H + TILE_H // 2) * FP     # (gx*0x40+0x20, gy*0x30+0x18)

    def on_cast_impact(self) -> None:
        """-100: FUN_004d9343."""
        self.fired = True
        self.live += 1
        tx, ty = self._cursor_center()
        projectile(self.battle, self.caster, tx, ty, BALL_FRAME, lambda: self.on_arrive(tx, ty))

    def on_arrive(self, tx: int, ty: int) -> None:
        b = self.battle
        # -200: 光标格火爆 (播完 -210)
        z = (0xac + (_rand(b) & 0xf) - 8) * FP
        x = tx + ((_rand(b) % 12 - 6) << 16)
        burst(b, x, ty + 0x7c * FP, z, CENTER_BURST_SEQ, self.on_center_done)
        # -250: 全目标受击 + 小火爆 (播完 -260)
        for v in self.targets:
            self.hit(v)
            vx, vy = _pos(v)
            z = (0x48 + (_rand(b) & 0xf) - 8) * FP
            x = vx + ((_rand(b) % 12 - 6) << 16)
            self.live += 1
            burst(b, x, vy + 0x18 * FP, z, TARGET_BURST_SEQ, self.on_target_burst_done)

    def on_center_done(self) -> None:
        """-210: 全部目标飘字."""
        self.live -= 1
        for v in self.targets:
            self.settle(v)

    def on_target_burst_done(self) -> None:
        """-260."""
        self.live -= 1

    def think(self) -> None:
        if self.fired and self.live == 0:
            self.fired = False
            self.finish()


TEMPLATES = {0x4d948f: BigFireBall}
