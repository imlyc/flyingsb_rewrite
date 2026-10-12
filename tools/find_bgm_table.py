"""在 FlyingSB.exe 里自动定位"71 项 .WAV 指针表"(= 原版 BGM 编号表).

动机
----
Data/ 下有 71 个 .WAV (assets/audio 是它的 1:1 拷贝)。剧本里出现过数值型 BGM 指令
`<BGMnn>`, 已知取值 {2,8,15,16,20,28,44,48,53}, 最大值 53 < 71 —— 高度指向
**一张 0..70 编号、71 项的指针表** (形如已破解的 SFX 表 @0x5483a0)。

⚠ 已证伪的路线: 剧本里的 `<$NAME>` (无冒号, 如 <$MIRO>/<$SONA>) **不是** BGM,
而是角色代号 (频次最高的正是角色名); 把它前缀匹配到 WAV 会得出 'P'→PAO.WAV 这类
荒谬结果。真正的地图 BGM 只能靠这张表。

做法
----
1. 扫出 exe 里所有 ".WAV" 短字符串的 VA;
2. 全文件滑窗找"连续 N 个 dword 全部落在 .WAV 字符串 VA 集合内"的位置;
3. 命中即候选表, 打印出来供人工确认。

跑法: rewrite/ 下  venv/Scripts/python -m tools.find_bgm_table
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = Path(os.environ.get(
    "FLYINGSB_EXE", ROOT.parent / "origin" / "flyingsb" / "FlyingSB.exe"))

EXPECT_N = 71          # Data/*.WAV 数量
IMAGE_BASE = 0x400000  # 常见 PE ImageBase (会被 pefile 校正, 见下)


def wav_string_vas(raw: bytes) -> dict[int, str]:
    """{VA: 文件名} —— 所有以 .WAV / .wav 结尾的短字符串."""
    out: dict[int, str] = {}
    for pat in (b".WAV", b".wav"):
        start = 0
        while True:
            i = raw.find(pat, start)
            if i < 0:
                break
            end = i + len(pat)
            # 往前找串首 (可打印字符)
            s = end
            while s > 0 and 0x20 <= raw[s - 1] < 0x7f and (end - s) < 40:
                s -= 1
            name = raw[s:end].decode("latin1")
            out[IMAGE_BASE + s] = name
            start = i + 1
    return out


def main() -> int:
    if not EXE.exists():
        print(f"[skip] 找不到 exe: {EXE}")
        return 1
    raw = EXE.read_bytes()
    print(f"exe: {EXE.name}  {len(raw)} bytes")

    try:
        import pefile
        pe = pefile.PE(str(EXE), fast_load=True)
        global IMAGE_BASE
        IMAGE_BASE = pe.OPTIONAL_HEADER.ImageBase
        print(f"ImageBase = 0x{IMAGE_BASE:x}")
    except Exception as e:
        print(f"(pefile 不可用, 沿用 0x400000: {e})")

    vas = wav_string_vas(raw)
    print(f"找到 .WAV 字符串 {len(vas)} 个")
    sample = sorted(vas.values())[:8]
    print("  样例:", sample)
    vaset = set(vas)

    # 滑窗: 找连续 EXPECT_N 个 dword 全在 vaset 内
    hits: list[tuple[int, int]] = []     # (文件偏移, 连续命中数)
    n = len(raw)
    i = 0
    limit = n - EXPECT_N * 4
    while i < limit:
        ok = 0
        j = i
        while j + 4 <= n:
            (v,) = struct.unpack_from("<I", raw, j)
            if v in vaset:
                ok += 1
                j += 4
                if ok >= EXPECT_N:
                    break
            else:
                break
        if ok >= EXPECT_N:
            hits.append((i, ok))
            i += EXPECT_N * 4        # 跳过本表继续找
            continue
        i += 4 if ok == 0 else 4 * (ok + 1)

    print(f"\n候选 {EXPECT_N} 项指针表: {len(hits)} 处")
    for off, cnt in hits[:10]:
        vas_list = [struct.unpack_from("<I", raw, off + 4 * k)[0]
                    for k in range(min(cnt, EXPECT_N))]
        names = [vas.get(v, "?") for v in vas_list]
        print(f"\n  文件偏移 0x{off:x} (VA 0x{IMAGE_BASE + off:x})  连续 {cnt} 项")
        print(f"    {names}")
    if not hits:
        print("\n未找到: 可能表不是连续 71 项指针, 需要按 loader 函数反查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
