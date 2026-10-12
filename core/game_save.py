"""整局存档 (remake 自有格式).

原版 `.dat` (15232B) 只含**角色/金钱/剧情 flags**, 不含本 remake 的背包/宝箱/世界访问/
剧情节点进度, 故此处用独立 JSON 存档 (可读、可手改), 落在 `<repo>/saves/saveN.json`:

    {version, saved_at, place, world:{base,x,y}, save:{...}, story:{done,flags}}

角色数值用 `Character.to_bytes()` 的 hex (与原版二进制同布局), 便于回写/对照。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.character import TOTAL_SLOTS, Character
from core.inventory import Inventory
from core.save_manager import FLAGS_END, FLAGS_START, SAVE_SIZE, SaveData

ROOT = Path(__file__).resolve().parents[1]
SAVE_DIR = ROOT / "saves"
SLOT_COUNT = 3
VERSION = 1


@dataclass
class LoadedGame:
    """一次读档的结果 (世界场景按此重建)."""

    save: SaveData
    base: str
    x: int
    y: int
    done: set
    flags: set


def slot_path(slot: int) -> Path:
    return SAVE_DIR / f"save{slot + 1}.json"


_PLACE_CACHE: dict[str, str] | None = None


def _place_map() -> dict[str, str]:
    """base → 中文地名 (优先世界地图表的 name_s, 其次 world_graph 的命名地点)."""
    global _PLACE_CACHE
    if _PLACE_CACHE is None:
        m: dict[str, str] = {}
        try:
            from core import world_graph as wg
            for b, name in wg.named_locations():
                m.setdefault(b, name)
        except Exception:
            pass
        try:
            p = ROOT / "assets" / "worldmap_locations.json"
            for loc in json.loads(p.read_text(encoding="utf-8"))["locations"]:
                if loc.get("base") and loc.get("name_s"):
                    m.setdefault(loc["base"], loc["name_s"])
        except Exception:
            pass
        _PLACE_CACHE = m
    return _PLACE_CACHE


def _place_name(base: str) -> str:
    return _place_map().get(base, base)


def slot_summary(slot: int) -> dict | None:
    """该槽的摘要 (供存档/读档界面显示); 空槽返回 None."""
    p = slot_path(slot)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    party = d.get("party_info")
    if not party:                       # 旧档: 用角色名 + 角色块里的 Level 现算
        from core.character import CHARACTER_NAMES, PLAYABLE_SLOTS, Character
        chs = {}
        for rec in d.get("save", {}).get("characters", []):
            try:
                chs[int(rec["slot"])] = Character.from_bytes(bytes.fromhex(rec["data"]), 0)
            except Exception:
                pass
        party = [[CHARACTER_NAMES.get(s, "?"),
                  int(chs[s].Level) if s in chs else 0]
                 for s in PLAYABLE_SLOTS if s in chs and chs[s].MaxHP > 0]
    return {
        "place": d.get("place") or _place_name(d.get("world", {}).get("base", "")),
        "money": d.get("save", {}).get("money", 0),
        "saved_at": d.get("saved_at", ""),
        "party": d.get("party", []),
        "party_info": party,
    }


def save_game(save: SaveData, director_state, base: str, x: int, y: int,
              slot: int) -> Path:
    """把当前进度写入槽位; 返回文件路径."""
    chars = []
    for slot_i in range(TOTAL_SLOTS):
        ch = save.characters.get(slot_i)
        if ch is None:
            continue
        chars.append({
            "slot": slot_i,
            "data": ch.to_bytes().hex(),
            "skills": list(getattr(ch, "skills", []) or []),
        })
    # 队伍 + 等级 (存档槽界面显示用)
    party_names = list(getattr(director_state, "party", []) or [])
    try:
        from core import party as party_mod
        name_to_slot = party_mod.NAME_TO_SLOT
    except Exception:
        name_to_slot = {}
    party_info = []
    for nm in party_names:
        sl = name_to_slot.get(nm)
        ch = save.characters.get(sl) if sl is not None else None
        party_info.append([nm, int(ch.Level) if ch is not None else 0])
    data = {
        "version": VERSION,
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "place": _place_name(base),
        "world": {"base": base, "x": int(x), "y": int(y)},
        "party": party_names,
        "party_info": party_info,
        "save": {
            "location": save.location,
            "flag": save.flag,
            "state": list(save.state),
            "money": save.money,
            "flags": save.flags.hex(),
            "characters": chars,
            "inventory": [[iid, n] for iid, n in save.inventory.sorted()],
            "chests_opened": list(save.chests_opened),
            "world_visited": list(save.world_visited),
        },
        "story": {
            "done": sorted(getattr(director_state, "done", []) or []),
            "flags": sorted(getattr(director_state, "flags", []) or []),
        },
    }
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    p = slot_path(slot)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def load_game(slot: int) -> LoadedGame | None:
    p = slot_path(slot)
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    s = d.get("save", {})

    characters: dict[int, Character] = {}
    for slot_i in range(TOTAL_SLOTS):
        characters[slot_i] = Character(
            MaxHP=0, CurrentHP=0, MaxMP=0, CurrentMP=0, Level=0, SG=0,
            Unknow_1=0, Exp=0, nextExp=0,
            Unknow_2=0, Unknow_3=0, Unknow_4=0, Unknow_5=0, Unknow_6=0,
            Unknow_7=0, Unknow_8=0,
            Power=0, Wisdom=0, Agile=0, Attack=0, Defence=0, Luck=0,
            Unknow_9=0,
            Head=0xFFFFFFFF, Body=0xFFFFFFFF, Hand=0xFFFFFFFF,
            Accessories1=0xFFFFFFFF, Accessories2=0xFFFFFFFF,
        )
    for rec in s.get("characters", []):
        try:
            ch = Character.from_bytes(bytes.fromhex(rec["data"]), 0)
            ch.skills = list(rec.get("skills") or [])
            characters[int(rec["slot"])] = ch
        except Exception:
            continue

    inv = Inventory()
    for iid, n in s.get("inventory", []):
        inv.add(int(iid), int(n))

    save = SaveData(
        location=s.get("location", ""),
        flag=int(s.get("flag", 0)),
        state=tuple(s.get("state") or (0, 0, 0, 0, 0)),
        money=int(s.get("money", 0)),
        characters=characters,
        inventory=inv,
        chests_opened=list(s.get("chests_opened") or []),
        world_visited=list(s.get("world_visited") or []),
        flags=bytes.fromhex(s["flags"]) if s.get("flags") else
        bytes(FLAGS_END - FLAGS_START),
        raw=bytes(SAVE_SIZE),
    )
    w = d.get("world", {})
    st = d.get("story", {})
    return LoadedGame(
        save=save,
        base=w.get("base") or "TBB0___P",
        x=int(w.get("x", 0)),
        y=int(w.get("y", 0)),
        done=set(st.get("done") or []),
        flags=set(st.get("flags") or []),
    )


def delete_slot(slot: int) -> None:
    slot_path(slot).unlink(missing_ok=True)
