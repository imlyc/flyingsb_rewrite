"""竞技场选人记忆: 把上次出战名单存到磁盘, 程序重启后读回.

存 rewrite/data/arena_selection.json. 读回时按当前名册校验, 丢弃已不存在的名字.
"""

from __future__ import annotations

import json
from pathlib import Path

from scenes.arena.roster import ENEMY_ROSTER, PLAYER_ROSTER

# rewrite/scenes/arena/store.py → parents[2] = rewrite/
_PATH = Path(__file__).resolve().parents[2] / "data" / "arena_selection.json"


def load_levels() -> dict[str, int]:
    """上次各我方角色的竞技场等级 {名字: 1..99}."""
    try:
        raw = json.loads(_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return {}
    return {n: max(1, min(99, int(v))) for n, v in raw.get("levels", {}).items() if n in PLAYER_ROSTER}


def load_selection() -> tuple[list[str], list[str]]:
    """返回上次的 (我方出战, 敌方出战). 文件缺失/损坏/名字失效时返回 ([], [])."""
    try:
        raw = json.loads(_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return [], []
    players = [n for n in raw.get("players", []) if n in PLAYER_ROSTER]
    enemies = [n for n in raw.get("enemies", []) if n in ENEMY_ROSTER]
    return players, enemies


def _read_raw() -> dict:
    try:
        raw = json.loads(_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _write_raw(data: dict) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def load_equipment() -> dict[str, list[int]]:
    """隊伍情報里给各我方角色记住的装备 {名字: [头, 身, 手, 饰, 饰]} (-1 = 空)."""
    out = {}
    for n, v in _read_raw().get("equipment", {}).items():
        if n in PLAYER_ROSTER and isinstance(v, list) and len(v) == 5:
            try:
                out[n] = [int(x) for x in v]
            except (TypeError, ValueError):
                continue
    return out


def save_equipment(name: str, slots) -> None:
    """记住一个角色的 5 槽装备 (None/UNSET → -1)."""
    data = _read_raw()
    eq = data.get("equipment", {})
    vals = []
    for v in slots:
        v = -1 if v is None else int(v)
        vals.append(-1 if v < 0 or v >= 0x80000000 else v)
    eq[name] = vals
    data["equipment"] = eq
    _write_raw(data)


def save_selection(players: list[str], enemies: list[str], levels: dict[str, int] | None = None) -> None:
    """把出战名单 (+ 我方等级) 写盘 (保留文件里的其它键, 如 equipment). 失败静默 (不阻断游戏)."""
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        data = _read_raw()
        data["players"], data["enemies"] = list(players), list(enemies)
        if levels is not None:
            data["levels"] = dict(levels)
        _PATH.write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass
