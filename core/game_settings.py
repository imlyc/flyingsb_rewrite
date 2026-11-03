"""战斗环境设定 / 音量 — exe FlyingSB.INI [ENVIRONMENT] (FUN_0049b21c 读写):
  battle_player_status 0x7b88dc  我军状态 (状态栏 FUN_004cf1ed 滑入)
  battle_enemy_status  0x7b88e0  敌军状态 (敌人 HP/MP FUN_004cf98d)
  battle_enemy_skill   0x7b88e4  攻击技术 (敌招名横幅 FUN_004d0291 / FUN_004cfde0)
  volume_bgm           0x7b88bc  音乐 0..100 (FUN_004156d1)
  volume_soundeffect   0x7b88c0  音效 0..100 (FUN_00414f20)
默认全开 (原版 INI 攻击技术为 0, 用户定为默认开).存 rewrite/data/settings.json (战斗 OP. 窗口改了就写).
"""
from __future__ import annotations

import json
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "data" / "settings.json"
DEFAULTS = {
    "battle_player_status": 1,
    "battle_enemy_status": 1,
    "battle_enemy_skill": 1,
    "volume_bgm": 100,
    "volume_soundeffect": 100,
}
_values: dict | None = None


def _load() -> dict:
    global _values
    if _values is None:
        _values = dict(DEFAULTS)
        try:
            raw = json.loads(_PATH.read_text(encoding="utf-8"))
            for k in DEFAULTS:
                if k in raw:
                    _values[k] = int(raw[k])
        except (FileNotFoundError, ValueError, OSError):
            pass
    return _values


def get(key: str) -> int:
    return _load()[key]


def set(key: str, value: int) -> None:
    v = _load()
    v[key] = int(value)
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
