"""提取开场 + 序章剧情对白 (按页) → assets/script/prologue.json; 顺带脚本条目表 → script_entries.json.

来源 FlyingSB.exe 剧本区 (Big5), 文件偏移 0x2A0CDA ("幻想西遊記" 后) 起:
  段0 开场 (一切的开端): 樂神奏乐封印孙悟空于金铁山 (200 年前)   0x2A0CDA
  段1 序章: 天宫 / 美娜公主 (禁断之卵)                            0x2A2400
  段2 小森林 (车坏)                                               0x2A6684
文本语法: `;` 分页, `<$CODE>` 说话人/立绘代号 (`<$CODE:NNNN>` 带立绘帧), `|` 换行, `*..*` 强调.
分页规则: `;` 与每个 `<$CODE>` 处切页 (换人 = 新页); 立绘代号跨页保持 (原版引擎行为).

脚本条目表 (seq 场景表, 文件偏移 ~0x2A1060 起): 每项 `[80][文本 ptr u32][00 00][代号 4B 反转]`,
给出每个剧本块的基准说话人, 用来在块起点重置说话人.

逻辑移植自 mygame (baozi 之外的另一位贡献者, 2026-10) 的 extract_prologue.py / parse_script_entries.py.
跑法: cd rewrite && venv/bin/python -m tools.extract_prologue
"""
from __future__ import annotations

import json
import os
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = Path(os.environ.get("FLYINGSB_ORIGIN", ROOT.parent / "origin" / "flyingsb"))
EXE = Path(os.environ.get("FLYINGSB_EXE", ORIGIN / "FlyingSB.exe"))
OUT_DIR = ROOT / "assets" / "script"
OUT = OUT_DIR / "prologue.json"
ENTRIES_OUT = OUT_DIR / "script_entries.json"
IMAGE_BASE = 0x400000

LO, HI = 0x2A0CDA, 0x2A6890          # 序章文本区 (文件偏移)
ENTRIES_LO, ENTRIES_HI = 0x2A1000, 0x2A8000
CLEAN_REGION = (0x2A2400, 0x2A6890)  # 已知无二进制污染的样本区, 用来学"合法汉字"词表

SPEAKER = {
    "RACH": "蕾琪兒", "DIT": "迪特", "MIRO": "美娜", "OK": "玉皇大帝",
    "SOL": "侍衛", "SOL1": "侍衛", "SOL2": "侍衛", "CAP": "侍衛隊長",
    "GL": "妖怪", "GR": "妖怪", "MASK": "蒙面人",
    "SON": "孫悟空", "SON5": "孫悟空", "SONA": "樂神傑特",
    "MES1": "", "MES": "", "P": "美娜", "SABUN": "", "TAIL": "", "STEM": "",
}
TAG = re.compile(r"<[^<>\x00\r\n]{1,24}>")
SPLIT = re.compile(r"(<\$[A-Za-z=][^<>\x00]{0,20}>)")
CODE = re.compile(r"<\$=?([A-Za-z][A-Za-z0-9_]*)(?::\d+)?>")
CLEAN_OK = re.compile(r"^[\s　-鿿＀-￯!-\?0-9A-Za-z，。、？！…「」『』（）:：;*\-~]+$")


def clean(chunk: str) -> str:
    s = re.sub(r"<&[^<>]*>", "", chunk)
    s = TAG.sub("", s)
    s = s.replace("|", "\n").replace("*", "")
    parts = []
    for ln in s.split("\n"):
        ln = ln.strip().lstrip("@/").strip()
        if ln:
            parts.append(ln)
    return "\n".join(parts)


def valid(text: str) -> bool:
    return len(text) >= 3 and bool(CLEAN_OK.match(text))


def is_text_bytes(b: bytes) -> bool:
    """字节级 Big5 校验: ASCII 可打印/空白 或合法 Big5 双字节; 二进制块会被拒."""
    i, n = 0, len(b)
    while i < n:
        c = b[i]
        if c in (0x0A, 0x0D, 0x09) or 0x20 <= c <= 0x7E:
            i += 1
            continue
        if 0xA1 <= c <= 0xF9 and i + 1 < n and (0x40 <= b[i + 1] <= 0x7E or 0xA1 <= b[i + 1] <= 0xFE):
            i += 2
            continue
        return False
    return True


def cjk_ok(text: str, vocab: set[str] | None) -> bool:
    if not vocab:
        return True
    cjk = [c for c in text if "一" <= c <= "鿿"]
    if len(cjk) < 3:
        return True
    return sum(1 for c in cjk if c not in vocab) / len(cjk) <= 0.6


def learn_vocab(data: bytes) -> set[str]:
    vocab: set[str] = set()
    for chunk in re.split(rb"[;\x00]", data[CLEAN_REGION[0]:CLEAN_REGION[1]]):
        if not is_text_bytes(chunk):
            continue
        try:
            vocab.update(clean(chunk.decode("big5")))
        except Exception:
            continue
    return vocab


def script_entries(data: bytes) -> list[dict]:
    """脚本条目表: [{off, ptr, code, text}]."""
    out = []
    for m in re.finditer(rb"\x80", data[ENTRIES_LO:ENTRIES_HI]):
        i = ENTRIES_LO + m.start()
        ptr = struct.unpack_from("<I", data, i + 1)[0]
        if not (0x6A0000 <= ptr < 0x6B0000):
            continue
        code = data[i + 6:i + 10]
        if not all(33 <= c < 127 for c in code):
            continue
        o = ptr - IMAGE_BASE
        e = data.find(b"\x00", o)
        if e < 0 or e > o + 3000:
            e = o + 3000
        txt = data[o:e].decode("big5", "replace")
        if not txt:
            continue
        out.append({"off": i, "ptr": hex(ptr), "code": code[::-1].decode("latin1"), "text": txt})
    return out


def parse_region(seg: bytes, vocab: set[str] | None, blockmap: dict[int, str]) -> list[dict]:
    pages: list[dict] = []
    cur_spk = cur_code = ""
    pos = 0
    for sep in re.finditer(rb"[;\x00]", seg):
        chunk = seg[pos:sep.start()]
        start = pos
        pos = sep.end()
        if not is_text_bytes(chunk) or (b"<" not in chunk and b"@" not in chunk):
            continue
        for boff in range(start, min(start + 3, len(seg))):
            if boff in blockmap:                 # 脚本块起点: 重置基准说话人
                cur_code = blockmap[boff]
                cur_spk = SPEAKER.get(cur_code, "")
                break
        try:
            raw = chunk.decode("big5")
        except Exception:
            continue
        if not CODE.search(raw) and re.search(r"<(?:TRANS|B)>", raw):
            cur_spk = cur_code = ""              # 转场块无说话人 → 旁白
        for part in SPLIT.split(raw):
            m = CODE.match(part) if part.startswith("<") else None
            if m:
                c = m.group(1)
                if c in SPEAKER:
                    cur_spk = SPEAKER[c]
                cur_code = c
                continue
            txt = clean(part)
            if valid(txt) and cjk_ok(txt, vocab):
                pages.append({"speaker": cur_spk, "text": txt, "code": cur_code})
    return pages


def extract(exe: Path = EXE) -> tuple[list[dict], list[dict]]:
    data = exe.read_bytes()
    entries = script_entries(data)
    blockmap = {}
    for e in entries:
        rel = int(e["ptr"], 16) - IMAGE_BASE - LO
        if 0 <= rel < (HI - LO):
            blockmap[rel] = e["code"]
    pages = parse_region(data[LO:HI], learn_vocab(data), blockmap)
    return pages, entries


def main() -> int:
    pages, entries = extract()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(pages, ensure_ascii=False, indent=1), encoding="utf-8")
    ENTRIES_OUT.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"脚本条目 {len(entries)} 条 → {ENTRIES_OUT}")
    print(f"序章对白 {len(pages)} 页 → {OUT}")
    for p in pages[:6]:
        print(f"  [{p['speaker'] or '旁白'}] {p['text'].replace(chr(10), ' / ')[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
