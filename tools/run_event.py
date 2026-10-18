"""干跑事件脚本 (不渲染): 打印每帧的演出回调, 用来核对解释器和找没实现的 op.

跑法: cd rewrite && venv/bin/python -m tools.run_event [起始事件=0] [-q 只打统计] [-n 最多事件数]
"""
from __future__ import annotations

import sys
from collections import Counter

from core.dialog_engine import DialogTask, code_str
from core.event_script import Cmd, EventHost, EventRunner, ScriptBundle


class TraceHost(EventHost):
    def __init__(self, quiet: bool) -> None:
        super().__init__()
        self.quiet = quiet
        self.frame = 0
        self.maps: list[int] = []
        self.speaks = 0
        self.unk: Counter = Counter()

    def log(self, msg: str) -> None:
        if not self.quiet:
            print(f"{self.frame:6d} {msg}")

    def switch_map(self, map_id: int, reload: bool = False) -> None:
        self.maps.append(map_id)
        super().switch_map(map_id, reload)

    def speak(self, dlg: DialogTask) -> None:
        self.speaks += 1
        super().speak(dlg)

    def dialog_event(self, dlg: DialogTask, what: str) -> None:
        if what in ("page", "close", "end") and dlg.pages and dlg.pages[-1].lines:
            self.log(f"[ev]   「{code_str(dlg.code)}」 {'|'.join(dlg.pages[-1].lines)}")
        if what == "page" and dlg.pages and dlg.pages[-1].lines:
            pass

    def unknown(self, cmd: Cmd) -> None:
        self.unk[(cmd.op, cmd.sub)] += 1
        super().unknown(cmd)


def main(argv: list[str]) -> int:
    quiet = "-q" in argv
    args = [a for a in argv if not a.startswith("-")]
    start = int(args[0]) if args else 0
    limit = int(argv[argv.index("-n") + 1]) if "-n" in argv else 20
    maxf = int(argv[argv.index("-f") + 1]) if "-f" in argv else 300000
    b = ScriptBundle.load()
    if b is None:
        print("缺 assets/script/events.json (先跑 tools.extract_event_scripts)")
        return 2
    host = TraceHost(quiet)
    r = EventRunner(b, host)
    r.start(start)
    last = None
    while True:
        if r.main is not last:
            last = r.main
            print(f"#### ev{last.event_id} arg={last.locals.get(0x44)} @ frame {r.frames}")
        host.frame = r.frames
        if r.frames % 40 == 0:
            r.press_key()
        if r.tick() or len(r.history) > limit or r.frames > maxf:
            break
    print(f"\nchain {r.history}, {r.frames} frames, maps {host.maps}, {host.speaks} speaks, "
          f"unknown ops {dict(host.unk)}")
    if "-d" in argv:
        dump_state(r)
    return 0


def dump_state(r: EventRunner) -> None:
    """卡住时看: 主任务/子任务停在哪条, 气泡在等什么, 消息环里有什么."""
    m = r.main
    if m is not None:
        print("main pc", m.pc, m.cur() if m.pc < len(m.cmds) else None, "wait", m.wait,
              "cc/d0/d8/dc", [hex(m.local(k)) for k in (0xCC, 0xD0, 0xD8, 0xDC)])
    for hd, vm in r.scheduler.tasks.items():
        print("task", hex(hd), vm.name, "pc", vm.pc, vm.cur() if vm.pc < len(vm.cmds) else None,
              "fc", vm.fc_default, "wait", vm.wait,
              {hex(k): v for k, v in vm.locals.items() if k in (0xF4, 0x44, 0xE8, 0xEC, 0xCC, 0xD0, 0xDC)})
    for hd, d in r.scheduler.dialogs.items():
        print("dlg", hex(hd), code_str(d.code), d.box_state, d.wait_kind, d.wait_sub and code_str(d.wait_sub),
              d.pos, len(d.toks), d.text_so_far()[:60])
    print("mq", [(code_str(e[0]), code_str(e[1]) if e[1] != 0xFFFFFFFF else -1, hex(e[2])) for e in r.scheduler.mq.entries])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
