"""战斗结算: 命中率 / reaction 序列 / 伤害扣血 / 普攻动画启动 / 必杀.

自由函数, 第一参数 battle (TacticsBattle 实例) 当 namespace 用. 把状态机的"结算瞬间"
和外面的回合流/AI 分开, 跟 scenes/battle/ 的 free-function 模式一致.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.battle.data import (
    AGILE_MISS_FACTOR,
    BASE_MISS_RATE,
    BattleUnit,
    DamageEvent,
    MAX_MISS_RATE,
)

if TYPE_CHECKING:
    from core.battle.tactics import TacticsBattle


def miss_chance(attacker: BattleUnit, defender: BattleUnit) -> float:
    diff = defender.agile - attacker.agile
    return max(0.0, min(MAX_MISS_RATE, BASE_MISS_RATE + diff * AGILE_MISS_FACTOR))


def set_reaction(defender: BattleUnit, seq_kind: str, attacker: BattleUnit | None = None) -> None:
    """seq_kind ∈ {'hit','dodge'}. 转面向攻击者, 加载对应的 reaction_seq.py 脚本."""
    from core.reaction_seq import HIT_SEQ, DODGE_SEQ, facing_to_seq_index
    # 保存原朝向 (动画结束 UI 还原); 多次连击不覆盖
    if defender.reaction_saved_facing is None:
        defender.reaction_saved_facing = defender.facing
    # 转面向攻击者
    if attacker is not None:
        dx = attacker.x - defender.x
        dy = attacker.y - defender.y
        if abs(dx) >= abs(dy) and dx != 0:
            defender.facing = (1 if dx > 0 else -1, 0)
        elif dy != 0:
            defender.facing = (0, 1 if dy > 0 else -1)
    idx = facing_to_seq_index(defender.facing)
    defender.reaction_seq = (DODGE_SEQ if seq_kind == "dodge" else HIT_SEQ)[idx]
    defender.reaction_step_idx = 0
    defender.reaction_step_elapsed_ms = 0
    defender.reaction_step_start_off = (0.0, 0.0)
    defender.reaction_offset = (0.0, 0.0)
    defender.reaction_frame = None


def apply_damage(battle: "TacticsBattle", attacker: BattleUnit,
                 defender: BattleUnit, dmg: int, label: str) -> None:
    defender.hp = max(0, defender.hp - dmg)
    battle.damage_events.append(DamageEvent(dmg, defender.hp, defender.x, defender.y))
    set_reaction(defender, "hit", attacker)
    _emit_hit_effect(battle, attacker, defender)
    battle._log(f"{attacker.name} → {defender.name}: {dmg} {label}命中"
                + (f" ({defender.hp}/{defender.max_hp})" if defender.alive else " [击倒]"))


def _emit_hit_effect(battle: "TacticsBattle", attacker: BattleUnit, defender: BattleUnit) -> None:
    """命中分支: 仿原版 DOIT_melee IMPACT 同时 spawn 2 个独立 anim_engine entity.
    miss/dodge 不放. ATK_C 1st spawn = 长椭圆, 否则 = 紫色 starburst; 2nd spawn = 小红刺爆.
    每个 spec 独立抖动 (jittered=True 时 RNG ±8px).
    技能攻击 (pending_skill_id != None) 额外 spawn 1 个特效 (= 技能 dispatcher 在 IMPACT
    时主动调 FUN_004d0c90 加挂的, 见 SKILL_IMPACT_EXTRA).
    """
    from core.hit_effect_seq import (
        HIT_EFFECT_JITTER_PX, HIT_EFFECT_Y_BASELINE_PX, pick_hit_effects,
    )
    from core.skill_seq import has_skill_impact_extra, skill_impact_extra_seq
    from core.sprites.base import TILE_W, TILE_H
    specs = pick_hit_effects(attacker.name, None, attacker.facing)
    cx = defender.x * TILE_W + TILE_W // 2
    cy = defender.y * TILE_H + TILE_H // 2
    for spec in specs:
        if spec.jittered:
            ox = battle.rng.randint(-HIT_EFFECT_JITTER_PX, HIT_EFFECT_JITTER_PX)
            oy = battle.rng.randint(-HIT_EFFECT_JITTER_PX, HIT_EFFECT_JITTER_PX) - HIT_EFFECT_Y_BASELINE_PX
        else:
            ox = 0
            oy = -HIT_EFFECT_Y_BASELINE_PX
        _spawn_effect_entity(battle, cx + ox, cy + oy, spec)

    # 技能专属额外特效 (= 原版 dispatcher IMPACT 分支调 blood_spawn 的 3rd entity)
    sid = attacker.pending_skill_id
    if has_skill_impact_extra(sid):
        _spawn_skill_extra_effect(battle, cx, cy - HIT_EFFECT_Y_BASELINE_PX,
                                  skill_impact_extra_seq(sid))


def _spawn_skill_extra_effect(battle: "TacticsBattle", world_x: int, world_y: int,
                              seq_tuples: list[tuple]) -> None:
    """技能 IMPACT 时 spawn 的额外特效: seq 含多帧 + 可能 mid-seq atlas 切换.
    跟 _spawn_effect_entity 套路一样, 但直接接受 tuple seq (不是 HitEffectSpec)."""
    from core.anim_engine.bytecode import tuple_to_bytecode
    e = battle.engine.spawn()
    e.x = world_x << 16
    e.y = world_y << 16
    e.z = 0
    e.user_data['kind'] = 'hit_effect'
    # 不设 atlas_key — render 端每帧从 entity.atlas_slot 反查 (支持 atlas 切换)
    battle.engine.attach_seq(e, tuple_to_bytecode(seq_tuples))


def _spawn_effect_entity(battle: "TacticsBattle", world_x: int, world_y: int, spec) -> None:
    """通用 effect entity spawn: 跟原版 FUN_004d0c90 blood_spawn 同套路.
    spawn anim_engine entity → 设世界坐标 → attach_seq 跑 FM op 字节码.
    EXIT op 自然结束后 playing flag 自动落下, render 端跳过该 entity.
    """
    e = battle.engine.spawn()
    e.x = world_x << 16
    e.y = world_y << 16
    e.z = 0
    e.user_data['kind'] = 'hit_effect'
    e.user_data['atlas_key'] = spec.atlas_key
    battle.engine.attach_seq(e, spec.to_bytecode())


def strike_skill(battle: "TacticsBattle", attacker: BattleUnit, defender: BattleUnit) -> None:
    # 必杀不能被闪避, 强制重击表现 (技能不走 attack_seq, 立即生效)
    raw = attacker.attack - defender.defence + battle.rng.randint(-5, 5)
    dmg = max(1, raw * 2)
    defender.hp = max(0, defender.hp - dmg)
    battle.damage_events.append(DamageEvent(dmg, defender.hp, defender.x, defender.y))
    set_reaction(defender, "hit", attacker)
    battle._log(f"  {attacker.name} → {defender.name}: {dmg} 必杀伤害"
                + (f" ({defender.hp}/{defender.max_hp})" if defender.alive else " [击倒]"))


# ---- 普攻 (走 anim_engine 字节码) ----
def begin_attack(battle: "TacticsBattle", attacker: BattleUnit, defender: BattleUnit,
                 skill_id: int | None = None,
                 cursor: tuple[int, int] | None = None) -> None:
    """启动攻击 seq; anim_engine 跑字节码, SIGNAL -100 时 apply_pending_attack 独立 roll 命中/伤害.
    多段攻击: seq 含多个 SIGNAL -100, 每次独立判定 (= 原版多次 jump -100).
    skill_id != None 时跑技能专属 seq (= core.skill_seq.SKILL_SEQS), 否则普攻.
    """
    from core.attack_seq import attack_seq_for
    from core.anim_engine.bytecode import tuple_to_bytecode
    attacker.pending_attack_target = defender
    attacker.pending_attack_skill = skill_id is not None
    attacker.pending_skill_id = skill_id
    attacker.pending_attack_cursor = cursor if cursor is not None else (defender.x, defender.y)
    attacker.pending_attack_kind = ""
    attacker.pending_attack_dmg = 0
    attacker.pending_impact_count = 0
    # 数 seq 里 IMPACT 总数, 给 apply_pending_attack 判断"是否最后一段"
    seq_tuples = attack_seq_for(attacker.name, attacker.facing, skill_id)
    attacker.pending_impact_total = max(1, sum(1 for t in seq_tuples if t[0] == 'impact'))
    # 创建/复用 entity, 关联回 BattleUnit (signal handler 用)
    if attacker.entity is None:
        attacker.entity = battle.engine.spawn()
    attacker.entity.x = 0
    attacker.entity.y = 0
    attacker.entity.z = 0
    # 清掉上一次攻击残留的 render snapshot (_move_start_*, _fm_total_ticks 等),
    # 否则新攻击第 1 帧会按旧 snapshot 算 MOVE lerp, 出现瞬移+退回的鬼畜.
    attacker.entity.user_data = {'unit': attacker}
    # tuple seq → bytecode 后挂载. attach_seq 自动跑到第一个阻塞 op.
    seq_bc = tuple_to_bytecode(seq_tuples)
    battle.engine.attach_seq(attacker.entity, seq_bc)


def apply_pending_attack(battle: "TacticsBattle", attacker: BattleUnit) -> None:
    """attack_seq 跑到 'impact' 步骤时由 UI 调.
    多段攻击 (e.g. 無限刀 5 段) 只有 *最后* 一段结算伤害 + 飘字, 之前的 IMPACT 仅
    触发 reaction + hit-fx 给视觉反馈. 单段攻击 (= total=1) 则首段即末段, 直接结算.
    """
    attacker.pending_impact_count += 1
    is_last = attacker.pending_impact_count >= attacker.pending_impact_total
    if not is_last:
        _replay_impact_visuals(battle, attacker)
        return
    # 回血技能 (生命之火): IMPACT 时给 target 友军回 HP, 不走伤害路径.
    sid = attacker.pending_skill_id
    if sid is not None:
        from core.skill_seq import is_heal_skill
        if is_heal_skill(sid):
            _apply_heal(battle, attacker)
            return
    # B 类技能: IMPACT 不直接结算伤害, 而是 spawn 投射物 (think_fn 物理 → 落地后发 SIG_IMPACT_2 才结算)
    if sid is not None:
        from core.skill_seq import has_impact_spawn, skill_impact_spawn
        if has_impact_spawn(sid):
            tile = attacker.pending_attack_cursor
            if tile is None:
                t = attacker.pending_attack_target
                if t is not None:
                    tile = (t.x, t.y)
            if tile is not None:
                skill_impact_spawn(sid)(battle, attacker, tile)
            return    # 不走默认伤害结算
    dmg_tiles = getattr(battle, '_pending_damage_range', None)
    if dmg_tiles:
        for (x, y) in dmg_tiles:
            t = battle.q.occupant(x, y)
            if t is None or not t.alive or t.is_player == attacker.is_player:
                continue
            _roll_damage_one(battle, attacker, t)
        return
    target = attacker.pending_attack_target
    if target is None or not target.alive:
        return
    _roll_damage_one(battle, attacker, target)


def _replay_impact_visuals(battle: "TacticsBattle", attacker: BattleUnit) -> None:
    """多段攻击的非末段 IMPACT: 视觉重放 (反应动画 + hit-fx), 不扣血/不飘字.
    沿用 pending_attack_target / pending_damage_range 拿目标列表."""
    targets: list[BattleUnit] = []
    dmg_tiles = getattr(battle, '_pending_damage_range', None)
    if dmg_tiles:
        for (x, y) in dmg_tiles:
            t = battle.q.occupant(x, y)
            if t is not None and t.alive and t.is_player != attacker.is_player:
                targets.append(t)
    else:
        t = attacker.pending_attack_target
        if t is not None and t.alive:
            targets.append(t)
    for t in targets:
        set_reaction(t, "hit", attacker)
        _emit_hit_effect(battle, attacker, t)


def _apply_heal(battle: "TacticsBattle", attacker: BattleUnit) -> None:
    """回血技能结算: 给 _pending_damage_range (or pending_attack_target) 的友军回 HP.
    生命之火 esum1 burst effect 在 target 上 spawn (视觉)."""
    from core.skill_seq import heal_amount
    amt = heal_amount(attacker, attacker.pending_skill_id)
    targets: list[BattleUnit] = []
    dmg_tiles = getattr(battle, '_pending_damage_range', None)
    if dmg_tiles:
        for (x, y) in dmg_tiles:
            t = battle.q.occupant(x, y)
            if t is not None and t.alive and t.is_player == attacker.is_player:
                targets.append(t)
    else:
        t = attacker.pending_attack_target
        if t is not None and t.alive:
            targets.append(t)
    for t in targets:
        before = t.hp
        t.hp = min(t.max_hp, t.hp + amt)
        healed = t.hp - before
        battle.damage_events.append(DamageEvent(healed, t.hp, t.x, t.y, heal=True))
        _emit_life_fire_effect(battle, t)
        battle._log(f"{attacker.name} → {t.name}: 回复 {healed} HP ({t.hp}/{t.max_hp})")


def _emit_life_fire_effect(battle: "TacticsBattle", target: BattleUnit) -> None:
    """生命之火 esum1 (atlas 299) burst 在 target 头顶 (8 帧)."""
    from core.anim_engine.bytecode import tuple_to_bytecode
    from core.sprites.base import TILE_W, TILE_H
    e = battle.engine.spawn()
    e.x = (target.x * TILE_W + TILE_W // 2) << 16
    e.y = (target.y * TILE_H + TILE_H // 2) << 16
    e.z = -(TILE_H // 2) << 16
    e.user_data['kind'] = 'hit_effect'
    seq = [('fm', 299, i, 3) for i in range(8)] + [('exit',)]
    battle.engine.attach_seq(e, tuple_to_bytecode(seq))


def _roll_damage_one(battle: "TacticsBattle", attacker: BattleUnit, target: BattleUnit) -> None:
    """对单个 target roll miss/hit + 损伤 + 反应动画. 抽出来给 AoE 多目标循环用."""
    if battle.rng.random() < miss_chance(attacker, target):
        battle.damage_events.append(DamageEvent(0, target.hp, target.x, target.y, miss=True))
        set_reaction(target, "dodge", attacker)
        battle._log(f"{attacker.name} → {target.name}: MISS (闪避)")
    else:
        raw = attacker.attack - target.defence + battle.rng.randint(-5, 5)
        dmg = max(1, raw)
        apply_damage(battle, attacker, target, dmg, "")


def clear_pending_attack(attacker: BattleUnit) -> None:
    attacker.pending_attack_target = None
    attacker.pending_attack_kind = ""
    attacker.pending_attack_dmg = 0
    attacker.pending_skill_id = None
    attacker.pending_impact_count = 0
    attacker.pending_impact_total = 1
    # 强制清掉 entity 的 playing flag, 防止后续 tick 还在跑 (即使 seq 没显式 EXIT)
    if attacker.entity is not None:
        attacker.entity.flags &= ~0x20000
        attacker.entity.seq = b''
        attacker.entity.x = 0
        attacker.entity.y = 0
        attacker.entity.z = 0


# 兼容旧 API: 立即结算 (测试 / 必杀沿用)
def strike(battle: "TacticsBattle", attacker: BattleUnit, defender: BattleUnit) -> None:
    if battle.rng.random() < miss_chance(attacker, defender):
        battle.damage_events.append(DamageEvent(0, defender.hp, defender.x, defender.y, miss=True))
        set_reaction(defender, "dodge", attacker)
        battle._log(f"{attacker.name} → {defender.name}: MISS (闪避)")
        return
    raw = attacker.attack - defender.defence + battle.rng.randint(-5, 5)
    dmg = max(1, raw)
    apply_damage(battle, attacker, defender, dmg, "")
