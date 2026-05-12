"""战斗场景包. 公开接口: BattleScene.

子模块:
  scene.py       — BattleScene 主体 (init/update/draw/handle_event/几何工具/引擎回调)
  units.py       — 单位渲染 (live/dying/dead/blink/facing arrow), 自由函数
  hud.py         — HUD/菜单/banner/日志/升级框, 自由函数
  float_text.py  — 浮动伤害数字 widget
"""

from scenes.battle.scene import BattleScene

__all__ = ["BattleScene"]
