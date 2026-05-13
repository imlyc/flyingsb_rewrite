"""战场空间查询: 占位 / 通行 / BFS / 攻击范围.

BattleQueries 持有 map + players + enemies 三个稳定引用 (TacticsBattle 构造后不再
重指), 所有方法都基于这些 ref 读取当前战场状态. 把 TacticsBattle 的"地图/位置"
关注点从"回合状态机"里剥离, 让 ai/tactics 等通过 battle.q 访问.
"""

from __future__ import annotations

from collections import deque

from core.battle.data import BattleMap, BattleUnit


class BattleQueries:
    def __init__(self, battle_map: BattleMap,
                 players: list[BattleUnit], enemies: list[BattleUnit]) -> None:
        self.map = battle_map
        self.players = players
        self.enemies = enemies

    @property
    def all_units(self) -> list[BattleUnit]:
        return self.players + self.enemies

    @property
    def alive_units(self) -> list[BattleUnit]:
        return [u for u in self.all_units if u.alive]

    def occupant(self, x: int, y: int, ignore: BattleUnit | None = None) -> BattleUnit | None:
        # 主角尸体保留格子占位 (可复活), 敌人死亡不占格.
        for u in self.all_units:
            if u is ignore:
                continue
            if not u.alive and not u.is_player:
                continue
            if u.x == x and u.y == y:
                return u
        return None

    def is_free(self, x: int, y: int, ignore: BattleUnit) -> bool:
        return self.map.passable(x, y) and self.occupant(x, y, ignore=ignore) is None

    def movement_range(self, unit: BattleUnit) -> set[tuple[int, int]]:
        start = (unit.x, unit.y)
        dist = {start: 0}
        q = deque([start])
        while q:
            x, y = q.popleft()
            d = dist[(x, y)]
            if d >= unit.move:
                continue
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = x + dx, y + dy
                if (nx, ny) in dist:
                    continue
                if not self.map.passable(nx, ny):
                    continue
                if self.occupant(nx, ny, ignore=unit) is not None:
                    continue
                dist[(nx, ny)] = d + 1
                q.append((nx, ny))
        return set(dist.keys())

    def bfs_path(self, unit: BattleUnit, dst: tuple[int, int]) -> list[tuple[int, int]]:
        """从 unit 当前位置到 dst 的最短路径 (不含起点, 含终点). 不通时返回空."""
        start = (unit.x, unit.y)
        if start == dst:
            return []
        parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        q = deque([start])
        while q:
            cur = q.popleft()
            if cur == dst:
                path: list[tuple[int, int]] = []
                node: tuple[int, int] | None = cur
                while node is not None and parent[node] is not None:
                    path.append(node)
                    node = parent[node]
                path.reverse()
                return path
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nxt = (cur[0] + dx, cur[1] + dy)
                if nxt in parent:
                    continue
                if not self.map.passable(*nxt):
                    continue
                if self.occupant(*nxt, ignore=unit) is not None:
                    continue
                parent[nxt] = cur
                q.append(nxt)
        return []

    def attack_tiles(self, unit: BattleUnit, x: int, y: int) -> set[tuple[int, int]]:
        r = unit.attack_range
        out = set()
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                d = abs(dx) + abs(dy)
                if d == 0 or d > r:
                    continue
                nx, ny = x + dx, y + dy
                if self.map.in_bounds(nx, ny):
                    out.add((nx, ny))
        return out

    def attackable_enemies(self, unit: BattleUnit) -> list[BattleUnit]:
        tiles = self.attack_tiles(unit, unit.x, unit.y)
        return [u for u in self.alive_units
                if u.is_player != unit.is_player and (u.x, u.y) in tiles]
