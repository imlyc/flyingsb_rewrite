"""位置图: 原版地图之间的关联 (地图切换骨架).

数据来自 assets/location_map.json (由 tools/extract_locations.py 从 .mfo 生成):
  locations[base] = {id, name, spawn:[x,y], transitions:[[x,y,target_id], ...]}
  by_id[id] = base

位置 ID 两套:
  · 数字 ID 空间 48..487 (429 个, 城镇/迷宫/房间)
  · 命名位置 (镇子/世界地图, 韩文名; 其 mfo 的 mapname 不是数字)
站立/走到 transitions 里的 (x,y) → 传送到 target_id 对应的地图.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "assets" / "location_map.json"

_cache: dict | None = None


def _data() -> dict:
    global _cache
    if _cache is None:
        if PATH.exists():
            _cache = json.loads(PATH.read_text(encoding="utf-8"))
        else:
            _cache = {"locations": {}, "by_id": {}}
    return _cache


def available() -> bool:
    return PATH.exists()


def info(base: str) -> dict | None:
    return _data()["locations"].get(base)


def base_for(loc_id: int) -> str | None:
    return _data()["by_id"].get(str(loc_id))


def all_bases() -> list[str]:
    return sorted(_data()["locations"])


def named_locations() -> list[tuple[str, str]]:
    """(base, 韩文名) 列表 (镇子/世界地图)."""
    out = []
    for base, v in _data()["locations"].items():
        if v.get("id") is None and v.get("name"):
            out.append((base, v["name"]))
    return sorted(out, key=lambda t: t[1])


# ---------------------------------------------------------------------------
# 运行时补丁: 原 .mfo 没抽出出口的地图, 在此手动接回原版邻接.
#   小森林 TBB0___P (id 476) 是序章前的起始村, 出村(南) -> 五指村 (id 22).
#   ⚠ 该图**南边整片是树墙**(flag=11 不可走), 可走空地只在 y3~11; 故出村口放在
#     空地南缘 y=12 一整条 (x9~17), 玩家在空地里往下走即出林 —— 见 _probe 的 ASCII 图。
#   放在这里而非改 location_map.json, 避免重新抽取时丢失.
# ---------------------------------------------------------------------------
#   跨簇链接: 五指村世界 T_LOC0_P(id 0) ↔ 雅士兰世界 T_LOC1_P(id 1) 原版靠剧情跳转相连,
#     这里补一对步行传送点, 让前 3 章纯步行可达 (两格均已验证可通行).
_EXTRA_TRANSITIONS: dict[str, dict[tuple[int, int], int]] = {
    "TBB0___P": {(x, 12): 22 for x in range(9, 18)},   # 小森林 出村(南) → 五指村
    "T_LOC0_P": {(10, 6): 1},                          # → 雅士兰世界
    "T_LOC1_P": {(5, 5): 0},                           # → 五指村世界
}


def transitions(base: str) -> dict[tuple[int, int], int]:
    """{ (x,y): target_id } —— 传送点坐标 → 目标位置 ID."""
    v = info(base)
    out = {}
    if v:
        out = {(t[0], t[1]): t[2] for t in v.get("transitions", [])}
    out.update(_EXTRA_TRANSITIONS.get(base, {}))
    return out


# ---------------------------------------------------------------------------
# 步行传送的剧情门控 (与 scenes/world_map/atlas.py 的 unlock 保持一致):
#   走到该传送点需先满足对应 flag, 否则被剧情挡住 (避免提前闯入未解锁区域).
#   例: 五行山步行入口 (T_LOC0_P 10,3 -> TOH0_00P) 需先完成五指村线 (LEFT_VILLAGE),
#   与 M 键世界地图"五行山 unlock=LEFT_VILLAGE"同义.
# ---------------------------------------------------------------------------
_LOCATION_GATES: dict[str, dict[tuple[int, int], str]] = {
    "T_LOC0_P": {(10, 3): "LEFT_VILLAGE"},   # 五行山入口
}


def gate_for(base: str, x: int, y: int) -> str | None:
    """该传送点需要的 flag; 无门控返回 None."""
    return _LOCATION_GATES.get(base, {}).get((x, y))


def has_encounters(base: str) -> bool:
    """该地图是否有随机遇敌 (需 .mfo 有 enemytype 且非城镇/房间)."""
    v = info(base)
    return bool(v.get("enc")) if v else False


def spawn(base: str) -> tuple[int, int] | None:
    v = info(base)
    if v and v.get("spawn"):
        return (v["spawn"][0], v["spawn"][1])
    return None


# ---------------------------------------------------------------------------
# 战斗配置 (assets/maps_events.json, 由 tools.extract_events 从 .mfo 生成)
# ---------------------------------------------------------------------------
_EVENTS_PATH = ROOT / "assets" / "maps_events.json"
_events_cache: dict | None = None


def _events() -> dict:
    global _events_cache
    if _events_cache is None:
        try:
            _events_cache = json.loads(_EVENTS_PATH.read_text(encoding="utf-8"))
        except Exception:
            _events_cache = {}
    return _events_cache


def enemy_types(base: str) -> list[int]:
    """该地图的敌人类型 id 池 (.mfo 的 enemytype = a,b,c,d)."""
    v = _events().get(base)
    if not v:
        return []
    return [int(x) for x in v.get("enemytype", [])
            if isinstance(x, (int, float)) and x >= 0]


def battle_info(base: str) -> dict:
    v = _events().get(base) or {}
    return {
        "enemytype": v.get("enemytype", []),
        "partylevel": v.get("partylevel", []),
        "escape": v.get("escape"),
        "battlearea": v.get("battlearea"),
    }
