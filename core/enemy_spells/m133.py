"""133 煙霧攻擊 (侍女服女郎): dispatcher FUN_004df96e (custom), reverse_engineering/enemy_spells_decomp.txt, 2026-10-26.

dispatcher:
  -1      DAT_0086a778 (烟团解散旗) = 0.
  case 0  渐暗 → 10 挂施法 seq 660860[朝向] (图 121 10 帧各 3t, 内含 2 次 0xab 音, -100) → 0x1e.
  -100    每个目标 FUN_004df925(目标, 施法者) 计时实体; 施法者改挂 660a30[朝向] (同帧**循环**, 一直摇扇).
  计时 think FUN_004df7f2:
          state 0: age == next (初值 1) → (第 0 粒且是第一个目标: 播 0xc2) 生成一团烟 FUN_004df543; n++; next += 2;
                   n > 15 → age = 0, state 10.   (每目标 16 团, 隔 2t)
          state 10: age%20 == 0 → 以目标为源发 -250; age == 128 → -200, 自毁.
  烟团 FUN_004df543(目标, 施法者): 生在施法者 (x, y+1, z), 飞向 目标 (x + rand%48-24, y+1, z + rand&63), 速度同
          core.enemy_spells.m127.aim_motion (mode 0x71); seq 660a88[rand%3] (图 248 两帧各 8t 循环).
          think FUN_004df459: 三轴到 → state 10: 每 t 在落点 ±2 px 抖动 (各轴 (rand&3)-2, 顺序 x→y→z); 解散旗置位 → 自毁.
  -250    目标 FUN_004c4f20 + 受击 6557f0 + 655c10[反(目标朝向)] 刺爆 + 655b18 星爆 (无抖动) + 0xbd.
  -200    该目标飘字; 施法者停 seq (清 0x20000, 停在当前帧); 第 N 个 (= 目标数) -200 → 停 0xc2 音 + 解散旗 = 1.
  0x1e    计数归零 + 受击播完 → 0x28 渐亮 → 自毁.
实录校准 (wine/captures/en133_t93_F3540.log): 计时实体出生当 tick 不 think; state 10 首次 think 时 age = 1 (exe 置 0 后引擎 +1),
  首次 -250 在第 16 团后 20 t, 共 6 次, -200 在 age 128; 烟团出生当 tick 已走第 1 步; 摇扇首遍少第 2 帧 (见 fan_seq).
  改后受击/飘字/施法者帧逐 tick 吻合; 渐亮原版 19 t (我们 20 t, 框架定值) → 收尾 +1 t.
"""
from __future__ import annotations

from core.anim_engine.bytecode import tuple_to_bytecode
from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _cdbc2, _dir, _unit_z, _set_z, _getz
from core.enemy_spells.m203 import impact_fx, reset_hit, OPP
from core.enemy_spells.m127 import aim_motion

CAST_133 = [  # @0x660860
    [('sound', 171, 1041), ('fm', 121, 30, 3), ('fm', 121, 31, 3), ('fm', 121, 32, 3), ('fm', 121, 33, 3), ('fm', 121, 34, 3), ('sound', 171, 1041), ('fm', 121, 35, 3), ('fm', 121, 36, 3), ('fm', 121, 37, 3), ('fm', 121, 38, 3), ('fm', 121, 39, 3), ('jump', -100), ('exit',)],
    [('sound', 171, 1041), ('fm', 121, 20, 3), ('fm', 121, 21, 3), ('fm', 121, 22, 3), ('fm', 121, 23, 3), ('fm', 121, 24, 3), ('sound', 171, 1041), ('fm', 121, 25, 3), ('fm', 121, 26, 3), ('fm', 121, 27, 3), ('fm', 121, 28, 3), ('fm', 121, 29, 3), ('jump', -100), ('exit',)],
    [('sound', 171, 1041), ('fm', 121, 0, 3), ('fm', 121, 1, 3), ('fm', 121, 2, 3), ('fm', 121, 3, 3), ('fm', 121, 4, 3), ('sound', 171, 1041), ('fm', 121, 5, 3), ('fm', 121, 6, 3), ('fm', 121, 7, 3), ('fm', 121, 8, 3), ('fm', 121, 9, 3), ('jump', -100), ('exit',)],
    [('sound', 171, 1041), ('fm', 121, 10, 3), ('fm', 121, 11, 3), ('fm', 121, 12, 3), ('fm', 121, 13, 3), ('fm', 121, 14, 3), ('sound', 171, 1041), ('fm', 121, 15, 3), ('fm', 121, 16, 3), ('fm', 121, 17, 3), ('fm', 121, 18, 3), ('fm', 121, 19, 3), ('jump', -100), ('exit',)],
]
FAN = [  # @0x660a30
    [('sound', 171, 1041), ('fm', 121, 30, 3), ('fm', 121, 31, 3), ('fm', 121, 32, 3), ('fm', 121, 33, 3), ('sound', 171, 1041), ('fm', 121, 34, 3), ('fm', 121, 35, 3), ('fm', 121, 36, 3), ('fm', 121, 37, 3), ('fm', 121, 38, 3), ('fm', 121, 39, 3), ('loop',)],
    [('sound', 171, 1041), ('fm', 121, 20, 3), ('fm', 121, 21, 3), ('fm', 121, 22, 3), ('fm', 121, 23, 3), ('fm', 121, 24, 3), ('sound', 171, 1041), ('fm', 121, 25, 3), ('fm', 121, 26, 3), ('fm', 121, 27, 3), ('fm', 121, 28, 3), ('fm', 121, 29, 3), ('loop',)],
    [('sound', 171, 1041), ('fm', 121, 0, 3), ('fm', 121, 1, 3), ('fm', 121, 2, 3), ('fm', 121, 3, 3), ('fm', 121, 4, 3), ('sound', 171, 1041), ('fm', 121, 5, 3), ('fm', 121, 6, 3), ('fm', 121, 7, 3), ('fm', 121, 8, 3), ('fm', 121, 9, 3), ('loop',)],
    [('sound', 171, 1041), ('fm', 121, 10, 3), ('fm', 121, 11, 3), ('fm', 121, 12, 3), ('fm', 121, 13, 3), ('fm', 121, 14, 3), ('sound', 171, 1041), ('fm', 121, 15, 3), ('fm', 121, 16, 3), ('fm', 121, 17, 3), ('fm', 121, 18, 3), ('fm', 121, 19, 3), ('loop',)],
]
SMOKE = [  # @0x660a88 (3 项)
    [('fm', 248, 6, 8), ('fm', 248, 7, 8), ('loop',)],
    [('fm', 248, 12, 8), ('fm', 248, 13, 8), ('loop',)],
    [('fm', 248, 0, 8), ('fm', 248, 1, 8), ('loop',)],
]
SFX_SMOKE, SFX_HIT = 0xc2, 0xbd


def fan_seq(d: int) -> list[tuple]:
    """-100 改挂的摇扇 seq. 实录 (en133_t93): 第一遍跳过第 2 帧 (帧 0 停 4 t 后直接帧 2, 共 9 帧 36 t), 之后每遍完整 10 帧
    (exe 在信号处理里换 seq 后解释器又前进一条指令, 近似). 展开: 首遍 + 完整体 ×8 + 循环 (-200 停帧前最多跑约 4 遍)."""
    body = FAN[d][:-1]
    fms = [i for i, t in enumerate(body) if t[0] == 'fm']
    first = body[:fms[1]] + body[fms[1] + 1:]
    return first + body * 8 + [('loop',)]


def _smoke_think(e, eng) -> None:
    """FUN_004df459."""
    ud = e.user_data
    if 'smoke' not in ud:
        return
    sp: Smoke = ud['spell']
    if ud['st'] == 0:
        if _cdbc2(e):
            ud['st'] = 10
        return
    b = sp.battle
    e.x = ud['tx'] - 2 * FP + (_rand(b) & 3) * FP
    e.y = ud['ty'] - 2 * FP + (_rand(b) & 3) * FP
    _set_z(e, ud['tz'] - 2 * FP + (_rand(b) & 3) * FP)
    if sp.dispersed:
        eng.destroy(e)


def _smoke(sp, victim) -> None:
    """FUN_004df543(目标, 施法者)."""
    b, c = sp.battle, sp.caster
    x, y = _pos(c)
    y += FP
    z = _unit_z(c)
    vx, vy = _pos(victim)
    tx = vx + (_rand(b) % 48 - 24) * FP
    ty = vy + FP
    tz = _unit_z(victim) + (_rand(b) & 63) * FP
    mot = aim_motion(b, x, y, z, tx, ty, tz)
    e = fx(b, _smoke_think, x, y, z, SMOKE[_rand(b) % 3], smoke=True, spell=sp, st=0, **mot)
    if _cdbc2(e):                 # 实录 en133_t93: 烟团出生当 tick 已走第 1 步
        e.user_data['st'] = 10


def _timer_think(e, eng) -> None:
    """FUN_004df7f2."""
    ud = e.user_data
    if 'smoke_timer' not in ud:
        return
    sp: Smoke = ud['spell']
    v = ud['victim']
    age = ud['age']
    if ud['st'] == 0:
        if age == ud['next']:
            if ud['n'] == 0 and sp.targets and v is sp.targets[0]:
                _sfx(sp.battle, SFX_SMOKE)
            _smoke(sp, v)
            ud['n'] += 1
            ud['next'] += 2
            if ud['n'] > 15:
                ud['age'] = 1             # exe 置 0 后引擎再 +1 → state 10 首次 think 时 age 1 (实录: 首次 -250 在第 16 团后 20 t)
                ud['st'] = 10
                return
    else:
        if age % 20 == 0:
            sp.on_hit(v)
        if age == 128:
            sp.on_settle(v)
            eng.destroy(e)
            return
    ud['age'] = age + 1


class Smoke(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.fired = False
        self.dispersed = False          # DAT_0086a778
        self.settled = 0                # +0x7c

    def cast_seq(self, d: int):
        return CAST_133[d]

    def on_cast_impact(self) -> None:
        if self.fired:
            return
        self.fired = True
        b, c = self.battle, self.caster
        for v in self.targets:
            e = b.engine.spawn(think_fn=_timer_think)
            e.flags = 0x800 | 0x10000
            e.user_data.update(kind='hit_effect', projectile=True, smoke_timer=True, spell=self, victim=v,
                               age=0, st=0, n=0, next=1)
            self.live += 1
        if c.entity is not None:
            b.engine.attach_seq(c.entity, tuple_to_bytecode(fan_seq(_dir(c))))
        if not self.targets:
            self.finish()

    def on_hit(self, v) -> None:
        """-250."""
        reset_hit(v)
        impact_fx(self.battle, v, OPP[_dir(v)], jitter=False)
        _sfx(self.battle, SFX_HIT)

    def on_settle(self, v) -> None:
        """-200."""
        b, c = self.battle, self.caster
        self.live -= 1
        self.settle(v)
        ent = c.entity
        if ent is not None:                      # 清 0x20000: 停在当前帧
            b.engine.attach_seq(ent, tuple_to_bytecode([('fm', ent.atlas_slot, ent.frame_idx, 0)]))
        self.settled += 1
        if self.settled == len(self.targets):
            b.engine._emit('sound_stop', None, SFX_SMOKE)
            self.dispersed = True
        if self.live <= 0:
            self.finish()


MOVES = {133: Smoke}
