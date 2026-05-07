"""方向键长按检测器: tap = 仅转向, 持续按住超阈值 = 自动连走.

世界地图和战斗场景都用这个共享的状态机, 避免在两处重复实现 (历史上已经因此出过 bug).

典型用法:
    self.hold = DirectionalHold()
    # 每帧 update:
    keys = pygame.key.get_pressed()
    dx = (keys[K_RIGHT] or keys[K_d]) - (keys[K_LEFT] or keys[K_a])
    dy = (keys[K_DOWN]  or keys[K_s]) - (keys[K_UP]   or keys[K_w])
    if dx == 0 and dy == 0:
        self.hold.reset(); return
    if dx != 0: dy = 0    # 优先水平
    new_dir = (dx, dy)
    edge = self.hold.tick(new_dir, dt_ms)
    if new_dir != self.facing:
        if edge:
            do_turn(new_dir)
        return
    if self.hold.should_walk(edge, WALK_HOLD_DELAY_MS):
        do_step(new_dir)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DirectionalHold:
    held_dir: tuple[int, int] = (0, 0)   # 当前持续按下的方向, (0,0) = 无输入
    held_ms: int = 0                      # 当前方向已按住时长 (从边沿开始累加)
    walking: bool = False                 # 一旦本次连续按下触发过走步, 后续无需再等阈值

    def reset(self) -> None:
        self.held_dir = (0, 0)
        self.held_ms = 0
        self.walking = False

    def tick(self, new_dir: tuple[int, int], dt_ms: int) -> bool:
        """更新内部状态, 返回 edge (本帧是否新按下 / 切换方向)."""
        edge = (new_dir != self.held_dir)
        if edge:
            self.held_dir = new_dir
            self.held_ms = 0
            self.walking = False
        else:
            self.held_ms += dt_ms
        return edge

    def should_walk(self, edge: bool, hold_delay_ms: int) -> bool:
        """朝向已对齐时, 是否本帧走一步.
        条件: 边沿 (新按下且方向已对) / 已在连走 / 持续按住够久.
        """
        if edge or self.walking or self.held_ms >= hold_delay_ms:
            self.walking = True
            return True
        return False
