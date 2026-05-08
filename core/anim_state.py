"""Per-unit 渲染层动画时序状态. 纯数据 (无 pygame 依赖), 让 core.battle 能直接拥有.

将来加新动画状态 (如 stunned / casting), 改这里 + scenes.unit_render.pick_locomotion_frame.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AnimationState:
    """走路 / 待机两态的时序累加器.
    注: 90° 转向不插过渡帧, 即转即生效, 无需额外状态.
    """
    anim_time_ms: int = 0    # 移动中累加 (静止 = 0); 走路帧切换
    idle_time_ms: int = 0    # 静止时累加 (移动 = 0); 待机呼吸帧切换

    def tick(self, dt_ms: int, *, moving: bool) -> None:
        if moving:
            self.anim_time_ms += dt_ms
            self.idle_time_ms = 0
        else:
            self.anim_time_ms = 0
            self.idle_time_ms += dt_ms

    def reset(self) -> None:
        self.anim_time_ms = 0
        self.idle_time_ms = 0
