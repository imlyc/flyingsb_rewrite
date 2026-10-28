"""core.exe_rng = MSVC rand(): 已知序列 + random.Random 兼容接口."""
from core.exe_rng import ExeRng


def test_msvc_rand_sequence():
    r = ExeRng(1)                                   # srand(1): MSVC 前几个 rand() 是公认值
    assert [r.rand() for _ in range(5)] == [41, 18467, 6334, 26500, 19169]


def test_mod_semantics_and_interface():
    r = ExeRng(1)
    assert r.randrange(101) == 41 % 101             # rand() % n
    assert r.randint(5, 9) == 5 + 18467 % 5
    r2 = ExeRng(7)
    s = r2.getstate()
    a = [r2.randrange(0x8000) for _ in range(3)]
    r2.setstate(s)
    assert [r2.rand() for _ in range(3)] == a       # randrange(0x8000) == rand()
    xs = list(range(10))
    ExeRng(3).shuffle(xs)
    assert sorted(xs) == list(range(10))
    assert len(set(ExeRng(4).sample(range(20), 5))) == 5
    assert 0.0 <= ExeRng(5).random() < 1.0
    assert ExeRng(6).choice("abc") in "abc"
