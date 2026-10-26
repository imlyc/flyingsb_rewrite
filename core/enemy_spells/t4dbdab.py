"""模板 FUN_004dbdab 重拳 (3 招: 68 用重拳攻擊 / 80 用重拳攻擊 / 160 用拳攻擊), reverse_engineering/enemy_spells_decomp.txt.

dispatcher: 渐暗 → 施法 seq 表[朝向] → -100: +0x78 清零 → 0x1e: dispatcher age%16==0 时给下一个目标放一只拳
  (FUN_004dbd44: 目标 x, y+1, z, seq 65991c = 播 221 + 拳 atlas 315 帧 0..6 各 1t, 播完定格).
  拳 think FUN_004dbc79: age==6 → -250; age==0x30 → 等全局标志 (所有拳都已 -250) → 挂 659968 (帧 6..0 各 1t 收回)
      → 播完 -200 并自毁.
  -250: 目标复位 + 受击 6557f0[目标朝向] + ef010 刺爆 655c10[施法者朝向] + et00 星爆 655b18 (都不抖动) + 0xbd;
        计数满目标数 → 全局标志 = 1.
  -200: 飘字 (+0x7a), +0x78 --.
  0x28: 拳全收 + 飘字完 + 受击完 → 0x32 渐亮 → 自毁.
实录校准 (wine/captures/en68_t34_F4458.log, 68 用重拳攻擊): 拳 +29 出生寿命 63, 帧序列 (0 1×2 .. 6×39 5×2 .. 0×3)、
  -250 刺爆/星爆 +35、-200 +91、飘字 +93/+95/+97 逐 tick 吻合; 刺爆/星爆位置改为目标受击后退 4px 后 (b_common.react). 残差: 渐亮起点晚 1 tick (原版 +128, 我们 +129) —
  原版渐亮 = 首个飘字数字 +35, 我们公共飘字系统 +36 (en5 实录里原版飘字发生器多活 1 tick 被抵消了), 属框架问题.
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, _dir, fx, FP, _pos, _sfx, _unit_z
from core.enemy_spells.b_common import react

FIST = 315
FIST_SEQ = [('sound', 221, 0x0411)] + [('fm', FIST, f, 1) for f in range(7)] + [('exit',)]       # 65991c
FIST_BACK_SEQ = [('fm', FIST, f, 1) for f in range(6, -1, -1)] + [('exit',)]                    # 659968
SFX_HIT = 0xbd
INTERVAL, HIT_AGE, HOLD_AGE = 0x10, 6, 0x30


def _fist_think(e, eng) -> None:
    """FUN_004dbc79."""
    ud = e.user_data
    if 'fist' not in ud:
        return
    sp: Fist = ud['spell']
    ud['age'] += 1
    st = ud['st']
    if st == 0:
        if ud['age'] == HIT_AGE:
            sp.on_fist_hit(ud['victim'])
        if ud['age'] == HOLD_AGE:
            ud['st'] = 10
    elif st == 10:
        if sp.all_hit:
            from core.anim_engine.bytecode import tuple_to_bytecode
            eng.attach_seq(e, tuple_to_bytecode(FIST_BACK_SEQ))
            ud['st'] = 20
    elif st == 20 and not e.is_playing():
        sp.on_fist_done(ud['victim'])
        eng.destroy(e)


class Fist(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.spawned = 0
        self.hits = 0
        self.all_hit = False
        self.casting = False

    def on_cast_impact(self) -> None:
        self.spawned = 0
        self.casting = True
        if not self.targets:
            self.casting = False
            self.finish()

    def think(self) -> None:
        if not self.casting:
            return
        if self.spawned < len(self.targets):
            if self.age % INTERVAL == 0:
                v = self.targets[self.spawned]
                self.spawned += 1
                x, y = _pos(v)
                fx(self.battle, _fist_think, x, y + FP, _unit_z(v), FIST_SEQ, fist=True, spell=self, victim=v,
                   age=0, st=0)
                self.live += 1
            return
        if self.live <= 0:
            self.casting = False
            self.finish()

    def on_fist_hit(self, v) -> None:
        """-250."""
        react(self, v, d=_dir(self.caster), starburst=True)   # 实录: 刺爆/星爆以目标受击后退 4px 后的位置为准
        self.hits += 1
        if self.hits == len(self.targets):
            self.all_hit = True
        _sfx(self.battle, SFX_HIT)

    def on_fist_done(self, v) -> None:
        """-200."""
        self.live -= 1
        self.settle(v)


TEMPLATES = {0x4dbdab: Fist}
