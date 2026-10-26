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


def push_damage_event(battle, unit, ev: "DamageEvent", counts: bool = True) -> None:
    """记事件 (场景/测试读) + 立即生成原版式飘字数字实体 (core.battle.float_digits; 无 engine 的假 battle 跳过).
    heal (回复/MP 回复) = 白字一起下落; 伤害/MISS/MP 吸取 = 红字逐位弹跳. counts=False: 不计入回合门控 (见 float_digits)."""
    battle.damage_events.append(ev)
    from core.battle.float_digits import spawn_float
    spawn_float(battle, unit, None if ev.miss else ev.damage, heal=bool(ev.heal), counts=counts)

# 玩家普攻音效 (char_id → (起手/挥舞音, 命中音/swing); exe 玩家攻击 wrapper FUN_004f3230..975c).
# 起手音在挥舞帧 (近似在攻击开始播); 命中音在 IMPACT 播 (= DAT_006566c0). 全局 sound_id.
PLAYER_ATTACK_SOUNDS: dict[int, tuple[int, int]] = {
    0: (0xb9, 0xbd), 1: (0xb9, 0xbf), 2: (0xb9, 0xbf),          # 孙悟空 3 形态 (命中 0xbf=191)
    3: (0xd5, 0xbd), 4: (0xd5, 0xbd), 5: (0xd5, 0xbd), 6: (0xd5, 0xbd), 7: (0xd5, 0xbd),
    # cid 8 蒙面人: 改用他的**刀刃音**(技能里用的 0x104 挥砍 E092 + 0x105 命中 E093), 不用 wrapper
    # 默认 0xd3(211 闷响). = "武器攻击音" 思路 (用户). 其它 cid 暂留 wrapper 默认, 待逐个校.
    8: (0x104, 0x105), 9: (0xd3, 0xbd), 10: (0xd3, 0xbd), 11: (0xd3, 0xbd),
    12: (0xd3, 0xbd), 13: (0xd3, 0xbd), 14: (0xd3, 0xbd), 15: (0xd3, 0xbd),
}
PLAYER_MELEE_SWING_SOUND = 0xbd  # 189, char_id 不明时的默认命中音


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
                 defender: BattleUnit, dmg: int, label: str,
                 face_attacker: bool = True) -> None:
    # face_attacker=False (范围/召唤技能): 受击保持原朝向, 不转向攻击者.
    # 逻辑 hp 立即扣 (AI/胜负判定要真值); 但**显示 hp + 虚弱/死亡视觉**延迟到结算 (原版语义):
    # shown_hp_override = 受击前旧值 → HUD 滞后; settle_pending=True → 抑制虚弱/死亡视觉.
    # 结算时机: 单体/同时 AOE = 该飘字进 flash (update._tick_settlement); 大金刚 = 全砸完批量.
    old_hp = defender.hp
    defender.hp = max(0, old_hp - dmg)
    # 紫河: 被类型标志 0x2000000 的敌人打中且未倒 → 待变身 (exe FUN_004a6efe 置 DAT_007e2d4c)
    from core.battle import energy
    energy.on_hit(attacker, defender)           # 被敌人命中 → SG +1
    z = getattr(defender, 'zihe', None)
    if z is not None and not z['transformed'] and defender.hp > 0 and (attacker.type_flags & 0x2000000):
        z['pending'] = True
    defender.shown_hp_override = old_hp
    defender.settle_pending = True
    push_damage_event(battle, defender, DamageEvent(dmg, defender.hp, defender.x, defender.y))
    if not getattr(attacker, 'suppress_hit_reaction', False):
        set_reaction(defender, "hit", attacker if face_attacker else None)
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
    if getattr(attacker, 'suppress_hit_fx', False):
        return    # 破天舞等: 命中不放 ef010 红刺 / et00 斩击 (视觉由技能自身特效负责)
    from core.hit_effect_seq import HIT_EFFECT_JITTER_PX, HIT_EFFECT_Y_BASELINE_PX
    from core.skill_seq import has_skill_impact_extra, skill_impact_extra_seq
    from core.sprites.base import TILE_W, TILE_H
    style = None
    if attacker.pending_skill_id is None and attacker.is_player and attacker.attack_cur is not None:
        from core.normal_attack import entry as _na_entry
        fx = _na_entry(attacker.attack_cur).fx
        style = fx.upper() if fx else None
    elif attacker.pending_skill_id is None and not attacker.is_player:
        from core.enemy_moves import hit_style
        style = hit_style(getattr(attacker, 'pending_enemy_move', None))
    specs = hit_effect_specs(defender, attacker.name, style)
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


def hit_effect_specs(defender: BattleUnit, attacker_name: str | None, style: str | None = None) -> list:
    """命中产生的特效 spec 列表 (et00 紫星/长椭圆 + ef010 红刺). 供 _emit_hit_effect 及召唤技
    (如月兔累积受击特效) 共用 — 受击特效"放哪些"是一处真值. hit-fx 朝向 = victim 原朝向反向.
    style: 普攻表项的命中特效 ('STARBURST'/'OVAL'/'CLAW'), None = 按角色旧规则."""
    from core.hit_effect_seq import pick_hit_effects
    ef_facing = (-defender.facing[0], -defender.facing[1])
    return pick_hit_effects(attacker_name, None, ef_facing, style)


def _spawn_effect_entity(battle: "TacticsBattle", world_x: int, world_y: int, spec,
                         *, think_fn=None, persist: bool = False, draw_order: int = 0):
    """通用 effect entity spawn: 跟原版 FUN_004d0c90 blood_spawn 同套路.
    spawn anim_engine entity → 设世界坐标 → attach_seq 跑 FM op 字节码. 返回 entity.
    EXIT op 自然结束后 playing flag 自动落下, render 端跳过该 entity (= 一次性, engine 回收).
    persist=True (+ think_fn 豁免 sweep): seq 播完定格仍渲染 (累积不消失, 调用方负责销毁)."""
    e = battle.engine.spawn(think_fn=think_fn)
    e.x = world_x << 16
    e.y = world_y << 16
    e.z = 0
    e.user_data['kind'] = 'hit_effect'
    e.user_data['atlas_key'] = spec.atlas_key
    if persist:
        e.user_data['projectile'] = True     # 播完定格仍渲染
    if draw_order:
        e.user_data['draw_order'] = draw_order
    battle.engine.attach_seq(e, spec.to_bytecode())
    return e


def strike_skill(battle: "TacticsBattle", attacker: BattleUnit, defender: BattleUnit) -> None:
    # 必杀不能被闪避, 强制重击表现 (技能不走 attack_seq, 立即生效)
    raw = attacker.attack - defender.defence + battle.rng.randint(-5, 5)
    dmg = max(1, raw * 2)
    defender.hp = max(0, defender.hp - dmg)
    push_damage_event(battle, defender, DamageEvent(dmg, defender.hp, defender.x, defender.y))
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
    # 普攻音效: exe 玩家攻击 wrapper 按 char_id 配 (PLAYER_ATTACK_SOUNDS). 命中音(swing)在攻击开始
    # 设、IMPACT 播; 挥砍/斩击音在挥刀帧的 seq 信号播 (与挥刀同步) —— 该信号因 char_id 组而异:
    # cid 0-7 组=jump -1000, cid 8-15 组=jump -1001 (exe wrapper FUN_004f3230 vs 94a0). 见 tactics 信号路由.
    # 技能/敌人不在这里设 (swing 复位 -1).
    attacker.pending_draw_sound = -1
    na_entry = None
    if skill_id is None and attacker.is_player and attacker.attack_cur is not None:
        from core.normal_attack import entry as _na_entry
        na_entry = _na_entry(attacker.attack_cur)
        from core.ranged_attack import handles as _ra_handles
        if na_entry.kind != 'doit' and not _ra_handles(na_entry.idx):
            na_entry = None
    if na_entry is not None:
        # 普攻表项 (core.normal_attack): 挥击音在其 seq 信号播, 命中音登记 (0 = 攻击开始就登记)
        battle.engine.swing_sound = na_entry.hit[0] if na_entry.hit else -1
        attacker.pending_draw_sound = na_entry.swing[0] if na_entry.swing else -1
        attacker.pending_draw_signal = na_entry.swing[1] if na_entry.swing else -1
    elif skill_id is None and attacker.is_player:
        from core.character_sprites import char_id_for
        cid = char_id_for(attacker.name)
        draw, swing = PLAYER_ATTACK_SOUNDS.get(
            cid if cid is not None else -1, (-1, PLAYER_MELEE_SWING_SOUND))
        battle.engine.swing_sound = swing
        attacker.pending_draw_sound = draw if draw is not None else -1
        attacker.pending_draw_signal = -1000 if (cid is not None and cid < 8) else -1001
    elif skill_id is None and _enemy_doit(attacker) is not None:
        # 敌招 DOIT_melee (core.enemy_moves): 挥击/命中音都在 exe seq 里 (op 0x13 设命中音, IMPACT 播)
        battle.engine.swing_sound = -1
    elif skill_id is None and attacker.enemy_moves:
        # 敌人普攻 = 招式表第 0 项: exe 处理函数里 play 的挥击音 + 登记的命中音 (core.battle.exe_sounds)
        from core.battle.exe_sounds import enemy_move_attack_sounds
        draw, swing = enemy_move_attack_sounds(attacker.enemy_moves[0])
        battle.engine.swing_sound = swing if swing >= 0 else PLAYER_MELEE_SWING_SOUND
        attacker.pending_draw_sound = draw
        attacker.pending_draw_signal = -1000
    else:
        battle.engine.swing_sound = -1
        if skill_id is not None:
            # 技能起手音 (exe dispatcher case 10 挂 cast seq 时 FUN_00416311); 挥击/命中音走 seq 信号
            # (core.skill_seq.SKILL_SIGNAL_SOUNDS, tactics._on_anim_signal 路由).
            from core.skill_seq import SKILL_START_SOUNDS
            snd = SKILL_START_SOUNDS.get(skill_id, -1)
            if snd >= 0:
                battle.engine._emit('sound_play', None, snd)
    attacker.pending_attack_target = defender
    attacker.pending_attack_skill = skill_id is not None
    attacker.pending_skill_id = skill_id
    attacker.pending_attack_cursor = cursor if cursor is not None else (defender.x, defender.y)
    attacker.pending_attack_kind = ""
    attacker.pending_attack_dmg = 0
    attacker.pending_impact_count = 0
    # 数 seq 里 IMPACT 总数, 给 apply_pending_attack 判断"是否最后一段"
    seq_tuples = None
    ra = False
    if na_entry is not None:
        from core.ranged_attack import handles as _ra_handles, cast_seq as _ra_cast
        if _ra_handles(na_entry.idx):
            seq_tuples, ra = _ra_cast(na_entry.idx, attacker.facing), True
        else:
            from core.normal_attack import seq_for as _na_seq
            seq_tuples = _na_seq(na_entry.idx, attacker.facing)
    enemy_doit = _enemy_doit(attacker) if skill_id is None else None
    if seq_tuples is None and enemy_doit is not None:
        from core.enemy_moves import seq_for as _em_seq
        seq_tuples = _em_seq(enemy_doit, attacker.facing)
    if seq_tuples is None:
        seq_tuples = attack_seq_for(attacker.name, attacker.facing, skill_id)
    attacker.pending_impact_total = max(1, sum(1 for t in seq_tuples
                                               if t[0] == 'impact' or (t[0] == 'jump' and t[1] == -100)))
    # 创建/复用 entity, 关联回 BattleUnit (signal handler 用)
    if attacker.entity is None:
        attacker.entity = battle.engine.spawn()
    attacker.entity.x = 0
    attacker.entity.y = 0
    attacker.entity.z = 0
    # 清掉上一次攻击残留的 render snapshot (_move_start_*, _fm_total_ticks 等),
    # 否则新攻击第 1 帧会按旧 snapshot 算 MOVE lerp, 出现瞬移+退回的鬼畜.
    attacker.entity.user_data = {'unit': attacker}
    if na_entry is not None or enemy_doit is not None:
        attacker.entity.user_data['global_atlas'] = True     # exe 原 seq: fm 槽号是全局图集号 (渲染不走 ATK_A/B/C 抽象槽)
        # seq 以 move 开头 (如孙悟空拳 0x670a20 先 move 1t): 第一个帧 op 之前 exe 仍显示待机姿 (实录 na0_00)
        pre = 0
        for t in seq_tuples:
            if t[0] in ('fm', 'idle', 'fm_mode1'):
                break
            if t[0] == 'move':
                pre += t[-1]
        if pre:
            attacker.entity.user_data['idle_until_tick'] = battle.engine._tick_id + pre + 1
    # 施法姿保持 (见 BattleUnit.cast_hold): 有帧 op 的 seq 播完后停在最后一帧直到攻击收尾 (= exe 清 0x10000).
    hold = any(t[0] in ('fm', 'fm_mode1', 'idle') for t in seq_tuples)
    # tuple seq → bytecode 后挂载. attach_seq 自动跑到第一个阻塞 op.
    seq_bc = tuple_to_bytecode(seq_tuples)
    from core.skill_seq import MELEE_TEMPLATE_SKILLS
    if skill_id is not None and skill_id not in MELEE_TEMPLATE_SKILLS:
        # 技能: 先战场暗化 (exe dispatcher state 0 的调色板渐变, ≈480ms) 再挂 cast seq (case 10); DOIT_melee 模板技能无渐变
        from core.battle.skill_dim import start_skill_dim
        ent = attacker.entity

        def _attach():
            battle.engine.attach_seq(ent, seq_bc)
            attacker.cast_hold = hold
            from core.skill_seq import SKILL_ATTACH_HOOKS
            hook = SKILL_ATTACH_HOOKS.get(skill_id)
            if hook is not None:
                hook(battle, attacker)
        start_skill_dim(battle, _attach, skill_id)
    else:
        battle.engine.attach_seq(attacker.entity, seq_bc)
        attacker.cast_hold = hold
        if ra:
            from core.ranged_attack import on_attach as _ra_attach
            _ra_attach(battle, attacker)          # 远程普攻 / 紫河第三形态: 协调实体 (core.ranged_attack)


def _enemy_doit(attacker: BattleUnit) -> int | None:
    """敌人本次出招若是 DOIT_melee 类 (有 exe seq 表) → 招式 id, 否则 None."""
    if attacker.is_player:
        return None
    mid = getattr(attacker, 'pending_enemy_move', None)
    if mid is None:
        return None
    from core.enemy_moves import move
    m = move(mid)
    return mid if m is not None and m.kind.startswith('doit') else None


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
        from core.skill_seq import is_heal_skill, SKILL_STATUS_EFFECTS, SKILL_MP_DRAIN, has_impact_spawn
        if sid in SKILL_STATUS_EFFECTS and not attacker.pending_impact2:
            _apply_status_skill(battle, attacker)
            if not has_impact_spawn(sid):
                return
        elif sid in SKILL_STATUS_EFFECTS:
            return                       # 状态技能的演出收尾 (IMPACT_2): 不扣血
        if sid in SKILL_MP_DRAIN:
            if attacker.pending_impact2:
                _apply_mp_drain(battle, attacker, SKILL_MP_DRAIN[sid])
                return
        elif is_heal_skill(sid) and (attacker.pending_impact2 or not has_impact_spawn(sid)):
            _apply_heal(battle, attacker)       # 生命之火: 光球→火爆 (IMPACT 时 spawn) 播完才回血 (IMPACT_2)
            return
    # B 类技能: IMPACT 不直接结算伤害, 而是 spawn 投射物 (think_fn 物理 → 落地后发 SIG_IMPACT_2 才结算)
    if sid is not None and not attacker.pending_impact2:
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
    if sid is None and not attacker.is_player and _apply_enemy_special(battle, attacker):
        return
    dmg_tiles = getattr(battle, '_pending_damage_range', None)
    if dmg_tiles:
        for (x, y) in dmg_tiles:
            t = battle.q.occupant(x, y)
            if t is None or not t.alive or t.is_player == attacker.is_player:
                continue
            _roll_damage_one(battle, attacker, t, face_attacker=False)  # 范围攻击不转向
        return
    target = attacker.pending_attack_target
    if target is None or not target.alive:
        return
    _roll_damage_one(battle, attacker, target)


def _range_units(battle: "TacticsBattle", attacker: BattleUnit, same_side: bool) -> list[BattleUnit]:
    dmg_tiles = getattr(battle, '_pending_damage_range', None)
    cells = dmg_tiles or ([] if attacker.pending_attack_target is None
                          else [(attacker.pending_attack_target.x, attacker.pending_attack_target.y)])
    out = []
    for (x, y) in cells:
        t = battle.q.occupant(x, y)
        if t is not None and t.alive and (t.is_player == attacker.is_player) == same_side:
            out.append(t)
    return out


def _apply_enemy_special(battle: "TacticsBattle", attacker: BattleUnit) -> bool:
    """敌招类别 1 加异常 / 2 回复己方 / 4 自爆 (core.enemy_moves); 类别 0 伤害 → False 走默认."""
    from core import enemy_moves as EM
    m = EM.move(getattr(attacker, 'pending_enemy_move', None))
    if m is None or m.category == EM.CAT_DAMAGE:
        return False
    if m.category == EM.CAT_HEAL:
        for t in _range_units(battle, attacker, same_side=True):
            amt = EM.heal_amount(battle, attacker, m, _falloff(battle, t))
            before = t.hp
            t.hp = min(t.max_hp, t.hp + amt)
            push_damage_event(battle, t, DamageEvent(t.hp - before, t.hp, t.x, t.y, heal=True))
            _emit_life_fire_effect(battle, t)
            battle.engine._emit('sound_play', None, 301)
            battle._log(f"{attacker.name} → {t.name}: 回复 {t.hp - before} HP")
        return True
    if m.category == EM.CAT_STATUS:
        for t in _range_units(battle, attacker, same_side=False):
            got = EM.resolve_status(battle, attacker, t, m)
            if got:
                set_reaction(t, "hit", None)
                battle._log(f"{attacker.name} → {t.name}: 中了 {[hex(b) for b in got]}")
            else:
                _miss(battle, attacker, t, False)
        return True
    if m.category == EM.CAT_FIXED:
        dmg = EM.SELF_DESTRUCT_DMG.get(attacker.enemy_type, 44)
        for t in _range_units(battle, attacker, same_side=False):
            apply_damage(battle, attacker, t, dmg, "", face_attacker=False)
        attacker.hp = 0
        battle._log(f"{attacker.name} 自爆")
        return True
    return False


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
        # 范围攻击 (dmg_tiles) 受击不转向; 单点保持转向攻击者.
        set_reaction(t, "hit", attacker if not dmg_tiles else None)
        _emit_hit_effect(battle, attacker, t)


def _apply_heal(battle: "TacticsBattle", attacker: BattleUnit) -> None:
    """回血技能结算: 给 _pending_damage_range (or pending_attack_target) 的友军回 HP.
    生命之火 esum1 burst effect 在 target 上 spawn (视觉)."""
    from core.battle.formulas import heal_amount
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
        amt = heal_amount(battle, attacker, attacker.pending_skill_id, _falloff(battle, t))   # exe act==2 case 1
        before = t.hp
        t.hp = min(t.max_hp, t.hp + amt)
        healed = t.hp - before
        push_damage_event(battle, t, DamageEvent(healed, t.hp, t.x, t.y, heal=True))
        if attacker.pending_skill_id != 0x15:
            _emit_life_fire_effect(battle, t)       # 生命之火的火爆已由 core.sam_skills 在光球到达时放
        battle.engine._emit('sound_play', None, 301)    # exe FUN_004fe111 case -210: 每 victim 回血数字旁播 0x12d
        battle._log(f"{attacker.name} → {t.name}: 回复 {healed} HP ({t.hp}/{t.max_hp})")


def _ally_targets(battle: "TacticsBattle", attacker: BattleUnit) -> list[BattleUnit]:
    """_pending_damage_range (or pending_attack_target) 里的我方存活单位."""
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
    return targets


def _apply_status_skill(battle: "TacticsBattle", attacker: BattleUnit) -> None:
    """状态类技能 (斗轉星移/返荷杖...): 给范围内我方加状态位 + 回合计数 (exe FUN_004a6efe skill switch)."""
    from core.skill_seq import SKILL_STATUS_EFFECTS
    from core.battle.status import apply_status
    from core.skills import get_skill_name
    bit, turns = SKILL_STATUS_EFFECTS[attacker.pending_skill_id]
    for t in _ally_targets(battle, attacker):
        apply_status(t, bit, turns)
        battle._log(f"{attacker.name} → {t.name}: {get_skill_name(attacker.pending_skill_id)} 生效")


def mp_drain_amount(battle: "TacticsBattle", attacker: BattleUnit, target: BattleUnit,
                    mode: str) -> int:
    """化精 / 吸精 的量 (core.battle.formulas.mp_drain = exe FUN_004a6efe act==2 case 3)."""
    from core.battle.formulas import mp_drain
    return mp_drain(battle, attacker, target, attacker.pending_skill_id)


def _apply_mp_drain(battle: "TacticsBattle", attacker: BattleUnit, mode: str) -> None:
    """化精大法 (zero: 敌 MP -= amt, 下限 0) / 吸精大法 (absorb: 敌 MP -= amt, 施法者 MP += amt)."""
    from core.skills import get_skill_name
    total = 0
    for t in _enemy_targets(battle, attacker):
        amt = mp_drain_amount(battle, attacker, t, mode)
        amt = min(amt, t.mp) if mode == 'absorb' else amt
        t.mp = max(0, t.mp - amt)
        push_damage_event(battle, t, DamageEvent(amt, t.mp, t.x, t.y, mp=True))
        battle._log(f"{attacker.name} → {t.name}: {get_skill_name(attacker.pending_skill_id)} MP -{amt} ({t.mp})")
        total += amt
    if mode == 'absorb' and total > 0:
        attacker.mp = min(attacker.max_mp, attacker.mp + total)
        # exe 吸精 -200: 敌红字 + 施法者白字 (FUN_004d074e) 同 tick 生成, 但 +0x3e 只 +1 → 白字 (56t 才落定) 不拖回合 (实录 idle 在红字 -20 后)
        push_damage_event(battle, attacker, DamageEvent(total, attacker.mp, attacker.x, attacker.y, heal=True, mp=True), counts=False)
        battle._log(f"{attacker.name}: MP +{total} ({attacker.mp}/{attacker.max_mp})")


def _enemy_targets(battle: "TacticsBattle", attacker: BattleUnit) -> list[BattleUnit]:
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
    return targets


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
    battle.engine._emit('sound_play', None, 299)        # exe FUN_004fdfbf: esum1 burst spawn 播 0x12b


def _falloff(battle: "TacticsBattle", target: BattleUnit) -> int:
    """范围衰减权重 (8 = 满额): 确认攻击时由 tactics 记下的 {格: 权重} (伤害 pattern 字节高 4 位)."""
    m = getattr(battle, '_pending_damage_falloff', None)
    if m:
        return m.get((target.x, target.y), 8)
    return 8


def roll_outcome(battle: "TacticsBattle", attacker: BattleUnit, target: BattleUnit):
    """掷一次命中/暴击/伤害 (core.battle.formulas = exe FUN_004a6efe). 同阵营之间 (无 exe 分支) → None."""
    from core.battle import formulas as F
    fo = _falloff(battle, target)
    sid = attacker.pending_skill_id
    if attacker.is_player and not target.is_player:
        if sid is None:
            from core.normal_attack import entry
            idx = getattr(attacker, 'attack_cur', None)
            return F.player_normal(battle, attacker, target, entry(idx).flags if idx is not None else 0x4001, fo)
        return F.player_skill(battle, attacker, target, sid, fo)
    if not attacker.is_player and target.is_player:
        move = getattr(attacker, 'pending_enemy_move', None)
        if move is None and attacker.enemy_moves:
            move = attacker.enemy_moves[0]
        return F.enemy_attack(battle, attacker, target, move, fo)
    return None


def preroll(battle: "TacticsBattle", attacker: BattleUnit, target: BattleUnit):
    """提前掷骰 (演出中途就要知道闪不闪, 如紫河第三形态); 之后 _roll_damage_one 用同一结果."""
    out = roll_outcome(battle, attacker, target)
    if out is not None:
        battle.__dict__.setdefault('_prerolled', {})[id(target)] = out
    return out


def _roll_damage_one(battle: "TacticsBattle", attacker: BattleUnit, target: BattleUnit,
                     face_attacker: bool = True) -> None:
    """对单个 target 结算一次 (命中/闪避 + 伤害 + 反应动画). 公式见 core.battle.formulas.
    face_attacker=False (范围/召唤技能): 受击保持原朝向不转向."""
    from core.battle.status import has_status, clear_status, ST_DOUZHUAN, ST_FANHE, ST_HUAJING
    pre = getattr(battle, '_prerolled', None)
    out = pre.pop(id(target), None) if pre else None
    if out is None:
        out = roll_outcome(battle, attacker, target)
    if out is None:                          # 同阵营 (无 exe 分支): 旧占位
        if battle.rng.random() < miss_chance(attacker, target):
            _miss(battle, attacker, target, face_attacker)
            return
        apply_damage(battle, attacker, target, max(1, attacker.attack - target.defence), "",
                     face_attacker=face_attacker)
        return
    if not out.hit:
        _miss(battle, attacker, target, face_attacker)
        _maybe_counter(battle, attacker, target, out)     # exe: 反击判定在命中/落空汇合后 → 闪开也能反击 (原版实录)
        return
    dmg = out.dmg
    label = "暴击 " if out.crit else ""
    if target.is_player and not attacker.is_player:
        if has_status(target, ST_DOUZHUAN):
            dmg = 0                          # 斗轉星移: 伤害归零 (仍算命中, 飘 0)
        if out.magic and has_status(target, ST_HUAJING):
            # 化精為氣 (0x80000, 一次性): 法术伤害归零, MP 型角色回 招式扣 MP / 目标数
            clear_status(target, ST_HUAJING)
            dmg = 0
            from core.battle import energy, formulas as F
            if energy.energy_type(target) == energy.ENERGY_MP:
                move = getattr(attacker, 'pending_enemy_move', None) or (attacker.enemy_moves or [None])[0]
                n = max(1, len(getattr(battle, '_pending_targets', []) or [target]))
                gain = min(F.enemy_move(move)['mp_cost'] // n if move is not None else 0,
                           max(0, target.max_mp - target.mp))
                target.mp += gain
                push_damage_event(battle, target, DamageEvent(gain, target.mp, target.x, target.y, heal=True, mp=True))
                battle._log(f"{target.name}: 化精為氣 → MP +{gain}")
        if has_status(target, ST_FANHE):
            # 返荷杖: 本人不受伤, 攻击者扣 自己的攻击力 (法术为法攻) ×暴击 ×衰减 (exe local_250)
            apply_damage(battle, attacker, target, 0, "", face_attacker=face_attacker)
            apply_damage(battle, target, attacker, out.reflect, "返荷")
            return
    apply_damage(battle, attacker, target, dmg, label, face_attacker=face_attacker)
    if not out.magic and dmg > 0:
        clear_status(target, 0x200)          # 物理命中打醒睡眠 (exe 清 0x200 + 计数)
    if out.status_chance and target.alive:
        from core.normal_attack import roll_status
        roll_status(battle, attacker, target, out.status_chance)
    _maybe_counter(battle, attacker, target, out)


def _attack_flags(attacker: BattleUnit) -> int | None:
    """本次攻击的招式 flags (普攻条目 / 敌招); 技能 → None (技能不触发反击)."""
    if attacker.pending_skill_id is not None:
        return None
    if attacker.is_player:
        from core.normal_attack import entry
        idx = getattr(attacker, 'attack_cur', None)
        return entry(idx).flags if idx is not None else None
    from core.battle.formulas import enemy_move, F_DEFAULT_ENEMY
    move = getattr(attacker, 'pending_enemy_move', None)
    if move is None and attacker.enemy_moves:
        move = attacker.enemy_moves[0]
    return enemy_move(move)['flags'] if move is not None else F_DEFAULT_ENEMY


def _maybe_counter(battle: "TacticsBattle", attacker: BattleUnit, target: BattleUnit, out) -> None:
    """exe 反击: 普攻 / 可反击敌招 (0x10) 命中后, 正前方的目标按概率反打 (伤害此刻算定, 动画在本次攻击演完后,
    tactics.advance_turn_when_ready). 反击本身不再触发反击; 一次行动最多一个反击者."""
    from core.battle import formulas as F
    if getattr(attacker, 'is_countering', False) or getattr(battle, '_pending_counter', None):
        return
    if attacker.is_player == target.is_player:
        return
    flags = _attack_flags(attacker)
    if flags is None or not F.counter_check(attacker, target, out, flags):
        return
    dmg, crit = F.counter_damage(battle, target, attacker)
    battle._pending_counter = dict(unit=target, target=attacker, dmg=dmg, crit=crit)
    battle._log(f"{target.name} 反击! ({dmg}{' 会心' if crit else ''})")


def _miss(battle: "TacticsBattle", attacker: BattleUnit, target: BattleUnit, face_attacker: bool) -> None:
    push_damage_event(battle, target, DamageEvent(0, target.hp, target.x, target.y, miss=True))
    set_reaction(target, "dodge", attacker if face_attacker else None)
    battle._log(f"{attacker.name} → {target.name}: MISS (闪避)")


def clear_pending_attack(attacker: BattleUnit) -> None:
    attacker.cast_hold = False
    attacker.suppress_hit_reaction = False
    attacker.suppress_hit_fx = False
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
    _roll_damage_one(battle, attacker, defender)
