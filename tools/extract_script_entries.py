"""从 FlyingSB.exe 反汇编提取"剧本入口表" (F 剧情绑定).

机制 (已逆向确认, 见 _f3 探针):
  · 引擎用 `call 0x45b173(npc_idx, script_ptr, arg)` 播放一段对白;
  · 剧本入口 script_ptr 以 `push imm32` / `mov reg, imm32` 直接写在代码里;
  · 入口处正好是台词行首, 例如 0x214b54 -> "<msg_id=NPC>我...你說我說過...";
  · 入口的选择由一个全局变量 (如 0x867e7c) 与常量比较 (if-else 链) 驱动.

本工具扫描 .text 中所有指向剧本区的立即数, 解出入口处的台词, 输出:
  assets/script/entries.json = [{code: 引用的代码地址, script: 剧本偏移, text: 解出的台词}]

依赖: capstone (pip install capstone), 仅分析用.
跑法: cd rewrite && venv/Scripts/python -m tools.extract_script_entries
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import capstone
import pefile

ROOT = Path(__file__).resolve().parent.parent
EXE = Path(__import__("os").environ.get(
    "FLYINGSB_EXE",
    ROOT.parent / "origin" / "flyingsb" / "FlyingSB.exe"))
OUT = ROOT / "assets" / "script" / "entries.json"

TEXT_LO, TEXT_HI = 0x208000, 0x340000     # 剧本区 (文件偏移)


def decode_text(raw: bytes, off: int, n: int = 60) -> str:
    if not (0 <= off < len(raw)):
        return ""
    end = raw.find(b"\x00", off)
    if end < 0 or end > off + n:
        end = off + n
    return raw[off:end].decode("big5", "replace")


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
    md.detail = True
    lo, hi = TEXT_LO + img, TEXT_HI + img

    found: dict[int, set[int]] = {}       # script_off -> {code_addr}
    off, n_ins = 0, 0
    while off < len(code):
        got = False
        for ins in md.disasm(code[off:off + 32], base_va + off):
            got = True
            n_ins += 1
            for op in ins.operands:
                v = op.imm if op.type == capstone.x86.X86_OP_IMM else (
                    op.mem.disp if op.type == capstone.x86.X86_OP_MEM else 0)
                if lo <= v < hi:
                    found.setdefault(v - img, set()).add(ins.address)
            off += ins.size
            break
        if not got:
            off += 1

    entries = [{"script": t, "code": sorted(cs), "text": decode_text(raw, t)}
               for t, cs in sorted(found.items())]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"反汇编 {n_ins} 条指令")
    print(f"剧本入口点: {len(entries)} 个 → {OUT.relative_to(ROOT)}")
    for e in entries[:6]:
        print(f"  0x{e['script']:06x} (code {len(e['code'])} 处)  {e['text'][:40]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
