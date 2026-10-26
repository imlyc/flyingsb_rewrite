"""敌方 AI 站位 / 朝向 / 光标 = exe FUN_004b1286 及其辅助函数的逐函数移植 (2026-10-26).

反编译: reverse_engineering/enemy_ai.txt + decomp_refs_AI.java 输出 (FUN_004aece7 一族).
exe 方向号 d: 0 上 / 1 下 / 2 左 / 3 右 (DIRS). 动作模板 (0x64458c stride 0x18): +0 flags (bit0 → 瞄准只 1 向,
bit1 → 伤害只 1 向), +4 瞄准 pattern (set1, cell&2), +8 伤害 pattern (set2, cell&4), +0xc/+0x10 方向 0 的光标偏移.

FUN_004b1286 (每个敌人行动):
  洪水 FUN_0049d80a(0x2f3: 墙 + 所有单位挡路, 自己除外) → FUN_004adf85(移动力 = 敌人表 +0x24 / 10) 标可站格;
  招式顺序 (FUN_004af4bf / 4af5d4: MP 够的招; 第一个 flags&1 的优先, 其余按权重无放回抽);
  逐招: 沉默 (0x400) 只能物理招; flags&3 == 0 / 2 → FUN_004af2d6 (2 = 不站在活玩家相邻格);
        == 1 → 招 2 (召唤) 特判, 否则评估**优先招** (FUN_004b0532 回复类); 都不行 → FUN_004b1084 移动.
FUN_004aece7 (攻击招选位):
  FUN_004ada77: 对每个方向 d、每个玩家 p、伤害 pattern(d) 的每个偏移 o → 候选光标 p - o, 同格累加分
    (FUN_004ada1b: 死 0 / 睡·麻痹 2..4 / 其他 3); 随机一个方向 r 的新候选 +rand%3.
  FUN_004ade5f/4adf85/4adff5/4ae20d: 可站格表 (全局 7ea718, 跨回合保留 → battle._ai_stand).
  FUN_004ae39a/4ade85: 瞄准 pattern(d) 转成行 run 表. **exe bug**: run 的右端写在下一个 run 槽里, 结果每个 run
    只剩最左一格 (c0 == c1) — 照搬.
  d 逐个: 4ae486 (可站格 + 瞄准 run 能罩到的格) → 4ae7b2 (罩不到的候选 = -1) → 4ae8bf 取最高分 (初值 = 全局
    0 号项的分, 同分取前) → 4aeb21 列出能瞄到该光标的可站格 (**从 0 号覆盖全局候选表**, 后面方向的候选可能被盖掉,
    照搬) → 取第一个. 总分 = 光标分 + 1 最大的方向 (同分取前).
  方向: 两 pattern 都 4 向 → 站位项的方向; 只伤害 1 向 → 站位项方向; 只瞄准 1 向 → 光标项方向; 都 1 向 → 下.
FUN_004af2d6: 猛撞 (0x46/0x49/0x4c/0x4f): 落点 = 站位 + 2·方向, x 越界 / 有单位 / 洪水不可达 → 放弃该招.
FUN_004b0532 (优先招 = 回复): ai_mode 决定触发条件与打分函数 (FUN_004afbbb + 4af7ba/4af8bc/4af7d0 + 4af7a2/4aface/
  4afb1b/4afb6a); 候选站位用**全局可站格表** (上一次 FUN_004aece7 留下的, 可能是别的敌人的 — exe 原样).
FUN_004b1084: 按 ai_mode 选目标玩家 (FUN_004b0b08), 可站格里 100 - 距离 最大 (FUN_004b0f89, ai_mode≥3 用寻路距离),
  朝向 FUN_004b01a8 (或随机). FUN_0049d1bd: 从目标格沿洪水距离回溯 (上/下/左/右优先) 出路径, 截到移动力.

近似 / 与 exe 不同之处:
  · 候选分数组 (7e65c4) 跨回合残留: battle._ai_ent 保存 (同 exe 全局); 初值 0 (exe BSS).
  · 线性下标越界 (地图边缘左右环绕) 不模拟: 我们的战场 = exe 世界地图的子矩形, exe 环绕落在战场外, 按坐标处理.
  · FUN_004b0532 伤害格数非 1/5/13 时 local_3c 未初始化 → 取 3 (现有回复招都是 1/5/13).
  · FUN_004b01a8 墙项: 我们地图无单向墙/地形位, 每个方向都 +100 (等于没影响); 距离表下标 ≥ 20 读到栈外 → 取 1.
  · 猛撞落点 y 越界 exe 不查 (读到战场外 → 实际不可达), 这里直接放弃.
  · 回复 / 移动 fallback 用的残留可站格可能已被其他单位占了 (exe 会叠人), 这里跳过被占格.
  · 召唤可用槽: exe 复活 1..8 号槽里已死的槽 (牛魔王战预置隐藏的牛寶寶), 我们直接新建, 上限 = 9 - 存活敌人数.
  · 权重 ≤ 0 时 exe 本轮抽签不写顺序 (残留栈值), 这里把剩余招按原序接上.
"""
from __future__ import annotations

from collections import deque
from functools import lru_cache
from typing import TYPE_CHECKING

from core.skill_patterns_data import ACTION_TEMPLATES, PATTERN_SET1, PATTERN_SET2

if TYPE_CHECKING:
    from core.battle.data import BattleUnit
    from core.battle.tactics import TacticsBattle

DIRS = ((0, -1), (0, 1), (-1, 0), (1, 0))          # exe 方向 0 上 1 下 2 左 3 右
DASH_MOVES = (0x46, 0x49, 0x4c, 0x4f)                # 猛撞
SUMMON_MOVE, CALF_TYPE = 2, 0x17                    # 召喚牛寶寶 / 牛寶寶
# 动作模板 flags (exe 0x64458c + t*0x18), 104 项; 只有 bit0 (瞄准单向) / bit1 (伤害单向) 被 AI 用
TEMPLATE_FLAGS = (
    0, 0, 0, 0, 0, 4, 0, 0, 4, 0, 4, 0, 0, 0, 4, 4, 0, 0, 0, 4, 0, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 4, 0, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 4, 4, 0, 0, 4, 4, 0, 0, 0, 4, 0, 0, 0, 4, 0, 0, 4, 0, 1, 0, 0, 0, 0, 0, 0, 0, 4)
# FUN_004b0532: ai_mode → (触发条件, 打分方式, 朝向用 FUN_004b01a8)
HEAL_MODE = {0: (0, 0, False), 1: (1, 1, False), 2: (1, 2, True), 3: (1, 3, True), 4: (1, 4, True), 5: (2, 4, True),
             6: (2, 3, True), 7: (2, 5, True), 8: (3, 4, True), 9: (3, 3, True), 10: (3, 5, True)}
# FUN_004b1084: ai_mode → (选目标方式 FUN_004b0b08, 朝向用 FUN_004b01a8)
MOVE_MODE = {0: (0, False), 1: (1, False), 2: (2, True), 3: (3, True), 4: (4, True), 5: (4, True), 6: (3, True),
             7: (5, True), 8: (4, True), 9: (5, True), 10: (6, True)}
COUNTER_CLASS = (1, 1, 1, 0, 0, 2, 1, 0, 0, 1, 2, 2)  # exe 0x641820[角色号] (FUN_004b0b08 模式 4/5)

# FUN_0049d80a 洪水标志
F_PLAYERS, F_ENEMIES = 0x10, 0x20
FLOOD_TURN = 0x2f3          # FUN_004b1286 开头: 敌我都挡
FLOOD_MOVE = 0x6d2          # FUN_0049d1bd / 4afbbb: 只有玩家挡 (穿过友军)
FLOOD_SUMMON = 0xd2         # 召唤: 只有玩家挡
FLOOD_WALLS = 2             # FUN_004b0ed5: 只看墙


def dir_index(facing: tuple[int, int]) -> int:
    return DIRS.index(facing) if facing in DIRS else 1


def _rot_grid(grid, d: int):
    """FUN_004ad010 的 4 向旋转 (exe 原下标式, 保证行优先扫描顺序一致)."""
    R = range(11)
    if d == 0:
        return [[grid[c][l] for l in R] for c in R]
    if d == 1:
        return [[grid[10 - c][10 - l] for l in R] for c in R]
    if d == 2:
        return [[grid[l][10 - c] for l in R] for c in R]
    return [[grid[10 - l][c] for l in R] for c in R]


@lru_cache(maxsize=None)
def dmg_offsets(tmpl: int, d: int) -> tuple[tuple[int, int], ...]:
    """FUN_004af172: 伤害 pattern(d) 的 cell&4 偏移 (行优先)."""
    if tmpl is None or not 0 <= tmpl < len(ACTION_TEMPLATES):
        return ()
    g = _rot_grid(PATTERN_SET2[ACTION_TEMPLATES[tmpl][1]], d)
    return tuple((l - 5, c - 5) for c in range(11) for l in range(11) if g[c][l] & 4)


@lru_cache(maxsize=None)
def aim_runs(tmpl: int, d: int) -> tuple[tuple[int, int, int], ...]:
    """FUN_004ade85(mask 2) 对瞄准 pattern(d): (行, c0, c1). exe bug: c1 写进下一槽 → 每个 run c1 = c0."""
    if tmpl is None or not 0 <= tmpl < len(ACTION_TEMPLATES):
        return ()
    g = _rot_grid(PATTERN_SET1[ACTION_TEMPLATES[tmpl][0]], d)
    runs: list[tuple[int, int, int]] = []
    for c in range(11):
        prev = False
        for l in range(11):
            cur = bool(g[c][l] & 2)
            if cur and not prev:
                runs.append((c - 5, l - 5, l - 5))     # 连续格只记起点 (右端写到下一槽, 被覆盖)
            prev = cur
    return tuple(runs)


def _incap(u) -> bool:
    return bool(getattr(u, 'status_bits', 0) & 0xa00)


def _active(u) -> bool:
    """status & 0x600a00 == 0: 活着且没睡/麻痹."""
    return u.alive and not _incap(u)


def _md(ax, ay, bx, by) -> int:
    return abs(ax - bx) + abs(ay - by)


def flood(battle, origin: tuple[int, int], flags: int) -> dict[tuple[int, int], int]:
    """FUN_0049d80a: 从 origin BFS 的步数图 (不可达不在表里). 墙 = 地图不可走; 0x10 玩家挡 (含尸体), 0x20 活敌人挡;
    0x200 = origin 格上的单位不算挡路 (origin 本来就是起点, 无影响)."""
    m = battle.map
    blocked = set()
    if flags & F_PLAYERS:
        blocked |= {(p.x, p.y) for p in battle.players}
    if flags & F_ENEMIES:
        blocked |= {(e.x, e.y) for e in battle.enemies if e.alive}
    blocked.discard(origin)
    dist = {origin: 0}
    q = deque([origin])
    while q:
        x, y = q.popleft()
        nd = dist[(x, y)] + 1
        for dx, dy in DIRS:
            n = (x + dx, y + dy)
            if n in dist or n in blocked or not m.passable(*n):
                continue
            dist[n] = nd
            q.append(n)
    return dist


class ExeAI:
    """一次 FUN_004b1286 调用的上下文. exe 全局: 洪水图 7de67c (self.dist), 可站格表 7ea718 (battle._ai_stand),
    候选表 7e65b8.. (battle._ai_ent: [x, y, 方向, 分])."""

    def __init__(self, battle: "TacticsBattle", unit: "BattleUnit"):
        from core.character_data import enemy
        self.b, self.u = battle, unit
        e = enemy(unit.enemy_type) if getattr(unit, 'enemy_type', -1) >= 0 else None
        self.ai_mode = int((e or {}).get('ai_mode', 0) or 0)
        self.rng_move = unit.move
        self.dist: dict = {}
        self.dist_origin = None
        if not hasattr(battle, '_ai_stand'):
            battle._ai_stand = []
        if not hasattr(battle, '_ai_ent'):
            battle._ai_ent = []
        self.start = [0, 0, 0, 0]
        self.cnt = [0, 0, 0, 0]
        self.standable: set = set()

    # ---------- 基础 ----------
    def rand(self, n: int) -> int:
        return self.b.rng.randrange(n)

    def _flood(self, origin, flags) -> None:
        self.dist = flood(self.b, origin, flags)
        self.dist_origin = origin

    def _ent(self, i: int) -> list:
        ent = self.b._ai_ent
        while len(ent) <= i:
            ent.append([0, 0, 0, 0])
        return ent[i]

    def _put(self, i: int, x: int, y: int, d: int, s: int) -> None:
        e = self._ent(i)
        e[0], e[1], e[2], e[3] = x, y, d, s

    @property
    def stand(self) -> list:
        return self.b._ai_stand

    def _occupied_by_other(self, p) -> bool:
        o = self.b.q.occupant(*p)
        return o is not None and o is not self.u

    # ---------- 打分 ----------
    def _score_player(self, p) -> int:
        """FUN_004ada1b."""
        if not p.alive:
            return 0
        if _incap(p):
            return self.rand(3) + 2
        return 3

    # ---------- FUN_004aece7 一族 ----------
    def ada77(self, tmpl: int) -> int:
        self.n4348 = 1 if TEMPLATE_FLAGS[tmpl] & 2 else 4
        players = self.b.players
        total = 0
        if self.n4348 == 1:
            self.start[0], self.cnt[0] = 0, 0
            for p in players:
                for ox, oy in dmg_offsets(tmpl, 0):
                    cx, cy = p.x - ox, p.y - oy
                    for j in range(total):
                        e = self._ent(j)
                        if e[0] == cx and e[1] == cy:
                            e[3] += self._score_player(p)
                            break
                    else:
                        d = self.rand(4)
                        self._put(total, cx, cy, d, self._score_player(p))
                        total += 1
                        self.cnt[0] += 1
            return total
        r = self.rand(4)
        for d in range(4):
            st = total
            self.start[d], self.cnt[d] = st, 0
            for p in players:
                for ox, oy in dmg_offsets(tmpl, d):
                    cx, cy = p.x - ox, p.y - oy
                    for j in range(st, total):
                        e = self._ent(j)
                        if e[0] == cx and e[1] == cy:
                            e[3] += self._score_player(p)
                            break
                    else:
                        self._put(total, cx, cy, d, self._score_player(p))
                        e = self._ent(total)
                        if r == d and e[3] > 0:
                            e[3] += self.rand(3)
                        total += 1
                        self.cnt[d] += 1
        return total

    def adf85(self, rng: int) -> None:
        """可站格. 洪水是 0x6d2/0xd2 (穿友军) 时 exe 会把友军格也算进来 (叠人), 这里排除被别人占的格."""
        self.standable = {c for c, v in self.dist.items()
                          if v >= 0 and (v & 0xff) <= rng and not self._occupied_by_other(c)}

    def adff5_ae20d(self, mode: int) -> None:
        cells = set(self.standable)
        if mode == 1:
            for p in self.b.players:
                if _active(p):
                    for dx, dy in DIRS:
                        cells.discard((p.x + dx, p.y + dy))
        self.b._ai_stand = sorted(cells, key=lambda c: (c[1], c[0]))     # 线性下标顺序

    def _covered(self, run_lists) -> set:
        cov = set()
        for sx, sy in self.stand:
            for runs in run_lists:
                for row, c0, c1 in runs:
                    for k in range(c0, c1 + 1):
                        cov.add((sx + k, sy + row))
        return cov

    def _best_in(self, lo: int, hi: int) -> int:
        """FUN_004ae8bf / 4ae848 / 4b00f6: 初值 = 0 号项的分, 严格大于才换."""
        bi, best = 0, self._ent(0)[3]
        for j in range(lo, hi):
            if self._ent(j)[3] > best:
                bi, best = j, self._ent(j)[3]
        return bi

    def _stand_for_cursor(self, cx, cy, d, runs, k) -> int:
        """FUN_004aeb21 / 4ae936 内层: 能用瞄准 run 罩到 (cx, cy) 的可站格, 从 k 号写起."""
        if not runs:
            return k
        r_first, r_last = runs[0][0], runs[-1][0]
        for sx, sy in self.stand:
            if sy + r_first <= cy <= sy + r_last and sx - 5 <= cx <= sx + 5:
                for row, c0, c1 in runs:
                    if sy + row == cy and sx + c0 <= cx <= sx + c1:
                        self._put(k, sx, sy, d, 1)
                        k += 1
                        self.cnt[d] += 1
                        break
        return k

    def aece7(self, tmpl: int, rng: int, mode: int):
        """返回 (光标, 站位, 方向) 或 None."""
        if self.ada77(tmpl) < 1:
            return None
        n40f0 = 1 if TEMPLATE_FLAGS[tmpl] & 1 else 4
        self.adf85(rng)
        self.adff5_ae20d(mode)
        runs = [aim_runs(tmpl, d) for d in range(n40f0)]
        if self.n4348 == 4 and n40f0 == 4:
            A: list = [None] * 4
            B: list = [None] * 4
            for d in range(4):
                cov = self._covered([runs[d]])
                for j in range(self.start[d], self.start[d] + self.cnt[d]):
                    e = self._ent(j)
                    if (e[0], e[1]) not in cov:
                        e[3] = -1
                bi = self._best_in(self.start[d], self.start[d] + self.cnt[d])
                if self._ent(bi)[3] > 0:
                    A[d] = tuple(self._ent(bi))
                    self.start[d], self.cnt[d] = 0, 0
                    if self._stand_for_cursor(A[d][0], A[d][1], d, runs[d], 0) > 0:
                        bi = self._best_in(self.start[d], self.start[d] + self.cnt[d])
                        if self._ent(bi)[3] > 0:
                            B[d] = tuple(self._ent(bi))
            bd, best = 0, -100000
            for d in range(4):
                if A[d] is not None and B[d] is not None and A[d][3] > 0 and B[d][3] > 0:
                    if A[d][3] + B[d][3] > best:
                        bd, best = d, A[d][3] + B[d][3]
            if best < 1:
                return None
            cur, st = A[bd], B[bd]
        else:
            cov = self._covered(runs)
            last = self.n4348 - 1
            tot = self.start[last] + self.cnt[last]
            for j in range(tot):
                e = self._ent(j)
                if (e[0], e[1]) not in cov:
                    e[3] = -1
            bi = self._best_in(0, tot)
            if self._ent(bi)[3] < 1:
                return None
            cur = tuple(self._ent(bi))
            k = 0
            for d in range(n40f0):
                self.start[d], self.cnt[d] = k, 0
                k = self._stand_for_cursor(cur[0], cur[1], d, runs[d], k)
            if k < 1:
                return None
            bi = self._best_in(0, self.start[n40f0 - 1] + self.cnt[n40f0 - 1])
            if self._ent(bi)[3] < 1:
                return None
            st = tuple(self._ent(bi))
        sel = (self.n4348 == 1) | ((n40f0 == 1) << 1)
        d = st[2] if sel in (0, 1) else (cur[2] if sel == 2 else 1)
        return (cur[0], cur[1]), (st[0], st[1]), d

    # ---------- 朝向 FUN_004b01a8 ----------
    def face_dir(self, x: int, y: int) -> int:
        sc = [100, 100, 100, 100]        # 墙项: 我们地图无单向墙 → 4 向都 +100 (见模块注释)
        prev = 0
        for p in self.b.players:
            if not p.alive:
                continue
            w = 1 if _incap(p) else 5
            dist = _md(x, y, p.x, p.y)
            dx, dy = p.x - x, p.y - y
            if abs(dy) < abs(dx):
                d = 2 if dx < 1 else 3
            else:
                d = 0 if dy < 1 else 1
            tbl = (0, 10, 9, 8, 7, 6, 4, 2, 2, 1, x, y - 1, x, y + 1, x - 1, y, x + 1, y, w, prev)
            bv = tbl[dist] if dist < len(tbl) else 1
            prev = int(w * bv / 3)
            sc[d] += prev
        bd = 0
        for d in range(4):
            if sc[d] > sc[bd]:
                bd = d
        return bd

    # ---------- 移动 FUN_0049d1bd ----------
    def path_to(self, dest, limit: int):
        """返回 (路径 [不含起点], 是否超出移动力). 不可达 → (None, False)."""
        u = self.u
        if self.dist_origin != (u.x, u.y):
            self._flood((u.x, u.y), FLOOD_MOVE)
        dd = self.dist.get(dest, -1)
        if dd < 0:
            return None, False
        back = [dest]
        x, y = dest
        while dd > 0:
            for dx, dy in DIRS:
                n = (x + dx, y + dy)
                if self.dist.get(n, -1) == dd - 1:
                    x, y = n
                    break
            dd -= 1
            back.append((x, y))
        path = list(reversed(back))[1:]
        return path[:limit], len(path) > limit

    def _go(self, path, facing_d: int) -> None:
        b, u = self.b, self.u
        f = DIRS[facing_d]
        if path:
            b._log(f"{u.name} 移动到 {path[-1]}")
            u.move_path = list(path)
            ddx, ddy = path[0][0] - u.x, path[0][1] - u.y
            u.facing = (ddx, ddy) if (ddx, ddy) in DIRS else f
            u.x, u.y = path[-1]
            u.post_move_facing = f
        else:
            u.facing = f
        u.reaction_saved_facing = None

    # ---------- FUN_004af2d6 ----------
    def af2d6(self, mid: int, mode: int):
        from core.enemy_moves import move
        m = move(mid)
        if not dmg_offsets(m.template, 0):
            return None
        r = self.aece7(m.template, self.rng_move, mode)
        if r is None:
            return None
        cursor, st, d = r
        if mid in DASH_MOVES:
            lx, ly = st[0] + 2 * DIRS[d][0], st[1] + 2 * DIRS[d][1]
            if not (0 <= lx < self.b.map.w and 0 <= ly < self.b.map.h):
                return None
            if self.b.q.occupant(lx, ly) is not None or self.dist.get((lx, ly), -1) < 0:
                return None
        return cursor, st, d

    # ---------- FUN_004b0532 (优先招: 回复) ----------
    def _hp_pct(self) -> list[int]:
        """FUN_004af6a3."""
        out = []
        for e in self.b.enemies:
            if not e.alive or e.hp >= e.max_hp:
                out.append(0)
            else:
                out.append(max(1, e.hp * 100 // e.max_hp))
        return out

    def _aff80(self, hp: list[int], near: bool) -> bool:
        r = self.rand(20)
        ok = False
        for i, e in enumerate(self.b.enemies):
            if near:
                c = sum(4 for p in self.b.players if _active(p) and _md(e.x, e.y, p.x, p.y) < 6)
                if hp[i] > 0:
                    hp[i] = max(1, hp[i] - c)
            if 0 < hp[i] < 50 - r:
                ok = True
        return ok

    def _fnA(self, kind: int, x: int, y: int) -> int:
        if kind == 0:                                   # FUN_004af7ba
            return self.rand(30)
        s = 0
        for p in self.b.players:
            if not _active(p):
                continue
            dist = _md(x, y, p.x, p.y)
            if kind == 1:                               # FUN_004af8bc: 离玩家越远越好
                s += (0, 2, 2, 3, 4, 5, 8, 9, 10, 12, 14, 0)[dist] if dist < 12 else 14
            else:                                       # FUN_004af7d0: 离玩家越近越好
                s += (10, 9, 8, 7, 6, 5, 4)[dist] if dist < 7 else self.rand(2)
        return s

    def _fnB(self, kind: int, hp: int, dist: int) -> int:
        t = (12, 10, 6)[dist]
        if kind <= 2:
            return self.rand(2)                         # FUN_004af7a2
        if kind == 3:
            return t * 3 - hp // 5 + 30                 # FUN_004aface
        if kind == 4:
            return t - hp // 5 + 50                     # FUN_004afb1b
        return t + (20 - hp // 5) * 3 + 10              # FUN_004afb6a

    def b0532(self, mid: int):
        """返回 (站位, 方向, 是否移动) 或 None."""
        from core.enemy_moves import move
        m = move(mid)
        n = len(dmg_offsets(m.template, 0))
        if n < 1:
            return None
        en = self.b.enemies
        me = en.index(self.u)
        hp = self._hp_pct()
        hurt = hp[me] > 0
        l3c = {1: 1, 5: 2, 13: 3}.get(n, 3)
        lc, l18, face = HEAL_MODE.get(self.ai_mode, (0, 0, False))
        if lc == 0:
            if self.rand(3) != 0:
                return None
        elif lc == 1:
            if hp[me] > 50:
                return None
        elif not self._aff80(hp, lc == 3):
            return None
        if l18 > 1 and l3c == 1:
            l18 = 2
        fa = 0 if l18 == 0 else (1 if l3c < 2 else 2)
        # FUN_004afbbb
        self._flood((self.u.x, self.u.y), FLOOD_MOVE)
        best_cnt = 0
        for i, (x, y) in enumerate(self.stand):
            e = self._ent(i)
            e[0], e[1] = x, y
            fd = self.dist.get((x, y), -1)
            e[3] += self._fnA(fa, x, y)
            cnt = 0
            for j, a in enumerate(en):
                if j == me:
                    if hurt:
                        cnt += 1
                        e[3] += self._fnB(l18, hp[me], 0)
                    continue
                dd = _md(x, y, a.x, a.y)
                if hp[j] > 0 and 0 <= fd <= self.rng_move and 0 < dd < l3c and hp[j] < 90:
                    cnt += 1
                    e[3] += self._fnB(l18, hp[j], dd)
            if cnt > 0:
                e[3] += (cnt * 3 + 2) * 10
            best_cnt = max(best_cnt, cnt)
        if best_cnt < 1 or not self.stand:
            return None
        bi, bs = None, None                              # FUN_004b00f6 (跳过被别人占的格, 见模块注释)
        for j, c in enumerate(self.stand):
            if self._occupied_by_other(c):
                continue
            if bs is None or self._ent(j)[3] > bs:
                bi, bs = j, self._ent(j)[3]
        if bi is None:
            return None
        dest = tuple(self._ent(bi)[:2])
        d = self.face_dir(*dest) if face else self.rand(4)
        path, over = self.path_to(dest, self.rng_move)
        if over:
            return None                                  # FUN_0049d1bd 返回 2 → 放弃
        return path, d                                   # path None = 不可达: exe 不动也不转向, 原地放

    # ---------- 召唤判定 (FUN_004b1286 move==2) ----------
    def summon_ok(self) -> bool:
        n = sum(1 for e in self.b.enemies if e.alive and getattr(e, 'enemy_type', -1) == CALF_TYPE)
        if not n < self.rand(7):
            return False
        self._flood((self.u.x, self.u.y), FLOOD_SUMMON)
        return sum(1 for v in self.dist.values() if (v & 0xff) < 4) > 2

    # ---------- FUN_004b1084 ----------
    def _pick_target(self, mode: int):
        """FUN_004b0b08. 同分取后者 (>=)."""
        ps = self.b.players
        n = len(ps)
        t = self.rand(n)
        for i in range(n):                               # exe 怪写法: 看第 i 个活不活, 选 (i + r) % n
            if ps[i].alive:
                t = (i + t) % n
                break
        best = -10000
        for i, p in enumerate(ps):
            if not p.alive:
                continue
            if mode == 1:
                v = p.hp
            elif mode == 2:
                v = 100 - _md(self.u.x, self.u.y, p.x, p.y)
            elif mode == 3:
                v = 10000 - p.hp
            elif mode in (4, 5):
                cid = _char_id(p)
                k = COUNTER_CLASS[cid] if cid is not None and 0 <= cid < len(COUNTER_CLASS) else 0
                v = 3 - k if mode == 4 else k
            elif mode == 6:
                v = 1 if _incap(p) else 0
            else:
                break
            if best <= v:
                best, t = v, i
        return ps[t]

    def b1084(self) -> None:
        if not self.b.players:
            return
        tm, face = MOVE_MODE.get(self.ai_mode, (0, False))
        tgt = self._pick_target(tm)
        # FUN_004b0f89
        cands = []
        for i, (x, y) in enumerate(self.stand):
            if self.ai_mode < 3:
                dd = _md(x, y, tgt.x, tgt.y)
            else:
                dd = flood(self.b, (x, y), FLOOD_WALLS).get((tgt.x, tgt.y), 100)
                self.dist_origin = None                  # FUN_004b0ed5 覆盖了洪水图
            self._put(i, x, y, self._ent(i)[2], 100 - dd)
            cands.append((x, y))
        bi, bs = None, None
        for j, c in enumerate(cands):
            if self._occupied_by_other(c):
                continue
            if bs is None or self._ent(j)[3] > bs:
                bi, bs = j, self._ent(j)[3]
        dest = cands[bi] if bi is not None else (self.u.x, self.u.y)
        d = self.face_dir(*dest) if face else self.rand(4)
        path, _ = self.path_to(dest, self.rng_move)
        if path is None:
            return                                       # 不可达: FUN_0049d1bd 什么都不做
        while path and self._occupied_by_other(path[-1]):
            path.pop()                                   # 截断后落在友军格上 (exe 叠人) → 停在前一格
        self._go(path, d)


def _char_id(p) -> int | None:
    try:
        from core.character_sprites import char_id_for
        return char_id_for(p.name)
    except Exception:
        return None


# ---------------- 入口 ----------------
def move_order_exe(battle, unit) -> tuple[list[int], int | None]:
    """FUN_004af4bf + 4af5d4 + 抽签: 返回 (按顺序的招式槽号, 优先槽号或 None). 沉默不在这里滤 (exe 在逐招时滤)."""
    from core.enemy_moves import move
    weights = list(getattr(unit, 'move_weights', []) or [])
    cands = []
    for slot, mid in enumerate(unit.enemy_moves):
        m = move(mid)
        if m is None or m.mp_cost > unit.mp:
            continue
        cands.append((slot, weights[slot] if slot < len(weights) else 0))
    pri = next((s for s, _ in cands if move(unit.enemy_moves[s]).flags & 1), None)
    order: list[int] = []
    rest = list(cands)
    if pri is not None:
        order.append(pri)
        rest = [c for c in rest if c[0] != pri]
    while rest:
        total = sum(max(0, w) for _, w in rest)
        if total <= 0:
            order += [s for s, _ in rest]
            break
        r = battle.rng.randrange(total)
        acc = 0
        for c in rest:
            acc += max(0, c[1])
            if r < acc:
                order.append(c[0])
                rest.remove(c)
                break
    return order, pri


def take_turn(battle: "TacticsBattle", unit: "BattleUnit") -> None:
    """FUN_004b1286. 结果写进 battle._pending_enemy_* (post_enemy_turn 发动)."""
    from core.battle.status import has_status
    from core.enemy_moves import move
    ai = ExeAI(battle, unit)
    ai._flood((unit.x, unit.y), FLOOD_TURN)
    ai.adf85(ai.rng_move)
    order, pri = move_order_exe(battle, unit)
    silenced = has_status(unit, 0x400)
    for slot in order:
        mid = unit.enemy_moves[slot]
        m = move(mid)
        if silenced and not m.physical:
            continue
        t = m.flags & 3
        if t in (0, 2):
            r = ai.af2d6(mid, 1 if t == 2 else 0)
            if r is None:
                continue
            cursor, st, d = r
            path, _ = ai.path_to(st, ai.rng_move)
            ai._go(path or [], d)
            if _commit_attack(battle, unit, mid, cursor, d):
                return
            continue
        if t != 1:
            continue
        if mid == SUMMON_MOVE:
            if ai.summon_ok():
                ai._go([], ai.face_dir(unit.x, unit.y))
                battle._pending_enemy_attack = unit
                battle._pending_enemy_skill = None
                battle._pending_enemy_move = mid
                battle._pending_enemy_cursor = (unit.x, unit.y)
                battle._pending_damage_range = None
                battle._pending_damage_falloff = None
                battle._log(f"{unit.name} 出招 {m.name} (#{mid})")
                return
            continue
        if pri is None:
            continue
        pmid = unit.enemy_moves[pri]
        r = ai.b0532(pmid)
        if r is None:
            continue
        path, d = r
        if path is not None:
            ai._go(path, d)
        _commit_heal(battle, unit, pmid)
        return
    ai.b1084()


def _commit_attack(battle, unit, mid: int, cursor, d: int) -> bool:
    from core.enemy_moves import move
    from core.skill_patterns import strike_falloff
    m = move(mid)
    saved = unit.facing
    unit.facing = DIRS[d]                           # 伤害 pattern 按最终朝向 (走路中 facing 是第一步方向)
    fo = strike_falloff(unit, cursor, m.template)
    unit.facing = saved
    _full_map_falloff(battle, m.template, fo)
    tiles = {t for t in fo if battle.map.in_bounds(*t)}
    hit = [p for p in battle.players if p.alive and (p.x, p.y) in tiles]
    if not hit:                                     # 理论上不会 (光标候选来自玩家位置)
        return False
    battle._pending_enemy_attack = hit[0]
    battle._pending_enemy_skill = None
    battle._pending_enemy_move = mid
    battle._pending_enemy_cursor = cursor
    battle._pending_damage_range = tiles if len(tiles) > 1 else None
    battle._pending_damage_falloff = fo if len(tiles) > 1 else None
    battle._log(f"{unit.name} 出招 {m.name} (#{mid}) → {cursor}, 罩住 {len(hit)}")
    return True


def _full_map_falloff(battle, tmpl, fo: dict) -> None:
    """全屏型伤害 pattern (11×11 全 4) 实际罩整张图 (同 core.skill_patterns._is_fullscreen_pattern)."""
    from core.skill_patterns import _is_fullscreen_pattern
    if tmpl is not None and tmpl < len(ACTION_TEMPLATES) and _is_fullscreen_pattern(PATTERN_SET2[ACTION_TEMPLATES[tmpl][1]]):
        for x in range(battle.map.w):
            for y in range(battle.map.h):
                fo.setdefault((x, y), 8)


def _commit_heal(battle, unit, mid: int) -> None:
    """回复招: 光标 = 站位 + 模板方向 0 偏移, 伤害 pattern 用方向 0 (exe FUN_004ad010(t, 0))."""
    from core.enemy_moves import move
    from core.skill_patterns import strike_falloff
    m = move(mid)
    ax, ay = ACTION_TEMPLATES[m.template][2:4] if m.template < len(ACTION_TEMPLATES) else (0, 0)
    cursor = (unit.x + ax, unit.y + ay)
    saved = unit.facing
    unit.facing = DIRS[0]
    fo = strike_falloff(unit, cursor, m.template)
    unit.facing = saved
    tiles = {t for t in fo if battle.map.in_bounds(*t)}
    allies = [e for e in battle.enemies if e.alive and (e.x, e.y) in tiles]
    battle._pending_enemy_attack = allies[0] if allies else unit
    battle._pending_enemy_skill = None
    battle._pending_enemy_move = mid
    battle._pending_enemy_cursor = cursor
    battle._pending_damage_range = tiles if len(tiles) > 1 else None
    battle._pending_damage_falloff = fo if len(tiles) > 1 else None
    battle._log(f"{unit.name} 出招 {m.name} (#{mid}) → {cursor}, 罩住友军 {len(allies)}")
