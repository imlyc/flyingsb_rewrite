"""竞技场选人记忆: 把上次出战名单存到磁盘, 程序重启后读回.

存 rewrite/data/arena_selection.json. 读回时按当前名册校验, 丢弃已不存在的名字.
"""

from __future__ import annotations

import json
from pathlib import Path

from scenes.arena.roster import ENEMY_ROSTER, PLAYER_ROSTER

# rewrite/scenes/arena/store.py → parents[2] = rewrite/
_PATH = Path(__file__).resolve().parents[2] / "data" / "arena_selection.json"


def load_selection() -> tuple[list[str], list[str]]:
    """返回上次的 (我方出战, 敌方出战). 文件缺失/损坏/名字失效时返回 ([], [])."""
    try:
        raw = json.loads(_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return [], []
    players = [n for n in raw.get("players", []) if n in PLAYER_ROSTER]
    enemies = [n for n in raw.get("enemies", []) if n in ENEMY_ROSTER]
    return players, enemies


def save_selection(players: list[str], enemies: list[str]) -> None:
    """把出战名单写盘 (开战时调). 失败静默 (不阻断游戏)."""
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(
            json.dumps({"players": list(players), "enemies": list(enemies)},
                       ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass
