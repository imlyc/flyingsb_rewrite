"""敌招演出 (exe 招式处理函数的 tmpl / custom 类; DOIT 类走 combat.begin_attack 的 seq 路径), 2026-10-26.

每个模块 (t<模板地址>.py / m<招式id>.py) 定义 Spell 子类并登记:
  TEMPLATES = {0x4d68a0: Cls}   # 模板函数地址 (core.enemy_move_data MOVES[.][8] = 'FUN_004d68a0') → 类
  MOVES = {24: Cls}             # 招式 id → 类 (custom / 有 hook 的招式; 优先于模板)
本包导入时自动扫描所有子模块. 框架见 core.enemy_spells.base.
"""
from __future__ import annotations

import importlib
import pkgutil

_TEMPLATES: dict[int, type] = {}
_MOVES: dict[int, type] = {}
_loaded = False


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for info in pkgutil.iter_modules(__path__):
        if info.name == 'base':
            continue
        try:
            mod = importlib.import_module(f'{__name__}.{info.name}')
        except Exception as ex:                      # 单个模块坏了不拖累其他招式 (回落通用动作)
            print(f"[enemy_spells] 模块 {info.name} 导入失败: {ex!r}")
            continue
        _TEMPLATES.update(getattr(mod, 'TEMPLATES', {}))
        _MOVES.update(getattr(mod, 'MOVES', {}))


def spell_class(mid: int | None):
    """招式 mid 的演出类; 没实现 (或 DOIT 类) → None."""
    if mid is None:
        return None
    _load()
    if mid in _MOVES:
        return _MOVES[mid]
    from core.enemy_moves import move
    m = move(mid)
    if m is None:
        return None
    if m.kind == 'doit':                       # 普通 DOIT_melee: 同 hook 招的 DOIT 收尾 (命中特效按受击后退 4px + 13 tick 镜头等待)
        from core.enemy_spells.m_doit_hook import DoitHook
        return DoitHook
    if not m.kind.startswith('tmpl') or not m.called:
        return None
    return _TEMPLATES.get(int(m.called[4:], 16))


def implemented() -> dict[int, str]:
    """已有演出的招式 id → 类名 (调试/统计用)."""
    from core.enemy_move_data import MOVES as ALL
    return {i: c.__name__ for i in range(len(ALL)) if (c := spell_class(i)) is not None}
