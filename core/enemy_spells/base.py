"""敌招演出框架 = exe 敌招 dispatcher 实体 (+0x14c 状态机) 的共同部分.

exe 模板的共同流程 (以 FUN_004d68a0 为例, reverse_engineering/enemy_spells_decomp.txt):
  state 0   FUN_004d0cd8(1, 0x1e) 渐暗, 完成 → 10
  state 10  施法者清 0x10000, 挂 seq 表[施法者朝向] (MOVES[.][9] = 表地址, 已解码进 core.enemy_move_data.SEQ_TABLES)
  -100      (施法者 seq 发) → 各招登场
  ...       子实体对 dispatcher 发信号, 源 = 目标单位 (FUN_004cba90(目标, sig)):
            -250 = 受击 (FUN_004c4f20 复位 + 6557f0[目标朝向] 受击 seq + 特效), 标记目标 +0x3c[i] |= 1
            -200 = 结算飘字 (FUN_004d05d8(目标, 预算伤害)), 计数 +0x7a ++
            -20  = 飘字完, +0x7a --
            -10..-12 = 目标受击 seq 播完 → 目标回待机, 清 +0x3c[i]
  收尾      所有计数归零 → FUN_004d0cd8(0, 0x1e) 渐亮 → FUN_004c4a6f 自毁.
我们这边: 受击 seq / 飘字都已由全局系统计时 (reaction_seq / battle.float_pending), 框架在 finish() 时等它们走完,
再渐亮 → 发 SIG_END (带 unit) → tactics.post_attack_anim.
数值: 结算走 core.battle.formulas.enemy_attack (类别 0) / core.enemy_moves (类别 1 异常, 2 回复).

子类写法 (exe 子实体 think 的 Python 版放在模块里, 用 fx() 生成):
  class Thunder(Spell):
      def on_cast_impact(self): ...     # -100
      def think(self): ...              # dispatcher 每 tick (state 机), 演完调 self.finish()
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.anim_engine.bytecode import tuple_to_bytecode
from core.anim_engine.entity import SIG_END
from core.jet_skills import FP, _fx, _set_z, _rand, _sin, _cos, _pos, _sfx, _dir, _i32
from core.mina_skills import _c3211, _cdbc2, _motion, _getz, _unit_z

if TYPE_CHECKING:
    from core.anim_engine.engine import Engine
    from core.anim_engine.entity import Entity
    from core.battle.data import BattleUnit

__all__ = ['Spell', 'FP', 'fx', '_set_z', '_rand', '_sin', '_cos', '_pos', '_sfx', '_dir', '_i32', '_c3211', '_cdbc2',
           '_motion', '_getz', '_unit_z', 'seq_of']

SIG_CAST_IMPACT = -100
# 原版实录 (2026-10-26 蛇魔法 巨雷壓頂, wine/captures/en15_thunder_*): dispatcher state 0 (渐暗) 18 tick + state 10 (挂施法 seq) 1 tick
# → 挂 seq 那一刻 dispatcher age = 19. 各模板 "age % N" 的节拍以此为准 (我们渐暗时长按 ms 换算, tick 数不同, 挂 seq 时对齐 age).
EXE_ATTACH_AGE = 19
EXE_DIM_TICKS = (20, 20)        # 同一实录: 渐暗 state 0 18 tick + 挂 seq 1 tick (我们 on_done 在第 n-1 tick → 20), 收尾渐亮 state 0x32 20 tick (Wine 帧率下 FUN_004d0cd8 的 30 步)


def fx(battle, think_fn, x: int, y: int, z: int, seq=None, /, atlas: int | None = None, frame: int = 0, **ud) -> "Entity":
    """特效子实体 (= FUN_004c4936 + 挂 seq). z: 16.16 正向 (上为正). think_fn(e, eng) 用 ud 里的键判是否已初始化."""
    return _fx(battle, think_fn, x, y, z, seq, atlas=atlas, frame=frame, **ud)


def seq_of(table_addr: int, d: int) -> list[tuple]:
    from core.enemy_move_data import SEQ_TABLES
    return SEQ_TABLES[table_addr][d]


class Spell:
    """一次敌招演出. 生命周期: begin_attack → start() (渐暗 → 挂施法 seq) → on_cast_impact() (-100) → think() 每 tick
    → finish() (等受击/飘字 → 渐亮 → SIG_END)."""
    DIM = True                      # 开头 FUN_004d0cd8(1, 0x1e) 渐暗 (无渐暗的模板设 False)
    FADE_IN = True                  # 收尾渐亮

    def __init__(self, battle, caster: "BattleUnit", mid: int):
        from core.enemy_moves import move
        self.battle, self.caster, self.mid = battle, caster, mid
        self.m = move(mid)
        self.targets: list["BattleUnit"] = self._collect_targets()
        self.age = 0                # dispatcher 存活 tick (+0x144)
        self.state = 0              # +0x14c
        self.live = 0               # 未结束的子实体计数 (子类自己加减)
        self.done = False
        self._finishing = False
        self.coord = battle.engine.spawn(think_fn=self._coord_think)
        self.coord.flags = 0x800 | 0x10000
        self.coord.user_data.update(kind='enemy_spell', projectile=True, spell=self,
                                    on_caster_impact=lambda c, eng: self._cast_impact(),
                                    on_caster_signal=self.on_caster_signal)

    # ---------- 目标 ----------
    def _collect_targets(self) -> list:
        """exe 目标表 DAT_00869c48: 伤害范围内的单位 (按行, 再按列). 对己方招 (flags&3==1) = 范围内友军."""
        b, c = self.battle, self.caster
        ally = self.m is not None and self.m.target_type == 1
        tiles = getattr(b, '_pending_damage_range', None)
        if tiles:
            cells = sorted(tiles, key=lambda t: (t[1], t[0]))
        else:
            t = c.pending_attack_target
            cells = [(t.x, t.y)] if t is not None else []
        out = []
        for (x, y) in cells:
            u = b.q.occupant(x, y)
            if u is None or not u.alive or u in out:
                continue
            if (u.is_player == c.is_player) == ally:
                out.append(u)
        return out

    # ---------- 施法者 ----------
    def cast_seq(self, d: int) -> list[tuple] | None:
        """施法者 seq (默认 = 招式参数表[朝向]); None = 不挂 seq (直接 -100)."""
        from core.enemy_move_data import SEQ_TABLES
        if self.m is not None and self.m.arg in SEQ_TABLES:
            return SEQ_TABLES[self.m.arg][d]
        return None

    def start(self) -> None:
        if self.DIM:
            from core.battle.skill_dim import start_skill_dim
            start_skill_dim(self.battle, self._attach, ticks=EXE_DIM_TICKS[0])
        else:
            self._attach()

    def _attach(self) -> None:
        if self.DIM:
            self.age = EXE_ATTACH_AGE + 1     # 渐暗实体的 on_done 在协调实体本 tick think 之后 → 下一 tick think 时 age = 20 (同 exe)
        c = self.caster
        seq = self.cast_seq(_dir(c))
        c.pending_caster_coord = self.coord
        if seq is None or c.entity is None:
            self._cast_impact()
            return
        self.battle.engine.attach_seq(c.entity, tuple_to_bytecode(seq))
        c.cast_hold = any(t[0] in ('fm', 'fm_mode1', 'idle') for t in seq)

    def _cast_impact(self) -> None:
        self.on_cast_impact()

    def on_cast_impact(self) -> None:
        """-100. 子类实现."""

    def on_caster_signal(self, sig: int) -> bool:
        """施法者 seq 的其他信号 (hook 招式: -2 转身 / -0xd2 等). 返回 True = 已处理. -100 走 on_cast_impact."""
        if sig == SIG_CAST_IMPACT:
            self._cast_impact()
            return True
        return False

    # ---------- 每 tick ----------
    def _coord_think(self, e: "Entity", eng: "Engine") -> None:
        if e.user_data.get('spell') is not self or self.done:
            return
        if self._finishing:
            self._finish_tick()
            return
        self.think()
        self.age += 1

    def think(self) -> None:
        """dispatcher 每 tick. 子类实现; 演完调 self.finish()."""

    # ---------- 目标反应 / 结算 ----------
    def hit(self, victim, fx: str | None = 'dir', facing=None, sound: int | None = None) -> None:
        """-250: 受击 seq (不转向) + 特效. fx='dir' = ef010 方向刺爆 655c10[施法者朝向] (FUN_004d0c90 y+400 z+448),
        'both' = DOIT 式 et00 星爆 + 红刺, None = 无."""
        from core.battle import combat
        from core.hit_effect_seq import (HitEffectSpec, facing_to_dir, UNIVERSAL_SPARK_ATLAS, UNIVERSAL_SPARK_BY_DIR,
                                         UNIVERSAL_SPARK_FRAME_TICKS, HIT_EFFECT_Y_BASELINE_PX)
        from core.sprites.base import TILE_W, TILE_H
        if not victim.alive:
            return
        combat.set_reaction(victim, "hit", None)
        if fx == 'both':
            combat._emit_hit_effect(self.battle, self.caster, victim)
        elif fx == 'dir':
            d = facing_to_dir(facing or self.caster.facing)
            spec = HitEffectSpec(UNIVERSAL_SPARK_ATLAS, list(UNIVERSAL_SPARK_BY_DIR[d]), UNIVERSAL_SPARK_FRAME_TICKS,
                                 jittered=False)
            cx = victim.x * TILE_W + TILE_W // 2
            cy = victim.y * TILE_H + TILE_H // 2 - HIT_EFFECT_Y_BASELINE_PX
            combat._spawn_effect_entity(self.battle, cx, cy, spec)
        if sound is not None:
            _sfx(self.battle, sound)

    def settle(self, victim) -> None:
        """-200: 按招式类别结算 + 飘字 (无受击 seq). 类别 0 伤害 / 1 异常 / 2 回复 / 4 自爆."""
        from core.battle import combat
        from core import enemy_moves as EM
        b, c, m = self.battle, self.caster, self.m
        if m is None:
            return
        if m.category == EM.CAT_HEAL:
            if victim.alive:
                amt = EM.heal_amount(b, c, m, combat._falloff(b, victim))
                before = victim.hp
                victim.hp = min(victim.max_hp, victim.hp + amt)
                combat.push_damage_event(b, victim, combat.DamageEvent(victim.hp - before, victim.hp, victim.x, victim.y,
                                                                     heal=True))
                b._log(f"{c.name} → {victim.name}: 回复 {victim.hp - before} HP")
            return
        if m.category == EM.CAT_STATUS:
            if victim.alive:
                got = EM.resolve_status(b, c, victim, m)
                b._log(f"{c.name} → {victim.name}: " + (f"中了 {[hex(x) for x in got]}" if got else "异常未中"))
            return                                       # exe 异常类模板的 -200 不出飘字 (中没中都一样)
        if not victim.alive:
            return
        c.suppress_hit_fx = True
        c.suppress_hit_reaction = True
        try:
            combat._roll_damage_one(b, c, victim, face_attacker=False)
        finally:
            c.suppress_hit_fx = False
            c.suppress_hit_reaction = False

    # ---------- 收尾 ----------
    def busy(self) -> bool:
        """还有受击 seq / 飘字 / 子实体没走完."""
        if self.live > 0 or getattr(self.battle, 'float_pending', 0) > 0:
            return True
        return any(v.reaction_seq is not None for v in self.targets)

    def finish(self) -> None:
        """进入收尾: 等 busy() 清空 → 渐亮 → SIG_END."""
        self._finishing = True
        self._fade = None
        self._quiet = 0

    def _finish_tick(self) -> None:
        if self._fade is None:
            if self.busy():
                self._quiet = 0
                return
            self._quiet += 1
            if self._quiet < 2:                  # 实录: exe 收到最后一个 -20 后下一 tick 才进渐亮 (两段实录都晚 1 tick)
                return
            if self.FADE_IN:
                from core.battle.skill_dim import end_skill_dim
                self._fade = end_skill_dim(self.battle, on_done=self._end, ticks=EXE_DIM_TICKS[1]) or False
                if self._fade is False:
                    self._end()
            else:
                self._fade = False
                self._end()

    def _end(self) -> None:
        if self.done:
            return
        self.done = True
        c = self.caster
        if c.pending_caster_coord is self.coord:
            c.pending_caster_coord = None
        c.cast_hold = False
        if c.entity is not None:                 # 实录: dispatcher 最后一 tick 之后再过 2 tick 施法者才回待机
            c.entity.user_data['hold_until_tick'] = self.battle.engine._tick_id + 2
        e = self.coord
        e.user_data['unit'] = c
        eng = self.battle.engine
        eng._signal(e, SIG_END)
        eng.destroy(e)
