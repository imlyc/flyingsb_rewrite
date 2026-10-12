"""从 FlyingSB.exe 提取"剧情分派总表": 地图角色 ID (FC ID) → 对白 (F 剧情绑定).

逆向出的完整链路 (地址为 VA, ImageBase=0x400000):
    mov eax, [0x7d75b8]        ; 当前 script 索引 (0-based)
    push ... / call 0x45b7d0   ; PlayScript(idx)
        └─ 0x45b7d0: index = param + 1;  if index > 0x29c -> default
            jmp dword ptr [index*4 + 0x467006]     ; 669 项跳转表
                └─ 各分支: push <对白地址>; push npc; call 0x45b173   ; 播放
  · 0x7d75b0 = "Input Field-Character ID" (地图角色 ID), 由引擎钳制到 0..0x29b
  · 0x45b835 = default 分支, 对白是开发期英文串
               "Field Character Speaking. Default String"

产物: assets/script/script_table.json
  [{ "id": 0..668, "code": 分支代码地址, "text": 该 id 对应的对白原文(Big5) }]

跑法: cd rewrite && venv/Scripts/python -m tools.extract_script_table
依赖: capstone, pefile
"""

from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path

import capstone
import pefile

ROOT = Path(__file__).resolve().parent.parent
EXE = Path(os.environ.get(
    "FLYINGSB_EXE", ROOT.parent / "origin" / "flyingsb" / "FlyingSB.exe"))
OUT = ROOT / "assets" / "script" / "script_table.json"

JUMP_TABLE = 0x467006        # 跳转表 VA
MAX_INDEX = 0x29C            # 索引上界 (表项数 = MAX_INDEX + 1 = 669)
PLAY_FUNC = 0x45B173         # 对白播放函数
SCRIPT_LO, SCRIPT_HI = 0x200000, 0x340000    # 剧本文本区 (文件偏移)

try:                          # 原版是 Big5 繁体, 额外给一版简体 (重制版用简体)
    from opencc import OpenCC
    _CC = OpenCC("t2s")
except Exception:            # 没装 opencc 就退回原文
    _CC = None


def _t2s(s: str) -> str:
    return _CC.convert(s) if _CC is not None else s


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not EXE.exists():
        print(f"[skip] 找不到 exe: {EXE}")
        return 1
    raw = EXE.read_bytes()
    pe = pefile.PE(str(EXE), fast_load=True)
    img = pe.OPTIONAL_HEADER.ImageBase
    text = next(s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text")
    code, base_va = text.get_data(), img + text.VirtualAddress

    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    rows: list[tuple[int, str, str]] = []
    off = 0
    while off < len(code):
        got = False
        for ins in md.disasm(code[off:off + 32], base_va + off):
            got = True
            rows.append((ins.address, ins.mnemonic, ins.op_str))
            off += ins.size
            break
        if not got:
            off += 1
    idx_of = {r[0]: i for i, r in enumerate(rows)}

    def text_at(va: int, n: int = 2048) -> str:
        """读入口处到 NUL 的完整原文 (原版一条消息以 NUL 结束, 最长约 1KB)."""
        o = va - img
        if o < 0 or o >= len(raw):
            return ""
        e = raw.find(b"\x00", o)
        if e < 0 or e > o + n:
            e = o + n
        return raw[o:e].decode("big5", "replace")

    n = MAX_INDEX + 1
    targets = struct.unpack_from("<%dI" % n, raw, JUMP_TABLE - img)

    out = []
    for k, t in enumerate(targets):
        i = idx_of.get(t)
        if i is None:
            continue
        # 在分支内找 play 前压栈的对白地址
        msg = None
        for j in range(i, min(len(rows), i + 40)):
            m, o = rows[j][1], rows[j][2]
            if m == "push" and o.startswith("0x6"):
                v = int(o, 16) - img
                if SCRIPT_LO <= v < SCRIPT_HI:
                    msg = int(o, 16)
            elif m == "call" and o == hex(PLAY_FUNC):
                break
        raw_text = text_at(msg) if msg else ""
        out.append({"id": k, "code": t, "text": raw_text,
                    "s": _t2s(raw_text) if raw_text else "",
                    "default": t == 0x45B835})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    real = [e for e in out if e["text"] and not e["default"]]
    print(f"表项 {n} 个, 解析成功 {len(out)} 个 (有对白 {len(real)}, default {n - len(real)})")
    print(f"→ {OUT.relative_to(ROOT)}")
    for e in real[:6]:
        print(f"  id {e['id']:<4d}  {e['text'][:46]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
