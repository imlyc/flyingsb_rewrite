"""出场名单: 原版存档 0xBF8 人数 + 0xBFC 槽位 (core.save_manager.party_slots), 野外战斗按它出场 (battle_launch)."""
import struct
from types import SimpleNamespace

from core.save_manager import PARTY_COUNT_OFFSET, PARTY_LIST_OFFSET, SAVE_SIZE, party_slots


def _ch(max_hp=100):
    return SimpleNamespace(MaxHP=max_hp)


def _save(count, slots, chars=(1, 3, 5, 10, 12, 4)):
    raw = bytearray(SAVE_SIZE)
    struct.pack_into("<i", raw, PARTY_COUNT_OFFSET, count)
    for i, s in enumerate(slots):
        struct.pack_into("<i", raw, PARTY_LIST_OFFSET + 4 * i, s)
    return SimpleNamespace(raw=bytes(raw), characters={c: _ch() for c in chars})


def test_party_slots_from_raw():
    assert party_slots(_save(5, [1, 3, 5, 10, 12])) == [1, 3, 5, 10, 12]
    assert party_slots(_save(2, [12, 4])) == [12, 4]                 # 顺序照名单, 不按槽位排
    assert party_slots(_save(0, [])) == []                           # JSON 存档 raw 全 0
    assert party_slots(_save(2, [12, 9])) == []                      # 名单里有不存在的角色 → 不可信


def test_battle_party_prefers_save_list_then_story():
    from scenes.world_map.battle_launch import battle_party_slots
    sc = SimpleNamespace(save=_save(3, [12, 1, 5]), story=SimpleNamespace(party=['美娜']))
    assert battle_party_slots(sc) == [12, 1, 5]
    sc = SimpleNamespace(save=_save(0, []), story=SimpleNamespace(party=['美娜', '孙悟空']))
    assert battle_party_slots(sc) == [3, 1]


def _event_block(vals, key=0x1234ABCD, n12=2, n4=3):
    """照 exe FUN_004cac73 构造加密块: 头 0x4c + 变量 + 12B 表 + 4B 表, 全体按 dword 异或 key, dword[5] = key ^ 0x66666666."""
    var_b, t12, t4 = 4 * len(vals), 12 * n12, 4 * n4
    total = var_b + 0x4c + t12 + t4
    words = [total, 0x34, var_b, t12, t4, 0] + [0] * 13 + [v & 0xFFFFFFFF for v in vals] + [7] * ((t12 + t4) // 4)
    words = [w ^ key for w in words]
    words[5] = key ^ 0x66666666
    return total, struct.pack(f"<{len(words)}I", *words)


def test_decode_event_block_roundtrip():
    from core.save_manager import EVENT_BLOCK_OFFSET, EVENT_VARS_VA, decode_event_block
    raw = bytearray(SAVE_SIZE)
    total, blob = _event_block([0, 5, -1, 418])
    struct.pack_into("<i", raw, EVENT_BLOCK_OFFSET, total)
    raw[EVENT_BLOCK_OFFSET + 4:EVENT_BLOCK_OFFSET + 4 + len(blob)] = blob
    assert decode_event_block(bytes(raw)) == (0, 5, -1, 418)
    assert decode_event_block(bytes(SAVE_SIZE)) == ()               # 空档
    from core.save_manager import SaveData
    s = SaveData(location="", flag=0, state=(), money=0, characters={}, raw=bytes(raw),
                 event_vars=decode_event_block(bytes(raw)))
    assert s.event_var(EVENT_VARS_VA + 12) == 418 and s.nonzero_event_vars() == {EVENT_VARS_VA + 4: 5,
                                                                                  EVENT_VARS_VA + 8: -1,
                                                                                  EVENT_VARS_VA + 12: 418}


def test_item_counts_and_layout_no_overlap():
    from core.save_manager import ITEM_COUNTS_OFFSET, PARTY_LIST_LEN, item_counts
    raw = bytearray(SAVE_SIZE)
    struct.pack_into("<i", raw, ITEM_COUNTS_OFFSET + 4 * 299, 3)      # 恢复药 ×3
    assert item_counts(bytes(raw)) == {299: 3}
    assert PARTY_LIST_OFFSET + 4 * PARTY_LIST_LEN <= ITEM_COUNTS_OFFSET   # 名单区不再和别的区重叠
