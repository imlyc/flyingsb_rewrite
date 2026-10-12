"""把主线剧本条目 (messages.json scene=="P") 回挂到**带演出标签的过场原文**.

背景
----
`assets/script/messages.json` 的 P 条目是主线对白, 但**丢失了演出标签**
(`<$CODE:帧号>` 立绘 / `<BGMnn>` 等); 而 `assets/script/scenario_full.txt`
是从 exe 剧本区按地址块 dump 的**原文**, 保留了完整演出标签, 例如:

    <$MIRO:3016><WA><$MIRO:1302>  ← 美娜立绘 (帧号属 core.npc_sprites 全局空间)
    <$SON:3022>                   ← 孙悟空立绘 (可与美娜同框)

做法
----
按文本匹配把每个 P 条目定位到 scenario_full 的那一行, 取出更完整的原文存成
`assets/script/cutscenes.json`: {p_index: 原文}. 游戏侧优先用它播过场,
于是立绘/演出标签就生效了 (解析见 core.script_text.parse)。

跑法: rewrite/ 下  venv/Scripts/python -m tools.extract_cutscenes
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MESSAGES = ROOT / "assets" / "script" / "messages.json"
SCENARIO = ROOT / "assets" / "script" / "scenario_full.txt"
OUT = ROOT / "assets" / "script" / "cutscenes.json"
MAIN_SCENE = "P"

TAG_RE = re.compile(r"<[^<>\x00\r\n]{1,24}>")
NEWLINE_TAGS = ("<br_r>", "<BR>", "<br_R>")
MIN_KEY = 10          # 用于匹配的最短文本片段


def clean(text: str) -> str:
    """剥掉剧本标记, 得到可比对的纯文本 (与 core.script_text 的分页规则一致)."""
    s = text or ""
    for nt in NEWLINE_TAGS:
        s = s.replace(nt, "\n")
    s = TAG_RE.sub("", s)
    s = s.replace("|", "\n").replace("@", "").strip()
    return s


def build_index(lines: list[str]) -> list[tuple[str, str]]:
    """[(清洗后文本, 原文)]"""
    return [(clean(l), l) for l in lines if l.strip()]


def main() -> int:
    if not MESSAGES.exists() or not SCENARIO.exists():
        print("[skip] 缺 messages.json / scenario_full.txt")
        return 1

    data = json.loads(MESSAGES.read_text(encoding="utf-8"))
    p_items = [(i, m) for i, m in enumerate(data)
               if m.get("scene") == MAIN_SCENE and (m.get("text") or "").strip()]
    lines = SCENARIO.read_text("utf-8", errors="replace").splitlines()
    index = build_index(lines)

    out: dict[str, str] = {}
    for idx, m in p_items:
        key = clean(m.get("text") or "")
        if len(key) < MIN_KEY:
            continue
        probe = key[:24]
        for ctext, craw in index:
            if probe and probe in ctext:
                # 只接受"演出标签更多"的那一版, 否则没有换的价值
                if tag_count(craw) > tag_count(m.get("text") or ""):
                    out[str(idx)] = craw
                break

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"P 条目 {len(p_items)} → 回挂到带演出标签的过场原文 {len(out)} 条")
    print(f"→ {OUT.relative_to(ROOT)}")
    for k in list(out)[:5]:
        print(f"  P[{k}] {out[k][:70]}")
    return 0


def tag_count(text: str) -> int:
    return len(TAG_RE.findall(text or ""))


if __name__ == "__main__":
    sys.exit(main())
