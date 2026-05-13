"""敌方 AI: 选目标 / 走位 / 朝向. 不结算伤害 (走完 + post_enemy_turn 才走 combat)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.battle.data import BattleUnit

if TYPE_CHECKING:
    from core.battle.tactics import TacticsBattle


def take_turn(battle: "TacticsBattle", unit: BattleUnit) -> None:
    """AI: 选目标 → 走 (逻辑坐标立即改, render 由 UI 插值动画) → 攻击留到 post_enemy_turn."""
    targets = [p for p in battle.players if p.alive]
    if not targets:
        return
    target = min(targets, key=lambda p: abs(p.x - unit.x) + abs(p.y - unit.y))

    # 已经能打就不动
    if (target.x, target.y) in battle.q.attack_tiles(unit, unit.x, unit.y):
        face_toward(unit, target)
        battle._pending_enemy_attack = target
        return

    # 朝目标走一步: 取可达格子里 Manhattan 最近的
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
    # 走到了能攻击的位置就计划攻击, 但留到 post_enemy_turn 才打
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
