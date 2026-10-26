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


def skill_chance(unit: BattleUnit) -> float:
    """「放招式 (非第 0 招)」倾向: 按原版敌人表出招权重 (+0x50..; exe FUN_004af4bf 按权重挑招),
    = 第 1..3 招权重和 / 总权重. 没有权重数据 → 0.3."""
    w = [max(0, int(x)) for x in (getattr(unit, "move_weights", None) or [])]
    if not w or sum(w) <= 0:
        return 0.3
    return sum(w[1:]) / sum(w)


def take_turn(battle: "TacticsBattle", unit: BattleUnit) -> None:
    """AI: 选目标 → (能放技能就放 / 否则走到能打处) → 攻击留到 post_enemy_turn."""
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
