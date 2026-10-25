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
