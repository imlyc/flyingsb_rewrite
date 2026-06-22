"""竞技场模式: 选人 (KOF 式) → 沙盒战斗 (随机摆阵, 无经验) → 战斗内控制台.

公开 ArenaSetupScene 作为入口 (从标题菜单进入).
"""

from __future__ import annotations

from scenes.arena.setup_scene import ArenaSetupScene

__all__ = ["ArenaSetupScene"]
