"""从 exe 的「事件脚本」提每个剧情事件的场景真值 → assets/script/event_scenes.json.

逆向链 (mygame 贡献者, IDA): 位置触发 sub_45A0DC → sub_45901C(ev) → 事件表 off_73DF8C[ev]
  → 事件脚本解释器 sub_467CBC, 指令格式 `[main u8][sub u8][len u16][args]`, 分派表 funcs_467D7B.
用到的指令:
  0xE0 切换地图 (arg = 地图 id)
  0x42 角色坐标  sub_49932A(obj, z, x, y)
  0x4A 角色控制  sub 0 隐藏 / 1 显示 / 2 显示+设帧 / 9 设帧 / 0x14 显示
  0x4F 对白 (arg = 文本 ptr + 立绘代号 4B 反转)
obj 指针是运行时 key, 同一事件内用它把 坐标 / 代号 / 帧 / 显隐 关联到一个角色.

产出: [{event, map, cast: [{code, x, y, z, frames, visible}]}]
跑法: cd rewrite && venv/bin/python -m tools.extract_event_scenes
"""
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = Path(os.environ.get("FLYINGSB_ORIGIN", ROOT.parent / "origin" / "flyingsb"))
EXE = Path(os.environ.get("FLYINGSB_EXE", ORIGIN / "FlyingSB.exe"))
OUT = ROOT / "assets" / "script" / "event_scenes.json"
IMAGE_BASE = 0x400000
EVENT_TABLE_VA = 0x73DF8C
MAX_EVENTS = 200


def extract(exe: Path = EXE) -> list[dict]:
    data = exe.read_bytes()
    off = lambda va: va - IMAGE_BASE
    evs = []
    for i in range(MAX_EVENTS):
        p = struct.unpack_from("<I", data, off(EVENT_TABLE_VA) + i * 4)[0]
        if p == 0:
            break
        evs.append(p)
    out = []
    for idx, va in enumerate(evs):
        end = evs[idx + 1] if idx + 1 < len(evs) else va + 0x4000
        p, e = off(va), off(end)
        mapid = None
        code: dict[int, str] = {}
        pos: dict[int, tuple] = {}
        frames: dict[int, list] = {}
        vis: dict[int, bool] = {}
        while p < e - 3:
            m, sub = data[p], data[p + 1]
            ln = struct.unpack_from("<H", data, p + 2)[0]
            if ln < 4 or p + ln > e:
                break
            args = data[p + 4:p + ln]
            if m == 0xE0 and ln >= 9:
                mapid = struct.unpack_from("<I", args, 1)[0]
            elif m == 0x4F and ln >= 16:
                k = struct.unpack_from("<I", args, 1)[0] & 0xFFFFFF
                code.setdefault(k, args[11:15][::-1].decode("latin1", "replace").strip("\x00"))
            elif m == 0x42 and ln >= 29:
                k = struct.unpack_from("<I", args, 1)[0] & 0xFFFFFF
                z = struct.unpack_from("<I", args, 6)[0]
                x = struct.unpack_from("<I", args, 11)[0]
                y = struct.unpack_from("<I", args, 16)[0]
                pos[k] = (x, y, z)
            elif m == 0x4A and ln >= 9:
                k = struct.unpack_from("<I", args, 1)[0] & 0xFFFFFF
                if sub in (2, 9) and ln >= 14:
                    frames.setdefault(k, []).append(struct.unpack_from("<I", args, 6)[0])
                elif sub == 0:
                    vis[k] = False
                elif sub in (1, 20):
                    vis[k] = True
            p += ln
        cast = []
        for k in set(pos) | set(code):
            c = code.get(k, "")
            if not c:
                continue
            x, y, z = pos.get(k, (None, None, None))
            if x is None or x == 0xFFFFFFFF:
                continue
            cast.append({"code": c, "x": x, "y": y, "z": z,
                         "frames": frames.get(k, []), "visible": vis.get(k, True)})
        cast.sort(key=lambda c: (c["code"], c["x"], c["y"]))
        if cast or mapid is not None:
            out.append({"event": idx, "map": mapid, "cast": cast})
    return out


def main() -> int:
    out = extract()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"事件 {len(out)} 个 → {OUT}")
    for e in out[:8]:
        print(f"  ev {e['event']:3d} map {e['map']}  {[(c['code'], c['x'], c['y'], c['z']) for c in e['cast']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
