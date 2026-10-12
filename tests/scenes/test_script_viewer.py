"""scenes/script_viewer 的剧本标记解析测试 (B 剧情回放).

原版剧本标记语义见 tools/extract_script.py 顶部:
  `;` 一条消息结束(= 一个对话框)   `|` 换行   `@` 段首缩进   `*x*` 强调
  `<msg_id=X>` / `<#X>` 说话人   `<ids_X>` 立绘名   `<&itemNNN>` 道具
"""

from __future__ import annotations

import pytest

from scenes.script_viewer import (
    entry_summary,
    load_script_table,
    parse_script_text,
    raw_text,
)


def _lines(page) -> list[str]:
    return ["".join(t for t, _ in line) for line in page]


def test_pages_split_by_semicolon():
    """`;` 分对话框, `|` 只在框内换行."""
    p = parse_script_text("第一句.|第二行;下一句.;")
    assert len(p["pages"]) == 2
    assert _lines(p["pages"][0]) == ["第一句.", "第二行"]
    assert _lines(p["pages"][1]) == ["下一句."]


def test_speaker_priority():
    assert parse_script_text("<msg_id=NPC><#P>你好.;")["speaker"] == "P"
    assert parse_script_text("<msg_id=NPC>你好.;")["speaker"] == "NPC"
    assert parse_script_text("<ids_輔助天使>你好.;")["speaker"] == "輔助天使"


def test_msg_id_kept_as_note():
    p = parse_script_text("<msg_id=NPC><#P>你好.;")
    assert any("NPC" in n for n in p["notes"])


def test_emphasis_runs():
    runs = parse_script_text("叫*五行山*的山.;")["pages"][0][0]
    assert [t for t, _ in runs] == ["叫", "五行山", "的山."]
    assert [e for _, e in runs] == [False, True, False]


def test_at_marker_and_br_r():
    p = parse_script_text("<WidthXL>@@您好.<br_r>再見.;")
    assert _lines(p["pages"][0]) == ["您好.", "再見."]


def test_display_tags_removed():
    p = parse_script_text("<WidthM>@@<+><fast>你好.;")
    assert _lines(p["pages"][0]) == ["你好."]


def test_item_resolved_to_name():
    """<&item199> → core.items 里的名字 (199 = 如意棒, 见 core/items.py 锚点)."""
    p = parse_script_text("得到<&item199>.;")
    assert _lines(p["pages"][0]) == ["得到「如意棒」."]


def test_item_variable_marked():
    p = parse_script_text("得到<&item%d>.;")
    assert any("剧本变量" in n for n in p["notes"])


def test_empty_text():
    p = parse_script_text("")
    assert p["pages"] == [] and p["speaker"] is None


def test_entry_summary_default():
    assert "Default" in entry_summary({"default": True, "text": "x"})


def test_entry_summary_first_line():
    e = {"text": "<WidthM>@@你好.|再見.;"}
    assert entry_summary(e, simplified=False) == "你好."


def test_raw_text_prefers_simplified():
    e = {"text": "這裡", "s": "这里"}
    assert raw_text(e, True) == "这里"
    assert raw_text(e, False) == "這裡"


def test_script_table_asset_if_present():
    """产物存在时校验结构 (未跑 extract_script_table 则跳过)."""
    table = load_script_table()
    if not table:
        pytest.skip("assets/script/script_table.json 未生成")
    assert len(table) == 669
    assert all(("id" in e and "code" in e) for e in table)
    # 19 条落到原版 default 分支; 另有 1 条文本为空 → 共 20 条无对白
    assert sum(1 for e in table if e.get("default")) == 19
    assert sum(1 for e in table if not e.get("text")) == 1
