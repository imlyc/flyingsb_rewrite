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
近似: 计时实体 age 从 0 起 (exe +0x144 递增与 think 先后未核); state 10 复位后同一 t 不再判 (下一 t 从 age 1 起).
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
    fx(b, _smoke_think, x, y, z, SMOKE[_rand(b) % 3], smoke=True, spell=sp, st=0, **mot)


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
                ud['age'] = 0
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
            b.engine.attach_seq(c.entity, tuple_to_bytecode(FAN[_dir(c)]))
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
