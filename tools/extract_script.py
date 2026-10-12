"""从 FlyingSB.exe 提取并解析原版剧情剧本 (只读).

原版剧本以 Big5 明文嵌在 exe 里, 是**线性脚本流**:
  · NUL 分隔记录, 一条消息以 ';' 结束, '|' 表示换行, '@' 段首标记
  · <msg_id=X> / <#X>   说话人
  · <$SON:1413>         角色立绘/语音 (SON/MIRO/MASK... = 角色代号, :N = 编号)
  · <$SONA> <$MIRO>     BGM 指令 (对应 Data/*.WAV)
  · <&item329>          获得道具
  · <br_r> <D1..D8> <DIR2/4/6/8> <possub_u> <widthXL> <TailX>  显示/换行/朝向控制

输出 (assets/script/):
  scenario_full.txt  剧本区完整可读文本 (带偏移锚点)
  stats.json         规模统计 (区域/条目/字符/标签直方图/msg_id)
  messages.json      结构化对白: [{scene, speaker, text, tags, cmds}]

跑法: cd rewrite && venv/Scripts/python -m tools.extract_script
"""

from __future__ import annotations

import collections
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = Path(os.environ.get("FLYINGSB_ORIGIN", ROOT.parent / "origin" / "flyingsb"))
EXE = Path(os.environ.get("FLYINGSB_EXE", ORIGIN / "FlyingSB.exe"))
OUT = ROOT / "assets" / "script"

TAG_RE = re.compile(r"<[^<>\x00\r\n]{1,24}>")

BLOCK = 1024          # 区域探测窗口
CJK_THRESHOLD = 0.40  # 窗口内 Big5 双字节占比阈值

# 已知的非对白标签 (纯显示控制, 不算指令)
_DISPLAY_TAGS = {
    "br_r", "<br_r>", "->", "<->", "+", "<+>", "x", "<x>", "TailX", "<TailX>",
    "BR", "<BR>", "widthXL", "<widthXL>",
}


def _cjk_ratio(block: bytes) -> float:
    pairs = 0
    i = 0
    n = len(block)
    while i < n - 1:
        if 0xA1 <= block[i] <= 0xF9 and (0x40 <= block[i + 1] <= 0x7E
                                         or 0xA1 <= block[i + 1] <= 0xFE):
            pairs += 2
            i += 2
        else:
            i += 1
    return pairs / max(1, n)


def find_regions(data: bytes) -> list[tuple[int, int]]:
    marks = []
    for lo in range(0, len(data), BLOCK):
        hi = min(len(data), lo + BLOCK)
        marks.append((lo, hi, _cjk_ratio(data[lo:hi]) >= CJK_THRESHOLD))
    regions = []
    cur = None
    for lo, hi, is_text in marks:
        if is_text:
            cur = [lo, hi] if cur is None else [cur[0], hi]
        else:
            if cur is not None and cur[1] - cur[0] >= BLOCK:
                regions.append(tuple(cur))
            cur = None
    if cur is not None and cur[1] - cur[0] >= BLOCK:
        regions.append(tuple(cur))
    return regions


def render(data: bytes, lo: int, hi: int) -> str:
    """字节段 → 可读文本: Big5 文本 + <tag> 原样, NUL → 换行."""
    out = []
    i = lo
    while i < hi:
        b = data[i]
        if b == 0:
            out.append("\n")
            i += 1
        elif b == 0x3C:
            j = data.find(b">", i, min(hi, i + 40))
            if j != -1:
                out.append(data[i:j + 1].decode("big5", "replace"))
                i = j + 1
            else:
                i += 1
        elif 0xA1 <= b <= 0xF9 and i + 1 < hi and (
                0x40 <= data[i + 1] <= 0x7E or 0xA1 <= data[i + 1] <= 0xFE):
            out.append(data[i:i + 2].decode("big5", "replace"))
            i += 2
        elif 32 <= b < 127:
            out.append(chr(b))
            i += 1
        else:
            i += 1
    return "".join(out)


def _is_diverse(body: str) -> bool:
    """判断一段文本是否"像人话": 最高频字符占比不能过高 (二进制填充会单字刷屏)."""
    if len(body) < 20:
        return False
    top = max(collections.Counter(body).values())
    return top / len(body) < 0.22


def _cjk_count(s: str) -> int:
    return sum(1 for ch in s if "\u3400" <= ch <= "\u9fff")


def parse_message(seg: str, scene: str | None) -> dict | None:
    """把一段文本解析成对白结构."""
    tags = TAG_RE.findall(seg)
    speaker = None
    cmds: list[dict] = []
    for t in tags:
        if t.startswith("<msg_id="):
            speaker = t[len("<msg_id="):-1]
        elif t.startswith("<#") and t.endswith(">"):
            speaker = t[2:-1]
        elif t.startswith("<&"):
            cmds.append({"cmd": "item", "arg": t[2:-1]})
        elif t.startswith("<$") and t.endswith(">"):
            inner = t[2:-1]
            name, sep, num = inner.partition(":")
            cmds.append({"cmd": "voice" if sep else "bgm/portrait",
                         "name": name, "n": int(num) if num.isdigit() else None})
    text = TAG_RE.sub("", seg)
    text = text.replace("|", "\n").strip()
    if not text and not tags:
        return None
    return {"scene": scene, "speaker": speaker, "text": text,
            "tags": tags, "cmds": cmds}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not EXE.exists():
        print(f"[skip] 找不到 exe: {EXE}")
        return 1
    data = EXE.read_bytes()
    print(f"exe: {EXE.name}  size={len(data)}")

    regions = find_regions(data)
    total = sum(hi - lo for lo, hi in regions)
    print(f"剧本区: {len(regions)} 段, 共 {total} 字节 ({total * 100 // len(data)}%)")

    OUT.mkdir(parents=True, exist_ok=True)
    tag_hist: collections.Counter = collections.Counter()
    msg_ids: collections.Counter = collections.Counter()
    messages: list[dict] = []
    cur_scene: str | None = None

    with (OUT / "scenario_full.txt").open("w", encoding="utf-8") as f:
        for lo, hi in regions:
            text = render(data, lo, hi)
            body = TAG_RE.sub("", text).replace("\n", "").replace(" ", "")
            if _cjk_count(body) / max(1, len(body)) < 0.35:
                continue                      # 整段中文占比过低 → 非剧本区
            if not _is_diverse(body):
                continue                      # 单字重复率过高 → 二进制误判区
            f.write(f"\n\n========== 0x{lo:06x}..0x{hi:06x} ==========\n")
            f.write(text)
            for line in text.split("\n"):
                for seg in line.split(";"):
                    seg = seg.strip()
                    if not seg:
                        continue
                    for t in TAG_RE.findall(seg):
                        tag_hist[re.sub(r"=\S*", "=*", t)] += 1
                        if t.startswith("<msg_id="):
                            cur_scene = t[len("<msg_id="):-1]
                            msg_ids[cur_scene] += 1
                    m = parse_message(seg, cur_scene)
                    if m and (m["cmds"] or _cjk_count(m["text"]) >= 2):
                        messages.append(m)

    stats = {
        "exe": EXE.name, "exe_size": len(data),
        "regions": [[lo, hi] for lo, hi in regions],
        "region_bytes": total,
        "messages": len(messages),
        "chars": sum(len(m["text"]) for m in messages),
        "msg_ids": dict(msg_ids),
        "top_tags": dict(tag_hist.most_common(60)),
    }
    (OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    (OUT / "messages.json").write_text(json.dumps(messages, ensure_ascii=False, indent=1),
                                       encoding="utf-8")

    print(f"解析出对白: {len(messages)} 条  字符: {stats['chars']}  "
          f"msg_id 种类: {len(msg_ids)}")
    named = sum(1 for m in messages if m["speaker"])
    print(f"  有说话人的: {named}  带指令的: {sum(1 for m in messages if m['cmds'])}")
    print(f"输出: {OUT.relative_to(ROOT)}/  (scenario_full.txt / stats.json / messages.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
