"""转录 seq ↔ FlyingSB.exe 逐 op 核对 (tools/verify_seqs). 有 exe 才跑.

断言: 能在 exe 里定位到的 seq, exe 有的 sound / signal op 我们都得有 (漏抄就是 bug);
已知的刻意省略列在 ALLOW 里.
"""
import pytest

from tools import verify_seqs as vs

ALLOW_MISSING = {
    "projectile.CDIT1_G0_TABLE",      # 投射物只用帧序列, -1001/-105 信号由 think fn 自己处理
    "raw_attack_seqs.SAM_ATK_B",      # 借用美娜召唤精灵的表当三藏双击; -1001 (精灵模型切换) / -105 不需要
}
ALLOW_NOT_FOUND = {
    "skill_seq._SON_CAST_DAJINGANG", "skill_seq.SKILL_SON_DAJINGANG",   # 旧占位 (真 seq = FLIP_SEQ)
}


@pytest.mark.skipif(not vs.EXE.exists(), reason="缺 FlyingSB.exe")
def test_transcribed_seqs_keep_every_sound_and_signal():
    data = vs.EXE.read_bytes()
    problems = []
    for name, seq in vs.collect():
        base = name.split("[")[0]
        r = vs.compare(name, seq, data, False)
        if r["status"].startswith("NOT") and base not in ALLOW_NOT_FOUND:
            problems.append(f"{name}: 在 exe 里没定位到")
        if r["missing"] and base not in ALLOW_MISSING:
            problems.append(f"{name} @0x{r['addr']:x}: 漏 {r['missing']}")
    assert not problems, "\n".join(problems)
