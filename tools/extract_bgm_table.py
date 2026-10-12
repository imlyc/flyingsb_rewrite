"""提取原版 BGM 编号表: `<BGMnn>` 的数字 nn → Data/*.WAV 曲名.

背景
----
剧本里有数值型 BGM 指令 `<BGMnn>`(如 <BGM15>/<BGM53>), 已知取值最大 53。
Data/ 下 71 个 BGM 里有 58 个曲名出现在 exe 中; 由 tools/find_bgm_table.py 的
变步长扫描定位到指针表: **文件偏移 0x1464c4, 步长 4, 连续 ~58 项**指针指向曲名。

⚠ 已证伪的路线: `<$NAME>` (无冒号, 如 <$MIRO>/<$SONA>) 是**角色代号不是 BGM**,
前缀匹配 WAV 会得到 'P'→PAO.WAV 这类错误映射, 不可采用。

产物: assets/bgm_table.json  {"0": "曲名.WAV", ...}  (键 = <BGMnn> 里的 nn)

跑法: rewrite/ 下  venv/Scripts/python -m tools.extract_bgm_table
"""
from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = Path(os.environ.get(
    "FLYINGSB_EXE", ROOT.parent / "origin" / "flyingsb" / "FlyingSB.exe"))
OUT = ROOT / "assets" / "bgm_table.json"

TABLE_OFF = 0x1464C4     # 文件偏移 (由 find_bgm_table 扫描定位)
STRIDE = 4
TABLE_LEN = 58           # 定长: 与"Data/ 的 71 个 BGM 里有 58 个曲名出现在 exe"吻合.
                         # 前 0..13 是**角色主题曲**(PUSAN/SON5/MIRO/SAMJANG/JUPAL/
                         # SAOJUNG/MASK/SONATA/PAO/JAHA/AMAZONA/?/OKRANG), 后 14..57
                         # 是**场景曲**(FAIRY/WORLD1/VILL1-4/MOUNTAIN/DUNGEON/FOREST/
                         # DESERT/TEMPLE/...). 个别指针指向的串本工具识别不出 → 记 null.
IMAGE_BASE = 0x400000


def _strings(raw: bytes) -> dict[int, str]:
    vas: dict[int, str] = {}
    for pat in (b".WAV", b".wav"):
        st = 0
        while True:
            i = raw.find(pat, st)
            if i < 0:
                break
            end = i + len(pat)
            s = end
            while s > 0 and 0x20 <= raw[s - 1] < 0x7f and (end - s) < 40:
                s -= 1
            vas[IMAGE_BASE + s] = raw[s:end].decode("latin1")
            st = i + 1
    return vas


def main() -> int:
    if not EXE.exists():
        print(f"[skip] 找不到 exe: {EXE}")
        return 1
    raw = EXE.read_bytes()
    try:
        import pefile
        global IMAGE_BASE
        IMAGE_BASE = pefile.PE(str(EXE), fast_load=True).OPTIONAL_HEADER.ImageBase
    except Exception:
        pass

    vas = _strings(raw)
    out: dict[str, str] = {}
    nulls: list[int] = []
    for k in range(TABLE_LEN):
        off = TABLE_OFF + k * STRIDE
        if off + 4 > len(raw):
            break
        (va,) = struct.unpack_from("<I", raw, off)
        name = vas.get(va)
        if name:
            out[str(k)] = name
        else:
            nulls.append(k)            # 容错: 少数指针指向的串识别不出, 不影响整体
    if nulls:
        print(f"  (未识别出曲名的下标: {nulls})")

    if not out:
        print(f"[fail] 0x{TABLE_OFF:x} 处没解出任何曲名")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"BGM 表: {len(out)} 项 (0x{TABLE_OFF:x}) → {OUT.relative_to(ROOT)}")
    for k, v in list(out.items())[:10]:
        print(f"  BGM{k:<3} {v}")

    # 与剧本里已知 <BGMnn> 取值交叉验证
    known = [2, 8, 15, 16, 20, 28, 44, 48, 53]
    print("\n剧本里出现过的 <BGMnn> 对照:")
    for n in known:
        print(f"  BGM{str(n):<3} -> {out.get(str(n), '(超出表长)')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
