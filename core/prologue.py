"""序章 (开场 + 禁断之卵) 的演出数据: 分场景 + 每场景的对白页 + 在场角色站位.

数据来源 (都是 exe 真值, 由 tools/extract_prologue / extract_event_scenes 提取):
  · assets/script/prologue.json    183 页对白 [{speaker, text, code}], 按剧本区顺序;
  · assets/script/event_scenes.json 事件脚本里的场景: {event, map, cast[{code,x,y,z,frames,visible}]};
  · 场景切分 (地图 ↔ 对白页区间) 跟随地图表的序章地图链 469→476 (map_table `next`),
    页区间按剧本内容人工标定 (mygame 贡献者 PROLOGUE_SCENES), 事件脚本本身没有切图页码.
立绘代号 → 精灵图集 (ps_*): SONA 樂神 / SON5 孫悟空(无头盔) / MIRO 美娜 / RACH 蕾琪兒 / DIT 迪特 /
OK 玉皇大帝 / SOL* 侍衛 / CAP 侍衛隊長.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES_PATH = ROOT / "assets" / "script" / "prologue.json"
EVENTS_PATH = ROOT / "assets" / "script" / "event_scenes.json"

# 立绘/说话人代号 → ps 图集资源名 (64×96, 行=朝向 0背/1正/2左/3右)
CODE_SPRITE: dict[str, str] = {
    "SONA": "ps_CSONA00", "SON5": "ps_CSON000", "SON": "ps_CSON000",
    "MIRO": "ps_CMIRO00", "RACH": "ps_CCHIW00", "DIT": "ps_CDIT000",
    "OK": "ps_COK000", "SOL": "ps_CSOLD00", "SOL1": "ps_CSOLD00", "SOL2": "ps_CSOLD00",
    "CAP": "ps_CCAPT00", "MASK": "ps_CMASK00",
}

# 序章分场景: 地图 (地图表 id) + 对白页区间 [a, b] (含) + 该场景强制 BGM (None = 用地图表的)
# 页区间: mygame 贡献者按剧本内容标定; 地图顺序 = 地图表 next 链 469→476.
@dataclass
class PrologueScene:
    map_id: int
    base: str
    a: int
    b: int
    name: str
    bgm: int | None = None
    hand_cast: tuple[tuple[str, int, int], ...] = ()   # 事件脚本没给坐标时的手摆
    cast: list[dict] = field(default_factory=list)      # 合并后 [{code, x, y, z, frames}]

    def pages(self, all_pages: list[dict]) -> list[dict]:
        return all_pages[self.a:self.b + 1]


SCENES: tuple[PrologueScene, ...] = (
    PrologueScene(469, "TCL0___P", 0, 15, "樂神奏乐 · 封印孫悟空 (200 年前)", bgm=7,
                  hand_cast=(("SONA", 6, 32), ("SON5", 6, 37))),
    PrologueScene(470, "TMI0___P", 16, 23, "美娜公主的房間 (恶梦惊醒)",
                  hand_cast=(("MIRO", 3, 5), ("RACH", 5, 5))),
    PrologueScene(471, "TRO2___P", 24, 61, "天宮 (蕾琪兒 / 迪特)",
                  hand_cast=(("MIRO", 7, 8), ("DIT", 10, 6), ("SOL1", 6, 7), ("SOL2", 8, 6))),
    PrologueScene(472, "TRO1___P", 62, 85, "天宮 (侍衛 / 蛋糕)",
                  hand_cast=(("MIRO", 6, 8), ("DIT", 10, 6))),
    PrologueScene(473, "TEG0___P", 86, 109, "禁斷之房 (禁断之卵)",
                  hand_cast=(("MIRO", 8, 9),)),
    PrologueScene(474, "TSK0___P", 110, 177, "天宮大殿 (玉帝遣美娜下凡)",
                  hand_cast=(("OK", 9, 9), ("MIRO", 7, 12), ("DIT", 11, 12), ("SOL", 6, 12), ("CAP", 13, 12))),
    PrologueScene(476, "TBB0___P", 178, 182, "小森林 (车坏)",
                  hand_cast=(("MIRO", 10, 8),)),
)


def available() -> bool:
    return PAGES_PATH.exists()


def load_pages() -> list[dict]:
    if not PAGES_PATH.exists():
        return []
    return json.loads(PAGES_PATH.read_text(encoding="utf-8"))


def _event_cast() -> dict[int, list[dict]]:
    """地图 id → 事件脚本里的 cast (取该地图的第一个事件)."""
    if not EVENTS_PATH.exists():
        return {}
    out: dict[int, list[dict]] = {}
    for e in json.loads(EVENTS_PATH.read_text(encoding="utf-8")):
        if e.get("map") is None or not e.get("cast"):
            continue
        out.setdefault(e["map"], e["cast"])
    return out


def scenes() -> list[PrologueScene]:
    """带合并 cast 的场景列表: 手摆名单为准, 坐标用事件脚本真值覆盖, 事件里多出的角色补上."""
    ev = _event_cast()
    out = []
    for sc in SCENES:
        evc = [c for c in ev.get(sc.map_id, []) if c.get("x") not in (None, 0xFFFFFFFF)]
        evpos = {c["code"]: c for c in evc}
        cast: list[dict] = []
        seen: set[str] = set()
        for code, x, y in sc.hand_cast:
            c = evpos.get(code)
            cast.append({"code": code, "x": c["x"] if c else x, "y": c["y"] if c else y,
                         "z": c["z"] if c else 0, "frames": list(c["frames"]) if c else []})
            seen.add(code)
        for c in evc:
            if c["code"] not in seen:
                cast.append({"code": c["code"], "x": c["x"], "y": c["y"], "z": c["z"],
                             "frames": list(c["frames"])})
                seen.add(c["code"])
        out.append(PrologueScene(sc.map_id, sc.base, sc.a, sc.b, sc.name, sc.bgm, sc.hand_cast, cast))
    return out


def messages_for(sc: PrologueScene, all_pages: list[dict]) -> list[dict]:
    """场景的对白页 → DialogueScene 的 message dict (带说话人头像资源)."""
    msgs = []
    for p in sc.pages(all_pages):
        code = p.get("code") or ""
        msgs.append({"scene": "prologue", "speaker": p.get("speaker") or None,
                     "text": p.get("text", ""), "code": code,
                     "face": CODE_SPRITE.get(code), "tags": [], "cmds": []})
    return msgs
