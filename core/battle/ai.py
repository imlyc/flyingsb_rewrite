"""敌方 AI: 选目标 / 选技能 / 走位 / 朝向. 不结算伤害 (走完 + post_enemy_turn 才走 combat).

真实数据驱动:
  · 敌人技能来自 exe 敌人表 (见 core.character_data.enemy / assets/enemy_table.json → setup.make_enemy_by_type);
    技能的范围/形状走 core.skill_patterns.compute_skill_pattern (反汇编自 exe 的技能 pattern).
  · exe 里的「行动表」见 assets/enemy_actions.json (tools.extract_enemy_actions); 单位 +0xE8 = 当前行动 id.
    当前 remake 用「技能优先」的简化决策: 能打就放技能 (命中数最多者优先) → 否则走到能打处普攻.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.battle.data import BattleUnit

if TYPE_CHECKING:
    from core.battle.tactics import TacticsBattle


def _dist(a: BattleUnit, b: BattleUnit) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def _pick_skill(battle: "TacticsBattle", unit: BattleUnit,
                targets: list[BattleUnit]) -> tuple[int, tuple[int, int],
                                                     set[tuple[int, int]]] | None:
    """在当前站位挑一个「能命中最多玩家」的攻击技能; 没有则 None.

    返回 (skill_id, cursor, damage_tiles). 回血/辅助类技能不在此选 (敌人默认进攻).
    """
    from core.skills import targets_allies
    skills = [s for s in getattr(unit, "known_skills", []) if not targets_allies(s)]
    if not skills:
        return None
    best = None
    saved_facing = unit.facing
    for sid in skills:
        for t in targets:
            cursor = (t.x, t.y)
            # 技能范围随朝向 → 先朝目标再算可达 cursor 集 (取不到就当不可达)
            _face_tile(unit, t.x, t.y)
            try:
                reach = battle.attack_range(unit, sid)
            except Exception:
                reach = set()
            if cursor not in reach:
                continue
            try:
                tiles = battle.damage_range(cursor, unit, sid)
            except Exception:
                continue
            if not tiles:
                continue
            hit = [p for p in targets if (p.x, p.y) in tiles]
            if not hit:
                continue
            score = len(hit)
            if best is None or score > best[0]:
                best = (score, sid, cursor, tiles, unit.facing)
    unit.facing = saved_facing
    if best is None:
        return None
    _, sid, cursor, tiles, _facing = best
    return sid, cursor, tiles


def _face_tile(unit: BattleUnit, tx: int, ty: int) -> None:
    dx, dy = tx - unit.x, ty - unit.y
    if abs(dx) >= abs(dy):
        unit.facing = (1 if dx > 0 else -1 if dx < 0 else unit.facing[0], 0)
    else:
        unit.facing = (0, 1 if dy > 0 else -1)
    unit.reaction_saved_facing = None


def _plan_skill(battle: "TacticsBattle", unit: BattleUnit, target: BattleUnit,
                sid: int, cursor: tuple[int, int],
                tiles: set[tuple[int, int]]) -> None:
    _face_tile(unit, cursor[0], cursor[1])
    battle._pending_enemy_attack = target
    battle._pending_enemy_skill = sid
    battle._pending_enemy_cursor = cursor
    battle._pending_damage_range = tiles if len(tiles) > 1 else None
    battle._pending_damage_falloff = battle.damage_falloff(cursor, unit, sid)


def skill_chance(unit: BattleUnit) -> float:
    """「放招式 (非第 0 招)」倾向: 按原版敌人表出招权重 (+0x50..; exe FUN_004af4bf 按权重挑招),
    = 第 1..3 招权重和 / 总权重. 没有权重数据 → 0.3."""
    w = [max(0, int(x)) for x in (getattr(unit, "move_weights", None) or [])]
    if not w or sum(w) <= 0:
        return 0.3
    return sum(w[1:]) / sum(w)


def take_turn(battle: "TacticsBattle", unit: BattleUnit) -> None:
    """AI 入口: 有敌招表 → exe 选招 (take_turn_moves); 否则旧的技能优先简化决策."""
    if unit.enemy_moves:
        take_turn_moves(battle, unit)
    else:
        _take_turn_legacy(battle, unit)


_FACINGS = ((0, 1), (0, -1), (-1, 0), (1, 0))


def _move_targets(battle: "TacticsBattle", unit: BattleUnit, m) -> list[BattleUnit]:
    from core.battle.status import has_status
    from core.enemy_moves import CAT_HEAL, CAT_STATUS
    if m.target_type == 1:                                   # 对己方
        allies = [e for e in battle.enemies if e.alive]
        if m.category == CAT_HEAL:
            allies = [e for e in allies if e.hp < e.max_hp]
        return allies
    tg = [p for p in battle.players if p.alive]
    if m.category == CAT_STATUS:                             # 已中全部异常的不必再打
        bits = [0x100 << k for k in range(5) if m.flags & (0x100 << k)]
        tg = [p for p in tg if any(not has_status(p, b) for b in bits)]
    return tg


def _best_aim(battle: "TacticsBattle", unit: BattleUnit, tmpl: int, targets: list[BattleUnit]):
    """在 unit 当前格, 4 个朝向里找罩住目标最多的 (光标, 朝向, 命中格→衰减). 返回 (分数, cursor, facing, falloff) 或 None."""
    from core.skill_patterns import (ACTION_TEMPLATES, PATTERN_SET2, _is_fullscreen_pattern,
                                     compute_template_pattern, strike_falloff)
    m = battle.map
    tpos = {(t.x, t.y) for t in targets}
    full = tmpl < len(ACTION_TEMPLATES) and _is_fullscreen_pattern(PATTERN_SET2[ACTION_TEMPLATES[tmpl][1]])
    saved = unit.facing
    best = None
    for f in _FACINGS:
        unit.facing = f
        aim = compute_template_pattern(unit, m, tmpl)
        if not aim:
            continue
        if full:
            c = (unit.x, unit.y) if (unit.x, unit.y) in aim else min(aim)
            fo = {(x, y): 8 for x in range(m.w) for y in range(m.h)}
            score = (len(tpos), 8 * len(tpos))
            if best is None or score > best[0]:
                best = (score, c, f, fo)
            continue
        offs = strike_falloff(unit, (0, 0), tmpl)
        cands = {(tx - ox, ty - oy) for (tx, ty) in tpos for (ox, oy) in offs} & aim
        for c in cands:
            hit = [offs[(tx - c[0], ty - c[1])] for (tx, ty) in tpos if (tx - c[0], ty - c[1]) in offs]
            score = (len(hit), sum(hit))
            if best is None or score > best[0]:
                best = (score, c, f, {(c[0] + ox, c[1] + oy): w for (ox, oy), w in offs.items()})
    unit.facing = saved
    return best


def _walk_to(battle: "TacticsBattle", unit: BattleUnit, dst: tuple[int, int]) -> None:
    if dst == (unit.x, unit.y):
        return
    battle._log(f"{unit.name} 移动到 {dst}")
    path = battle.q.bfs_path(unit, dst)
    unit.move_path = list(path)
    if path:
        ddx, ddy = path[0][0] - unit.x, path[0][1] - unit.y
        if abs(ddx) >= abs(ddy) and ddx != 0:
            unit.facing = (1 if ddx > 0 else -1, 0)
        elif ddy != 0:
            unit.facing = (0, 1 if ddy > 0 else -1)
        unit.reaction_saved_facing = None
    unit.x, unit.y = dst


def take_turn_moves(battle: "TacticsBattle", unit: BattleUnit) -> None:
    """exe FUN_004b1286: 按 core.enemy_moves.move_order 依次试招; 每招在 (原地 + 可走格) 找能罩住目标的站位,
    原地能打就不动, 否则取罩住最多 (同分取走得最近) 的格. 都打不到 → 朝最近的玩家走 (FUN_004b1084).
    站位打分近似 FUN_004aece7 (未逐项还原)."""
    from core.enemy_moves import CAT_SUMMON, move, move_order
    origin = (unit.x, unit.y)
    reach = [p for p in battle.q.movement_range(unit) | {origin} if p == origin or battle.q.occupant(*p) is None]
    reach.sort(key=lambda p: (abs(p[0] - origin[0]) + abs(p[1] - origin[1]), p))
    for mid in move_order(battle, unit):
        m = move(mid)
        if m.category == CAT_SUMMON:
            continue                                         # 召唤 (未做)
        targets = _move_targets(battle, unit, m)
        if not targets:
            continue
        best = None
        for pos in reach:
            unit.x, unit.y = pos
            r = _best_aim(battle, unit, m.template, targets)
            if r is not None and (best is None or r[0] > best[0][0]):
                best = (r, pos)
            if pos == origin and r is not None:
                break                                        # 原地能打: 不动
        unit.x, unit.y = origin
        if best is None:
            continue
        (_, cursor, facing, fo), pos = best
        _walk_to(battle, unit, pos)
        unit.facing = facing
        unit.reaction_saved_facing = None
        if unit.move_path:
            unit.post_move_facing = facing
        tiles = {t for t in fo if battle.map.in_bounds(*t)}
        hit = [t for t in targets if (t.x, t.y) in tiles]
        battle._pending_enemy_attack = hit[0]
        battle._pending_enemy_skill = None
        battle._pending_enemy_move = mid
        battle._pending_enemy_cursor = cursor
        battle._pending_damage_range = tiles if len(tiles) > 1 else None
        battle._pending_damage_falloff = fo if len(tiles) > 1 else None
        battle._log(f"{unit.name} 出招 {m.name} (#{mid}) → {cursor}, 罩住 {len(hit)}")
        return
    # 没招可用: 朝最近的玩家走
    players = [p for p in battle.players if p.alive]
    if not players:
        return
    target = min(players, key=lambda p: _dist(p, unit))
    if reach:
        _walk_to(battle, unit, min(reach, key=lambda p: (abs(p[0] - target.x) + abs(p[1] - target.y))))


def _take_turn_legacy(battle: "TacticsBattle", unit: BattleUnit) -> None:
    """旧 AI: 选目标 → (能放技能就放 / 否则走到能打处) → 攻击留到 post_enemy_turn."""
    targets = [p for p in battle.players if p.alive]
    if not targets:
        return
    target = min(targets, key=lambda p: _dist(p, unit))

    # 是否"愿意"放技能: 命中多个目标时必定放, 否则按行为组倾向掷骰
    pick = _pick_skill(battle, unit, targets)
    if pick is not None:
        sid, cursor, tiles = pick
        hits = len([p for p in targets if (p.x, p.y) in tiles])
        if hits >= 2 or battle.rng.random() < skill_chance(unit):
            _plan_skill(battle, unit, target, sid, cursor, tiles)
            battle._log(f"{unit.name} 施放技能 (id {sid}) → {cursor}")
            return

    # 2) 已经能普攻就不动
    if (target.x, target.y) in battle.q.attack_tiles(unit, unit.x, unit.y):
        face_toward(unit, target)
        battle._pending_enemy_attack = target
        return

    # 3) 朝目标走一步: 取可达格子里 Manhattan 最近的
    reachable = battle.q.movement_range(unit)
    cands = [(x, y) for (x, y) in reachable
             if (x, y) == (unit.x, unit.y) or battle.q.occupant(x, y) is None]
    best = min(cands, key=lambda p: abs(p[0] - target.x) + abs(p[1] - target.y))
    if best != (unit.x, unit.y):
        battle._log(f"{unit.name} 移动到 {best}")
        # 计算真实路径让 render 沿格逐步走 (避免两轴并行 lerp 出 45° 飞行)
        path = battle.q.bfs_path(unit, best)
        unit.move_path = list(path)
        # 朝向 = 第一段方向
        if path:
            step0 = path[0]
            ddx = step0[0] - unit.x
            ddy = step0[1] - unit.y
            if abs(ddx) >= abs(ddy) and ddx != 0:
                unit.facing = (1 if ddx > 0 else -1, 0)
            elif ddy != 0:
                unit.facing = (0, 1 if ddy > 0 else -1)
            unit.reaction_saved_facing = None    # 同 face_toward, 防 reaction 恢复覆盖
        unit.x, unit.y = best

    # 4) 移动后: 优先技能 (同样按行为组倾向), 否则普攻
    pick = _pick_skill(battle, unit, targets)
    if pick is not None:
        sid, cursor, tiles = pick
        hits = len([p for p in targets if (p.x, p.y) in tiles])
        if hits >= 2 or battle.rng.random() < skill_chance(unit):
            _plan_skill(battle, unit, target, sid, cursor, tiles)
            if unit.move_path:
                unit.post_move_facing = unit.facing
            battle._log(f"{unit.name} 移动后施放技能 (id {sid})")
            return
    if target.alive and (target.x, target.y) in battle.q.attack_tiles(unit, unit.x, unit.y):
        face_toward(unit, target)
        # 移动期间 render 会把 facing 改成最后一段移动方向; 标记一下让 UI 走完路径后还原
        if unit.move_path:
            unit.post_move_facing = unit.facing
        battle._pending_enemy_attack = target


def face_toward(unit: BattleUnit, target: BattleUnit) -> None:
    """让 unit 朝向 target 所在格 (用于攻击前).
    清掉 reaction_saved_facing — 若 unit 还有未结束的受击反应,
    防止反应结束时把 facing 恢复成旧值, 覆盖 AI 设的攻击朝向.
    """
    dx = target.x - unit.x
    dy = target.y - unit.y
    if abs(dx) >= abs(dy):
        unit.facing = (1 if dx > 0 else -1 if dx < 0 else unit.facing[0], 0)
    else:
        unit.facing = (0, 1 if dy > 0 else -1)
    unit.reaction_saved_facing = None
