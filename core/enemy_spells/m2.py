"""招式 2 召喚牛寶寶 (牛魔王) = custom dispatcher FUN_004e6454 + 结算 FUN_004a6efe 类别 3, 2026-10-26.

AI (FUN_004b1286 move==2, 见 core.battle.ai_exe): 场上未倒的牛寶寶 (类型 0x17) 数 < rand%7, 且洪水 0xd2 (只玩家挡) 步数
  0..3 的格 > 2 → 原地朝 FUN_004b01a8 方向出招.
结算 (FUN_004a6efe case 3, 行动开始时): 同一洪水图里步数 0..3 且格上无单位的格 (线性顺序, 最多 24 个) 中无放回随机
  抽 3 个; 敌人槽 1..8 里已死的槽依次复活成牛寶寶 (状态 = 类型 0x17 flags, HP/MP = 表值, 朝向 rand&3, 行动值 rand%20,
  FUN_004a2ec8(槽, 1)), 作为本招的 3 个目标.
  **近似**: 我们直接新建单位 (core.battle.setup.make_enemy_by_type(0x17)), 上限 = 9 - 存活敌人数; 候选格不足 3 个时
  exe 会死循环, 这里有几个用几个. 新单位在 -100 时出现 (exe 结算时已复活, 但 -100 前不可见/不动).
dispatcher: 0 渐暗 → 10 施法者挂 66e078[朝向] (cwu_m0 跺脚, 带 0xa9 音) → -100: 每个召唤目标清 0x10000 挂 66e158[目标朝向]
  (eflea 烟雾 4 帧 × 3t, 起手 0x122 音) 计数 +1 → 目标 seq 发 -200: FUN_004c4f20 复位 + 待机, 计数 -1 → 全清 → 渐亮 → 自毁.
"""
from __future__ import annotations

from core.anim_engine.bytecode import tuple_to_bytecode
from core.enemy_spells.base import Spell, _dir

CALF_TYPE = 0x17
MAX_ENEMIES = 9
_CAST_FR = ((1, 8), (2, 8), (0, 6), (2, 6), (0, 5), (2, 5), (0, 4), (2, 4), (0, 3), (2, 3), (0, 2), (2, 2), (0, 1),
            (2, 1), (0, 1), (2, 1), (0, 1), (2, 1), (0, 1), (1, 1), (2, 1))
# 66e078[d]: cwu_m0 (atlas 43) 帧 4d+k
CAST = [[('fm', 43, 4 * d + f, t) for f, t in _CAST_FR] + [('sound', 169, 1041), ('jump', -100), ('fm', 43, 4 * d + 3, 8),
                                                             ('exit',)] for d in range(4)]
# 66e158[d]: eflea (atlas 239) 帧 4d+3..4d+0 各 3t, 末尾 jump -200 (这里用计时代替, 同 m30)
APPEAR = [[('sound', 290, 1041)] + [('fm', 239, 4 * d + k, 3) for k in (3, 2, 1, 0)] + [('exit',)] for d in range(4)]
APPEAR_TICKS = 4 * 3
DIRS = ((0, -1), (0, 1), (-1, 0), (1, 0))


def summon_cells(battle, caster) -> list[tuple[int, int]]:
    """FUN_004a6efe case 3: 洪水 0xd2 步数 < 4 且无单位的格, 线性顺序最多 24 个."""
    from core.battle.ai_exe import FLOOD_SUMMON, flood
    dist = flood(battle, (caster.x, caster.y), FLOOD_SUMMON)
    cells = sorted((c for c, v in dist.items() if (v & 0xff) < 4 and battle.q.occupant(*c) is None),
                   key=lambda c: (c[1], c[0]))
    return cells[:24]


class SummonCalf(Spell):
    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.spawned: list = []
        self.until = None

    def cast_seq(self, d):
        return CAST[d]

    def _spawn(self) -> list:
        from core.battle.setup import make_enemy_by_type
        b = self.battle
        cells = summon_cells(b, self.caster)
        picks: list[int] = []
        want = min(3, len(cells))
        while len(picks) < want:                          # 无放回: rand % 格数, 重复就重抽
            i = b.rng.randrange(0x8000) % len(cells)
            if i not in picks:
                picks.append(i)
        room = MAX_ENEMIES - sum(1 for e in b.enemies if e.alive)
        out = []
        for i in picks[:max(0, room)]:
            u = make_enemy_by_type(CALF_TYPE)
            if u is None:
                break
            u.x, u.y = cells[i]
            u.facing = DIRS[b.rng.randrange(0x8000) & 3]
            u.action_value = b.rng.randrange(0x8000) % 20
            u.has_acted = False
            u.snap_render()
            b.enemies.append(u)
            out.append(u)
            b._log(f"{self.caster.name} 召唤 {u.name} @{cells[i]}")
        return out

    def on_cast_impact(self) -> None:
        eng = self.battle.engine
        self.spawned = self._spawn()
        for v in self.spawned:
            if v.entity is None:
                v.entity = eng.spawn()
                v.entity.user_data = {'unit': v}
            v.entity.x = v.entity.y = v.entity.z = 0
            v.cast_hold = True
            eng.attach_seq(v.entity, tuple_to_bytecode(APPEAR[_dir(v)]))
        self.until = self.age + APPEAR_TICKS

    def think(self) -> None:
        if self.until is None or self.age < self.until:
            return
        self.until = None
        for v in self.spawned:                            # -200: FUN_004c4f20 复位 + 回待机
            v.cast_hold = False
            if v.entity is not None:
                v.entity.user_data.pop('idle_until_tick', None)
        self.finish()


MOVES = {2: SummonCalf}
