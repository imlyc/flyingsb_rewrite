"""战斗绘制队列 — exe FUN_004c8184 每帧的画法.

原版不分「单位层 / 特效层」: 带可见位 0x40 的实体按池序 (单位槽 < 0x5a 在前, 特效在后) 逐个进精灵队列
(FUN_004b3663, 排序键 = 地面 y 像素 = +0xc >> 16), 带 0x08 的再追加一个影子项 (FUN_004b3421, 键恒 0),
再追加压住实体的前景瓦片 (FUN_004b8aa9, 键 = 瓦片底边), 然后整段选择排序 (FUN_004b2927, 严格 <, 不稳定)
后依次画 (FUN_004b29d3). 所以影子全部最先画, 单位与特效按地面 y 互相遮挡 (如回复药粒子转到身后).
"""

from __future__ import annotations

from typing import Callable, Sequence, TypeVar

T = TypeVar('T')


def ground_key(y16: int) -> int:
    """16.16 地面 y → 像素 (C 截断除法, 同 exe `(y + (y >> 31 & 0xffff)) >> 16`)."""
    return y16 >> 16 if y16 >= 0 else -((-y16) >> 16)


def entity_key(e) -> int:
    """特效实体的排序键. 飘字的 y 我们不含 exe 的 +400/+404 (折进了 z), 记在 user_data['sort_dy']."""
    return ground_key(e.y + e.user_data.get('sort_dy', 0))


def selection_sort(items: Sequence[T], key: Callable[[T], int]) -> list[T]:
    """FUN_004b2927: 每位取其后最小 (严格 <, 取第一个) 与之交换 — 同键不保序, 照搬."""
    a = list(items)
    keys = [key(x) for x in a]
    n = len(a)
    for c in range(n - 1):
        m = c
        for j in range(c + 1, n):
            if keys[j] < keys[m]:
                m = j
        if m != c:
            a[c], a[m] = a[m], a[c]
            keys[c], keys[m] = keys[m], keys[c]
    return a


def unit_slot_order(players, enemies) -> list:
    """单位在实体池里的顺序 (全部单位槽在特效之前): 我方按队伍序占 0.., 敌方从 60 起
    (原版实录 entdump: 5 人队伍占槽 0-4, 敌人 60+)."""
    return list(players) + list(enemies)
