"""存档检查 / 对比工具: 打印布局与剧情 flags 位, 或对比两个存档.

用法:
  python -m tools.inspect_save <save.dat>            # 打印布局 + 置位 flag
  python -m tools.inspect_save <saveA> <saveB>       # 对比两个存档的 flags 差异

存档布局 (15232 字节, little-endian):
  0x00  DWORD  标记
  0x04  24B    地点名 (Big5)
  0x20  5×DWORD 游戏状态 (state[2] = 剧情进度)
  0x44  16×0xBC 角色块
  0xBF4 DWORD  金钱
  0xC04-0x1C00 剧情 flags 位图 (1 = 已置位)
  0x1C00+      其它状态表 (待解析)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.save_manager import (  # noqa: E402
    FLAGS_END, FLAGS_START, load_save,
)


def describe(path: Path) -> None:
    save = load_save(path)
    bits = save.set_flag_bits()
    n = (FLAGS_END - FLAGS_START) * 8
    print(f"=== {path.name} ===")
    print(f"  地点: {save.location}   金钱: {save.money}   进度: {save.progress}")
    print(f"  状态 state: {save.state}")
    print(f"  flags 区 0x{FLAGS_START:X}..0x{FLAGS_END:X}: 置位 {len(bits)}/{n}")
    print(f"  置位下标: {bits[:64]}{' ...' if len(bits) > 64 else ''}")
    print(f"  raw: {save.flags.hex()[:120]}{'...' if len(save.flags) * 2 > 120 else ''}")


def diff(pa: Path, pb: Path) -> None:
    a, b = load_save(pa), load_save(pb)
    ba, bb = set(a.set_flag_bits()), set(b.set_flag_bits())
    print(f"=== diff {pa.name} -> {pb.name} ===")
    print(f"  进度: {a.progress} -> {b.progress}")
    print(f"  置位数: {len(ba)} -> {len(bb)}")
    added = sorted(bb - ba)
    removed = sorted(ba - bb)
    print(f"  新增置位 ({len(added)}): {added[:80]}{' ...' if len(added) > 80 else ''}")
    print(f"  取消置位 ({len(removed)}): {removed[:80]}{' ...' if len(removed) > 80 else ''}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    if not args:
        d = Path(os.environ.get("FLYINGSB_ORIGIN", ROOT.parent / "origin" / "flyingsb")) / "Data"
        print(f"用法: python -m tools.inspect_save <save> [<save2>]   (默认目录 {d})")
        return 1
    if len(args) == 1:
        describe(Path(args[0]))
    else:
        describe(Path(args[0]))
        print()
        describe(Path(args[1]))
        print()
        diff(Path(args[0]), Path(args[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
