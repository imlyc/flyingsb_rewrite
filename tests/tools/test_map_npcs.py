"""assets/map_npcs.json 校验 (A: 地图角色的 FC/位置放置数据).

数据来自 tools/extract_map_npcs.py: 解析 .mfo 的 pcpos + jmp,
得到「每张地图上每个角色的 (x, y, 朝向, 精灵帧, 位置/剧本 ID)」。

关键结论: 该 ID 同时是「传送目标位置 ID」与「script_table 的索引」
(原版位置表与剧本表共用同一套 ID 空间)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "assets" / "map_npcs.json"
TABLE = ROOT / "assets" / "script" / "script_table.json"

pytestmark = pytest.mark.skipif(
    not ASSET.exists(),
    reason="assets/map_npcs.json 未生成 (先跑 tools.extract_map_npcs)")


@pytest.fixture(scope="module")
def data() -> dict:
    return json.loads(ASSET.read_text(encoding="utf-8"))


def test_all_maps_covered(data):
    assert len(data["maps"]) == 487
    assert data["stats"]["npcs"] > 1000


def test_entries_carry_position_and_script(data):
    for base, m in list(data["maps"].items())[:80]:
        for e in m["npcs"] + m["doors"]:
            assert isinstance(e["x"], int) and isinstance(e["y"], int)
            assert isinstance(e["target"] if "target" in e else e["script"], int)


def test_most_entries_resolve_to_real_dialogue(data):
    """位置 ID 能当剧本索引用 —— 这是「共用 ID 空间」的直接证据."""
    total = data["stats"]["npcs"]
    real = data["stats"]["npcs_with_dialogue"]
    assert real / total > 0.9, f"只有 {real}/{total} 能解出对白"


@pytest.mark.parametrize("base,script,keyword", [
    ("TAS0___P", 18, "五指村"),
    ("TAL0___P", 353, "阿尔夏"),
    ("TAL0___P", 351, "酒店"),
])
def test_known_npc_dialogues(data, script, keyword, base):
    """已知地图上的角色对白与地图主题吻合 (人肉核对过的锚点)."""
    texts = [e.get("text", "") for e in data["maps"][base]["npcs"]
             if e["script"] == script]
    assert texts, f"{base} 里没有 script={script} 的角色"
    assert any(keyword in t for t in texts), texts


def test_script_ids_exist_in_table(data):
    if not TABLE.exists():
        pytest.skip("script_table.json 未生成")
    ids = {e["id"] for e in json.loads(TABLE.read_text("utf-8"))}
    used = {e["script"] for m in data["maps"].values() for e in m["npcs"]}
    assert used <= ids, sorted(used - ids)[:10]
