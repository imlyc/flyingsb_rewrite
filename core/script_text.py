"""原版剧本的读取与标记解析 (供剧情回放 / 地图 NPC 对白共用).

数据源: `assets/script/script_table.json`
  由 `tools/extract_script_table.py` 提取, 是原版「位置/角色 ID → 剧本分支」的
  669 项分派表 (VA 0x467006 的跳转表)。

原版剧本标记 (语义见 tools/extract_script.py 顶部):
  `<msg_id=X>` / `<#X>`    说话人 (显示名 > 立绘名 > 剧本段名)
  `<ids_NAME>`             立绘 / 显示名
  `<&itemNNN>`             获得道具 (解析成 core.items 的中文名)
  `<$NAME:NNN>` / `<$NAME>` 立绘 / 语音 / BGM
  `<WidthM|L|XL> <HMaxN> <push> <pop> <D0N> <dir..> <pos..> <TailX>`
                           显示控制 (玩家看不到, 收进 notes)
  `;`   一条消息结束 → 一个对话框 (一条记录 = 多个对话框的序列)
  `|`   换行
  `@` / `@@`  段首缩进标记 (渲染时剥掉)
  `*文字*`    强调
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "assets" / "script" / "script_table.json"

TAG_RE = re.compile(r"<[^<>\x00\r\n]{1,24}>")
EMPH_RE = re.compile(r"\*(.+?)\*", re.S)
NEWLINE_TAGS = ("<br_r>", "<BR>", "<br_R>")

# 立绘/语音指令 `<$CODE:帧号>` (带冒号) vs BGM 指令 `<$NAME>` (无冒号).
# 帧号是 core.npc_sprites 的全局编号空间 (与原版 jmp.c0 同一空间), 可直接出图.
PORTRAIT_RE = re.compile(r"<\$([^<>]*:[^<>]*)>")
# 数值型 BGM 指令 `<BGMnn>`: nn 查 core.bgm_table (exe 0x1464c4 的 58 项指针表).
BGM_RE = re.compile(r"<BGM(\d+)>", re.I)

Run = tuple[str, bool]          # (文本, 是否强调)
Line = list[Run]
Page = list[Line]               # 一个对话框 = 若干行


def _item_label(arg: str) -> str:
    """`<&item329>` / `<&item%d>` → 道具名."""
    if "%" in arg:                       # 剧本变量 (运行时填入), 非固定道具
        return "道具(剧本变量)"
    num = "".join(ch for ch in arg if ch.isdigit())
    if not num:
        return f"道具[{arg}]"
    try:
        from core.items import get_item_name
        return get_item_name(int(num))
    except Exception:
        return f"道具#{num}"


def parse(raw: str) -> dict:
    """原版剧本原文 → {speaker, notes, pages, portraits}.

    pages 是对话框序列; 每个对话框是若干行; 每行是 [(文本, 是否强调)] 的片段。
    portraits 与 pages 一一对应: 该页要显示的**原版立绘帧号列表** (可多人同框),
    取自 `<$CODE:帧号>` 标签 —— 判定见 PORTRAIT_RE。
    """
    msg_id = sharp = disp = None
    notes: list[str] = []
    for t in TAG_RE.findall(raw):
        if t.startswith("<msg_id="):
            msg_id = t[len("<msg_id="):-1]
        elif t.startswith("<#") and len(t) > 3:
            sharp = t[2:-1]                     # <#P> = 显示名
        elif t.startswith("<ids_"):
            disp = t[len("<ids_"):-1]           # <ids_輔助天使> = 立绘/名
        elif t.startswith("<&"):
            notes.append("道具 → " + _item_label(t[2:-1]))
        elif t.startswith("<$"):
            notes.append("演出 → " + t[1:-1])
    speaker = sharp or disp or msg_id           # 显示名 > 立绘名 > 剧本段名
    if msg_id and msg_id != speaker:
        notes.append(f"剧本段 {msg_id}")

    s = raw
    for nt in NEWLINE_TAGS:
        s = s.replace(nt, "\n")
    s = re.sub(r"<&[^<>]*>", lambda m: "「" + _item_label(m.group(0)[2:-1]) + "」", s)
    s = TAG_RE.sub("", s)
    s = s.replace("|", "\n")

    # 逐页取原版立绘: <$CODE:帧号> (带冒号才成立绘, 无冒号的 <$NAME> 是 BGM 指令).
    # 立绘在该页切换后保持到下次切换 (原版语义), 故用 cur_frames 跨页延续.
    raw_chunks = raw.split(";")
    pages: list[Page] = []
    portraits: list[list[int]] = []
    bgms: list[int | None] = []
    cur_frames: list[int] = []
    cur_bgm: int | None = None
    for _i, chunk in enumerate(s.split(";")):
        frames: list[int] = []
        bgm_now: int | None = None
        if _i < len(raw_chunks):
            for inner in PORTRAIT_RE.findall(raw_chunks[_i]):
                _code, sep, num = inner.partition(":")
                if not sep:
                    continue
                dig = "".join(c for c in num if c.isdigit())
                if dig:
                    frames.append(int(dig))
            _bm = BGM_RE.search(raw_chunks[_i])
            if _bm:
                bgm_now = int(_bm.group(1))
        if frames:
            cur_frames = frames
        if bgm_now is not None:
            cur_bgm = bgm_now          # BGM 同样在该页切换后延续
        lines: Line = []
        for ln in chunk.split("\n"):
            ln = ln.lstrip("@").strip()
            if not ln:
                continue
            runs: Line = []
            pos = 0
            for m in EMPH_RE.finditer(ln):
                if m.start() > pos:
                    runs.append((ln[pos:m.start()], False))
                runs.append((m.group(1), True))
                pos = m.end()
            if pos < len(ln):
                runs.append((ln[pos:], False))
            if runs:
                lines.append(runs)
        if lines:
            pages.append(lines)
            portraits.append(list(cur_frames))
            bgms.append(cur_bgm)
    # "bgm": 本段第一条非空的 BGM (给不需要逐句切乐的调用方); "bgms": 逐页
    first_bgm = next((b for b in bgms if b is not None), None)
    return {"speaker": speaker, "notes": notes, "pages": pages,
            "portraits": portraits, "bgms": bgms, "bgm": first_bgm}


def raw_text(entry: dict, simplified: bool = True) -> str:
    """取原文; simplified=True 优先用工具生成的 t2s 简体版 (原版是 Big5 繁体)."""
    if simplified:
        return entry.get("s") or entry.get("text") or ""
    return entry.get("text") or ""


def load_table(path: Path = TABLE) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


_TABLE_CACHE: dict[int, dict] | None = None


def table_by_id() -> dict[int, dict]:
    """script_id → 条目 (进程内缓存)."""
    global _TABLE_CACHE
    if _TABLE_CACHE is None:
        _TABLE_CACHE = {e["id"]: e for e in load_table()}
    return _TABLE_CACHE


def entry(script_id: int) -> dict | None:
    return table_by_id().get(script_id)


def has_dialogue(script_id: int) -> bool:
    e = entry(script_id)
    return bool(e and not e.get("default") and e.get("text"))


def first_line(script_id: int, simplified: bool = True) -> str:
    """该剧本第一行 (列表摘要 / 调试用)."""
    e = entry(script_id)
    if e is None:
        return "(无此剧本)"
    if e.get("default"):
        return "(原版此位置无对白)"
    pages = parse(raw_text(e, simplified))["pages"]
    return "".join(t for t, _ in pages[0][0]) if pages else ""


def to_messages(script_id: int, simplified: bool = True) -> list[dict]:
    """转成 scenes.dialogue.DialogueScene 可播的 messages (一个对话框 = 一条).

    messages 项: {scene, speaker, text, tags, cmds}
      · text 用 "\\n" 分行, 由 DialogueScene 自动折行;
      · cmds 里塞演出/道具提示 (cmd="note")。
    """
    e = entry(script_id)
    if e is None:
        return []
    if e.get("default") or not e.get("text"):
        return [{"scene": script_id, "speaker": None, "tags": [], "cmds": [],
                 "text": "（原版这个位置没有对白）"}]
    parsed = parse(raw_text(e, simplified))
    cmds = [{"cmd": "note", "arg": n} for n in parsed["notes"]]
    ports = parsed.get("portraits") or []
    out = []
    for _i, page in enumerate(parsed["pages"]):
        lines = ["".join(t for t, _ in line) for line in page]
        if not lines:
            continue
        out.append({"scene": script_id, "speaker": parsed["speaker"],
                    "text": "\n".join(lines), "tags": [], "cmds": cmds,
                    "portraits": ports[_i] if _i < len(ports) else []})
    return out
