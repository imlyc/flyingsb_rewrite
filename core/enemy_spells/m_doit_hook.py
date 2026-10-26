"""带 hook 的 DOIT_melee 招式 (FUN_004d0e18 外包一层拦截信号), reverse_engineering/enemy_spells_decomp.txt.
施法者 seq = exe 招式参数表 (core.enemy_moves.seq_for 同一张), 结算走普通 DOIT 路径 (combat.apply_pending_attack:
受击面朝施法者 + 命中特效 + 飘字). DOIT 无渐暗.

猛撞 (70 用猛撞攻擊 / 73 / 76 / 79 猛撞攻擊; FUN_004dcaa3 / 4dcb2a / 4dcbb1 / 4dcc38):
  seq 冲过目标共 2 格 (上下 96px / 左右 128px), -100 命中, -110 时 DOIT_melee 按像素位置重算格坐标 (x>>6, y/48)
  = 施法者落在目标身后第 2 格. hook 拦截 -2 (dispatcher 销毁): FUN_004c4f01 把当前位置存为归位点 (+0x7c ← +8),
  朝向 = 6418dc[朝向] (反向) → 施法者停在新格并转身.
  我们: -110 时若落点格在图内且空 → 单位移到落点 + 转身; 否则 (近似) 留原格不转身.
雙拳擊 (245; FUN_004ff223): state 0 置 DAT_006566c0 = 0xbd (命中音, DOIT -100 播); seq 的 -1001 (两次挥拳) → 播 0xb9.
DOIT 收尾 (FUN_004d0e18): 0x14 等 -110 + 飘字 + 受击标记 → 0x1e FUN_004cc4e0 镜头拉远 (FUN_00403071(0, 框, 300ms))
  → 0x28 等镜头完 (Wine 下 13 tick) → 自毁 (-2: 猛撞 hook 此时才转身).
实录校准 (wine/captures/en70_t36_F4370.log 70 用猛撞攻擊, en245_t0_F5922.log 245 雙拳擊):
  施法者位移/帧序列、-100 特效 tick 吻合. 修正: (1) 命中特效以目标受击后退 4px (沿施法者朝向) 后为准 (combat._emit_hit_effect
  按格中心, 这里临时替换成带后退的版本); (2) -110 起施法者即回待机姿 (exe 置 0x10000), 猛撞落格但先不转身;
  (3) 收尾多 0x28 镜头 13 tick, 自毁的下一 tick 才转身 (70: 原版 +50). 镜头本身我们不做 (近似: 只等时长).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, SIG_CAST_IMPACT
from core.sprites.base import TILE_W, TILE_H

SIG_END = -110
ZOOM_TICKS = 13             # 0x28 镜头拉远 13 tick (实录 en70: 0x1e +36 → 0x28 +37..+49 自毁, 转身 +50 可见)


def _emit_hit_effect_knocked(battle, attacker, defender) -> None:
    """= combat._emit_hit_effect (敌方 DOIT 分支), 但位置以目标受击后退后为准: exe -100 先 FUN_004c4f20 + 挂受击 seq
    6557f0[6418dc[施法者朝向]] (首个位移 4px 沿施法者朝向立即生效), 再 FUN_004d0c90(目标 +8/+0xc ...)."""
    from core.battle import combat
    from core.enemy_moves import hit_style
    from core.hit_effect_seq import HIT_EFFECT_JITTER_PX, HIT_EFFECT_Y_BASELINE_PX
    specs = combat.hit_effect_specs(defender, attacker.name, hit_style(getattr(attacker, 'pending_enemy_move', None)))
    fx, fy = attacker.facing
    cx = defender.x * TILE_W + TILE_W // 2 + fx * 4
    cy = defender.y * TILE_H + TILE_H // 2 + fy * 4
    for spec in specs:
        if spec.jittered:
            ox = battle.rng.randint(-HIT_EFFECT_JITTER_PX, HIT_EFFECT_JITTER_PX)
            oy = battle.rng.randint(-HIT_EFFECT_JITTER_PX, HIT_EFFECT_JITTER_PX) - HIT_EFFECT_Y_BASELINE_PX
        else:
            ox, oy = 0, -HIT_EFFECT_Y_BASELINE_PX
        combat._spawn_effect_entity(battle, cx + ox, cy + oy, spec)


class DoitHook(Spell):
    DIM = False
    FADE_IN = False

    def on_cast_impact(self) -> None:
        from core.battle import combat
        b = self.battle
        saved = combat._emit_hit_effect
        combat._emit_hit_effect = _emit_hit_effect_knocked
        try:
            combat.apply_pending_attack(b, self.caster)
        finally:
            combat._emit_hit_effect = saved
        if b.engine.swing_sound >= 0:             # DOIT -100: if (-1 < DAT_006566c0) 播
            b.engine._emit('sound_play', None, b.engine.swing_sound)

    def on_caster_signal(self, sig: int) -> bool:
        if sig == SIG_CAST_IMPACT:
            self.on_cast_impact()
            return True
        if sig == SIG_END:
            c = self.caster
            c.cast_hold = False                 # exe -110: 施法者置 0x10000, 末帧再显示 1 tick 后回待机姿 (实录 +27/+28)
            if c.entity is not None:
                c.entity.user_data['hold_until_tick'] = self.battle.engine._tick_id + 1
            self.on_end()
            self.finish()
            return True
        return self.on_hook(sig)

    def _finish_tick(self) -> None:
        z = getattr(self, '_zoom', None)
        if z is not None:
            self._zoom = z - 1
            if self._zoom <= 0:
                self.on_destroy()
                super()._end()
                c = self.caster
                if c.entity is not None:
                    c.entity.user_data.pop('hold_until_tick', None)    # -110 起已是待机姿
            return
        super()._finish_tick()

    def _end(self) -> None:
        if getattr(self, '_zoom', None) is None:
            self._zoom = ZOOM_TICKS           # 0x1e → 0x28 镜头拉远
            return
        super()._end()

    def on_destroy(self) -> None:
        """-2 (dispatcher 自毁): hook 招在这里处理."""

    def on_hook(self, sig: int) -> bool:
        return False

    def on_end(self) -> None:
        pass

    def busy(self) -> bool:
        """DOIT 0x14: 等飘字 + 受击 seq (施法者 seq 已播完)."""
        if getattr(self.battle, 'float_pending', 0) > 0:
            return True
        from core.battle import combat  # noqa: F401
        return any(v.reaction_seq is not None for v in self._victims())

    def _victims(self) -> list:
        t = self.caster.pending_attack_target
        return list(self.targets) + ([t] if t is not None and t not in self.targets else [])


class Ram(DoitHook):
    def on_end(self) -> None:
        c, b = self.caster, self.battle
        ent = c.entity
        if ent is None:
            return
        dx = round((ent.x / 65536) / TILE_W)
        dy = round((ent.y / 65536) / TILE_H)
        if not (dx or dy):
            return
        nx, ny = c.x + dx, c.y + dy
        if not (b.map.in_bounds(nx, ny) and b.q.is_free(nx, ny, c)):
            b._log(f"{c.name} 猛撞落点 ({nx},{ny}) 不可站, 留原格")
            return
        c.x, c.y = nx, ny
        c.snap_render()
        ent.x = ent.y = 0
        self._moved = True

    def on_destroy(self) -> None:
        """-2: FUN_004c4f01 存归位点 + 朝向 = 6418dc[朝向] (反向)."""
        if getattr(self, '_moved', False):
            c = self.caster
            c.facing = (-c.facing[0], -c.facing[1])


class DoubleFist(DoitHook):
    SFX_SWING, SFX_HIT = 0xb9, 0xbd

    def _attach(self) -> None:
        self.battle.engine.swing_sound = self.SFX_HIT   # state 0: DAT_006566c0 = 0xbd
        super()._attach()

    def on_hook(self, sig: int) -> bool:
        if sig == -1001:
            self.battle.engine._emit('sound_play', None, self.SFX_SWING)
            return True
        return False


MOVES = {70: Ram, 73: Ram, 76: Ram, 79: Ram, 245: DoubleFist}
