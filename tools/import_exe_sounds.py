"""把外部资料包 (from_others/战斗技能动画音效与数值资料, exe 静态解析) 的音效绑定转成 core/battle/exe_sounds.py.

来源 json (07来源与机器数据/原版音效绑定/):
  skills-audio-static.json         66 技能: audio[] {id, kind(播放/停止/登记命中音/序列播放), tick?, function}
  player-attacks-audio-static.json 16 普攻形态: 同上
  enemy-actions-audio-static.json  248 敌方招式: 同上
  enemy-templates.json             248 招式 raw [id, name_ptr, A, flags, p3, p4, p5, func]
声音 id = 全局音表 (core.sound_table) 下标. 产物是生成的 python 数据模块 (入库, 不依赖资料包).

跑法: cd rewrite && venv/bin/python -m tools.import_exe_sounds [资料包根目录]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PACK = ROOT.parent / "from_others" / "战斗技能动画音效与数值资料"
OUT = ROOT / "core" / "battle" / "exe_sounds.py"
KIND = {"播放": "play", "停止": "stop", "登记命中音": "hit", "序列播放": "seq", "序列登记命中音": "hit", "序列停止": "stop"}


def _events(audio: list[dict]) -> list[tuple]:
    out = []
    for a in audio:
        k = KIND.get(a.get("kind"), a.get("kind"))
        out.append((int(a["id"]), k, a.get("tick"), int(a["instruction"], 16)))
    return out


def main(argv: list[str]) -> int:
    pack = Path(argv[1]) if len(argv) > 1 else DEFAULT_PACK
    src = pack / "07来源与机器数据" / "原版音效绑定"
    skills = json.loads((src / "skills-audio-static.json").read_text(encoding="utf-8"))
    players = json.loads((src / "player-attacks-audio-static.json").read_text(encoding="utf-8"))
    enemies = json.loads((src / "enemy-actions-audio-static.json").read_text(encoding="utf-8"))
    lines = ['"""exe 静态解析的战斗音效绑定 (生成文件, 勿手改; tools/import_exe_sounds.py).',
             "",
             "每项事件 = (sound_id, kind, tick, 调用地址): kind 'play' 直接播 / 'stop' 停 / 'hit' 登记为命中音 (IMPACT 时播) /",
             "'seq' 动画字节码第 tick 个 tick 播 (tick 只是该局部序列内的坐标). 同一技能里按处理链的条件分支可能只播其中一部分.",
             "来源: from_others/战斗技能动画音效与数值资料 (2026-10-14, 逐项带 exe 调用地址). 声音 id 见 core.sound_table.",
             '"""',
             "from __future__ import annotations",
             "",
             "# 技能 id → [(sound_id, kind, tick, addr)]",
             "SKILL_SOUNDS: dict[int, list[tuple]] = {"]
    for s in skills:
        lines.append(f"    {s['id']:#04x}: {_events(s['audio'])!r},  # {s['name']}")
    lines += ["}", "", "# 普攻形态 (exe wrapper 顺序: 0-2 孙悟空无头盔/拳头/双节棒, 3 美娜, 4 三藏, 5 八戒, 6 沙悟净, 7 蒙面人真容,",
              "# 8 蒙面人斗篷, 9 乐神, 10 破无, 11 捕山, 12-15 紫河四形态) → [(sound_id, kind, tick, addr)]",
              "PLAYER_ATTACK_SOUNDS_EXE: dict[int, list[tuple]] = {"]
    for p in players:
        lines.append(f"    {p['index']}: {_events(p['audio'])!r},")
    lines += ["}", "", "# 敌方招式 id (assets/enemy_actions.json 下标, 敌人表 skill0..3) → (名字, [(sound_id, kind, tick, addr)])",
              "ENEMY_MOVE_SOUNDS: dict[int, tuple[str, list[tuple]]] = {"]
    for e in enemies:
        lines.append(f"    {e['index']}: ({e['name']!r}, {_events(e['audio'])!r}),")
    lines += ["}", "", "",
              "def enemy_move_attack_sounds(move_id: int) -> tuple[int, int]:",
              '    """招式的 (挥击音, 命中音); 没有的填 -1. 挥击音 = 处理函数里直接 play 的第一个; 命中音 = 登记的 hit."""',
              "    _, ev = ENEMY_MOVE_SOUNDS.get(move_id, ('', []))",
              "    hit = next((sid for sid, k, _t, _a in ev if k == 'hit'), -1)",
              "    draw = next((sid for sid, k, _t, _a in ev if k in ('play', 'seq') and sid != hit), -1)",
              "    return draw, hit", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"→ {OUT}: {len(skills)} skills, {len(players)} player forms, {len(enemies)} enemy moves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
