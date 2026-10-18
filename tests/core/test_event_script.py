"""原版事件脚本解释器 (core.event_script) + 气泡引擎 (core.dialog_engine) 的干跑测试.

数据: assets/script/events.json (tools.extract_event_scripts 从 FlyingSB.exe 提取). 缺则跳过.
"""
from pathlib import Path

import pytest

from core import event_script as es
from core.dialog_engine import DialogHost, DialogTask, MessageQueue, code_of, code_str, tokenize

ROOT = Path(__file__).resolve().parents[2]
needs_bundle = pytest.mark.skipif(not (ROOT / "assets" / "script" / "events.json").exists(),
                                  reason="缺 assets/script/events.json (先跑 tools.extract_event_scripts)")


# ---------------------------------------------------------------- 气泡引擎 (不需要数据)
def test_code_roundtrip():
    assert code_of("MIRO") == 0x4D49524F and code_str(0x4D49524F) == "MIRO"
    assert code_str(code_of("010")) == "010"


def test_tokenize_prologue_tags():
    toks = tokenize("<possub_L>/<WIDTHXL>@@不知*死猴子*! <D4>|就讓.;<$010>/<$SON5:3035><->")
    kinds = [t.kind for t in toks]
    assert kinds[:4] == ["possub", "wait_msg", "width", "box"]
    assert ("post", code_of("010"), 0) in [(t.kind, t.a, t.b) for t in toks]
    assert ("post", code_of("SON5"), 3035 | 0x8000) in [(t.kind, t.a, t.b) for t in toks]
    assert kinds.count("hl") == 2 and "page" in kinds and "nl" in kinds and "close" in kinds
    d = next(t for t in toks if t.kind == "delay")
    assert d.a == 400                                   # <D4> = 4×100ms
    assert kinds[-1] == "end"


class _Host(DialogHost):
    def __init__(self):
        self.events = []

    def dialog_event(self, dlg, what):
        self.events.append(what)


def _run(dlg: DialogTask, ms: int, step: int = 30) -> None:
    for _ in range(ms // step):
        dlg.tick(step)


def test_dialog_waits_for_message_then_types_and_signals():
    """'/' 等自己代号的消息; 收到后打字; <$010> 发出标签; ';' 自动翻页 (事件模式)."""
    mq = MessageQueue()
    host = _Host()
    d = DialogTask("<possub_U>/@@哼! <D2>別太囂張了;<$010>/@@呵呵", 1, code_of("SON5"), mq, host,
                   auto_delay_ms=300, speed_ms=10)
    _run(d, 600)
    assert not d.visible() and d.wait_kind == "msg"      # 卡在 '/'
    mq.post(code_of("SON5"), code_of("X"), 0)           # 主脚本 71.05 ['X', SON5]
    _run(d, 3000)
    assert d.pages[0].lines[0].startswith("哼! 別太囂張了")
    assert mq.find(code_of("010")) >= 0                 # <$010> 已发出, 又停在第二个 '/'
    assert d.wait_kind == "msg"
    mq.take(mq.find(code_of("010")))
    mq.post(code_of("SON5"), 0, 0)
    _run(d, 2000)
    assert "呵呵" in " ".join(d.transcript) and d.finished and "end" in host.events


def test_dialog_partner_handshake():
    """<$=DIT> 设对手; <$> 发给对手; 对手文本里的 '/' 收到后继续."""
    mq = MessageQueue()
    host = _Host()
    miro = DialogTask("<$=DIT>@@你來有什麼事?<$><->/@@哼<$>", 3, code_of("MIRO"), mq, host, auto_delay_ms=100, speed_ms=5)
    dit = DialogTask("<$=MIRO>/@@公主!<$>/@@好", 8, code_of("DIT"), mq, host, auto_delay_ms=100, speed_ms=5)
    for _ in range(300):
        miro.tick(30)
        dit.tick(30)
    assert dit.finished and miro.finished
    assert "公主!" in " ".join(dit.transcript) and "哼" in " ".join(miro.transcript)


def test_flag_message_closes_waiting_bubble():
    mq = MessageQueue()
    d = DialogTask("@@哈哈/@@後面", 1, code_of("SONA"), mq, _Host(), speed_ms=5)
    _run(d, 1000)
    assert d.visible() and d.wait_kind == "msg"
    mq.post(code_of("SONA"), code_of("X"), 1)           # 71.04 [X, SONA, 1] = 关窗
    _run(d, 500)
    assert not d.visible() and d.wait_kind == "msg"       # 关了但还在等


# ---------------------------------------------------------------- 解释器 (需要 events.json)
class _Trace(es.EventHost):
    def __init__(self):
        super().__init__()
        self.maps = []
        self.speaks = []
        self.unknown = []

    def log(self, msg):
        pass

    def switch_map(self, map_id, reload=False):
        self.maps.append(map_id)

    def speak(self, dlg):
        self.speaks.append((code_str(dlg.code), dlg.fc))

    def unknown(self, cmd):
        self.unknown.append((cmd.op, cmd.sub))


def _chain(start: int, limit: int, max_frames: int = 60000):
    b = es.ScriptBundle.load()
    host = _Trace()
    r = es.EventRunner(b, host)
    r.start(start)
    while r.frames < max_frames:
        if r.frames % 40 == 0:
            r.press_key()
        if r.tick() or len(r.history) > limit:
            break
    return r, host


@needs_bundle
def test_bundle_has_prologue_events_and_builtin_scripts():
    b = es.ScriptBundle.load()
    assert all(i in b.events for i in range(10))
    for va in (es.TALK_SCRIPT_VA, es.TURN_SCRIPT_VA, es.WALK_SCRIPT_VA, es.WALKER_SCRIPT_VA):
        assert va in b.scripts and any(c.addr == va for c in b.scripts[va])
    ev0 = b.scripts[b.events[0]]
    assert ev0[0].addr == b.events[0] and (ev0[0].op, ev0[0].sub) == (0x92, 0)
    assert any(c.op == 0x4F and c.sub == 9 and c.text and "死猴子" in c.text for c in ev0)


@needs_bundle
def test_prologue_chain_runs_to_event_9():
    r, host = _chain(0, 12)
    assert r.history == [0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9], r.history
    assert host.maps == [469, 470, 471, 472, 473, 474, 476]
    assert not host.unknown, host.unknown
    assert 20 <= len(host.speaks) <= 30
    assert r.frames < 60000


@needs_bundle
def test_event2_reruns_second_phase_via_92_02():
    r, host = _chain(2, 2)
    assert r.history[:2] == [2, 2]                      # 92.02: 事件标志 +1 → 重跑自己, 开头 switch 选第二阶段
    assert host.maps == [470] and len(host.speaks) >= 4  # 第二阶段 e1.02 同图不重载; 两阶段都有人说话


@needs_bundle
def test_turn_script_rotates_actor():
    """44.00 起转向脚本: 逐 45° 把 obj+0x110 转到目标向, 走完自己结束."""
    b = es.ScriptBundle.load()

    class H(_Trace):
        def __init__(self):
            super().__init__()
            self.dir = 0
            self.target = 0
            self.dirs = []

        def fc_get(self, fc, field):
            return self.dir if field == 0x110 else (self.target if field == 0x114 else 0)

        def fc_set(self, fc, field, v):
            if field == 0x114:
                self.target = v

        def fc_dir(self, fc, d):
            self.dir = d
            self.dirs.append(d)

    host = H()
    r = es.EventRunner(b, host)
    sch = r.scheduler
    vm = es.EventVM(b, [], host, {}, scripts=b.scripts, scheduler=sch)
    hd = vm._turn(1, 2, 0)
    for _ in range(200):
        sch.tick()
        if not sch.alive(hd):
            break
    assert not sch.alive(hd) and host.dir == 2 and host.dirs
