"""战斗单位走路/待机 = 原版运动状态机 + 姿态函数 FUN_004c2492 (case 0 / case 2), 2026-10-29 逆向 + 实录对齐.

实体字段: [0x41] 状态 (0 站立 / 2 战斗走格), [0x42] 计数, [0x43] 左右脚 phase, [0x44] 方向 (0 上 1 下 2 左 3 右),
[0x4c] ps_ 网格基址 (待机周期表下标 = 基址 >> 3), flags & 0x30 = 帧表变体 (敌人表 +4 flags & 0xc0 >> 2, 玩家恒 0).

每 tick 先走运动 (状态 2: 计数 +1 mod 4, 位移 1/4 格; 计数归 0 = 到格: phase 翻转、回状态 0),
再算姿态 (状态 0 时计数 +1):
- 状态 2: 走路图 第 dir 行, 列 = 0x65314c[计数 + phase*4 + 变体*8] (变体 0: 1,2,1 / 3,4,3).
- 状态 0 计数 1 (= 到格那一 tick): 走路图第 0 列 → 连走时每格 4 tick 正好 1,2,1,0 / 3,4,3,0 交替 (实录 232 段全吻合).
- 状态 0 之后: 待机图 frame dir + ((计数 // 周期) & 1) * 4, 周期 = 0x652d0c[基址 >> 3] (玩家 6..11, 敌多为 8).
- 变体 1/2 (飞行/浮游类) 待机也用走路图: 列 = 0x65308c[(计数 & 15) + 变体*16]; 变体 3 (鬼火) 不分方向: 0x8c 数组[全局 tick % 20].
- 虚弱 (HP < 40%) 只对玩家 (敌实体 +0x2c 恒非 0 → 走普通分支): ps_*04 第 dir 行 列 1 + ((计数 // 周期) & 1).
- 睡眠/痲痺 (状态字 & 0xa00): 定格 (见 pose()).
"""
from __future__ import annotations

from dataclasses import dataclass

WALK_TICKS = 4                    # 状态 2 周期: 4 tick 一格 (横 16px/t, 纵 12px/t)
FROZEN_STATUS = 0x200 | 0x800     # 睡眠 | 痲痺

# 0x65314c: 状态 2 帧表 (int32, 高 nibble = atlas, 低 nibble = 列), 4 变体 × 8 (变体 3 不读)
STATE2_COLS = (0, 1, 2, 1, 0, 3, 4, 3,
               0, 1, 1, 2, 2, 1, 1, 0,
               0, 1, 2, 3, 3, 2, 1, 0)
# 0x65308c: 状态 1 (大地图走格) 帧表 4 变体 × 16; 战斗里变体 1/2 的待机借用
STATE1_COLS = (0, 0, 1, 1, 2, 2, 1, 1, 0, 0, 3, 3, 4, 4, 3, 3,
               0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 1, 1, 1, 1, 0, 0,
               0, 0, 1, 1, 2, 2, 3, 3, 3, 3, 2, 2, 1, 1, 0, 0)
# 0x652d0c: 待机换帧周期 (tick), 下标 = 网格基址 >> 3; 16 以后全是 8
IDLE_PERIODS = (8, 8, 8, 10, 8, 7, 6, 11, 11, 8, 9, 9, 10, 9, 8, 7)
# 变体 3 的栈上数组 local_4c[16], exe 用 [全局 tick % 20] 读 — 16..19 越界读到别的栈变量 (实录 0, 3, 垃圾, 垃圾).
# 越界的 4 项这里一律给 0.
WISP_FRAMES = (0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 1, 1, 1, 1)

WALK, IDLE, WEAK = "walk", "idle", "weak"     # atlas 0x20000 / 0x20006 / 0x20004

_DIR = {(0, -1): 0, (0, 1): 1, (-1, 0): 2, (1, 0): 3}


@dataclass
class Locomotion:
    state: int = 0       # [0x41]
    counter: int = 0     # [0x42]
    phase: int = 0       # [0x43]


def idle_period(grid_base: int) -> int:
    i = grid_base >> 3
    return IDLE_PERIODS[i] if 0 <= i < len(IDLE_PERIODS) else 8


def exe_dir(facing: tuple[int, int]) -> int:
    return _DIR.get(tuple(facing), 1)


def motion_tick(loco: Locomotion, walking: bool) -> bool:
    """运动一步 (MotionRules 的状态 2 平移). walking = 本 tick 要向目标格走. 返回本 tick 是否位移."""
    if walking and loco.state != 2:
        loco.state, loco.counter = 2, 0          # 起步: 状态 2 计数从 0 起
    if loco.state != 2:
        return False
    loco.counter = (loco.counter + 1) % WALK_TICKS
    if loco.counter == 0:
        loco.phase ^= 1
        loco.state = 0
    return True


def pose(loco: Locomotion, facing: tuple[int, int], *, variant: int = 0, player: bool = False,
         weak: bool = False, frozen: bool = False, period: int = 8, global_tick: int = 0) -> tuple[str, int, int]:
    """FUN_004c2492 case 0 / 2 → (atlas, 列, 行); 行 -1 = 列是线性帧号 (变体 3 不分方向). 状态 0 会推进计数 (同 exe)."""
    d = exe_dir(facing)
    if loco.state == 2:
        if variant == 3:
            return WALK, WISP_FRAMES[global_tick % 20] if global_tick % 20 < 16 else 0, -1
        return WALK, STATE2_COLS[(loco.counter + loco.phase * 4 + variant * 8) % len(STATE2_COLS)] & 0xF, d
    loco.counter += 1
    c = loco.counter
    if not (weak and player):
        if variant == 0:
            if frozen or c == 1:
                return WALK, 0, d
            return IDLE, d, (c // period) & 1                  # 待机图 frame d + k*4 = 第 d 列第 k 行
        if variant in (1, 2):
            if not frozen:
                return WALK, STATE1_COLS[(c & 0xF) + variant * 16], d
            return (WALK, STATE1_COLS[variant * 16], d) if variant == 1 else (WEAK, 2, d)
        if frozen:
            return WALK, 0, -1
        return WALK, WISP_FRAMES[global_tick % 20] if global_tick % 20 < 16 else 0, -1
    if not frozen:
        return WEAK, 1 + ((c // period) & 1), d
    return WEAK, (1, 1, 2, 0)[variant], d


def unit_params(u) -> tuple[int, int]:
    """(帧表变体, 待机周期). 玩家: 属性 flags 全 0 → 变体 0, 网格基址 0x54eb08[角色] = 8 × (角色号 + 1);
    敌: 敌人表 flags & 0xc0 >> 6, 网格基址 = 敌人表记录头贴图基址."""
    cached = getattr(u, "_loco_params", None)
    if cached is not None:
        return cached
    if u.is_player:
        from core.character import CHARACTER_NAMES
        rec = next((k for k, v in CHARACTER_NAMES.items() if v == u.name), 0)
        res = (0, idle_period(8 * (rec + 1)))
    else:
        from core.character_data import _enemies
        e = _enemies().get(str(u.enemy_type), {})
        res = ((u.type_flags & 0xC0) >> 6, idle_period(int(e.get("sprite_base", 0))))
    u._loco_params = res
    return res


def tick_pose(u, global_tick: int) -> tuple[str, int, int]:
    """该单位本 tick 的姿态 (运动已走完后调用)."""
    variant, period = unit_params(u)
    return pose(u.loco, u.facing, variant=variant, player=u.is_player, weak=u.display_weakened,
                frozen=bool(u.status_bits & FROZEN_STATUS), period=period, global_tick=global_tick)
