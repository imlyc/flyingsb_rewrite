"""core.party / 新游戏开局 + 剧情入队 (复刻原版主角=美娜)."""

from __future__ import annotations

import pytest

from core import party as party_mod
from core.save_manager import new_game_save, load_save
from core.character import PLAYABLE_SLOTS, CHARACTER_NAMES


def test_new_game_starts_with_mina_only():
    sv = new_game_save()
    active = party_mod.active_party(sv)
    assert active == ["美娜"], active
    # 美娜槽有真实 HP
    slot = party_mod.NAME_TO_SLOT["美娜"]
    assert sv.characters[slot].MaxHP > 0
    # 其余可玩槽为空
    for s in PLAYABLE_SLOTS:
        if s == slot:
            continue
        assert sv.characters[s].MaxHP == 0


def test_activate_character_joins_and_persists():
    sv = new_game_save()
    assert party_mod.activate_character(sv, "蒙面人") is True
    assert party_mod.activate_character(sv, "蒙面人") is False  # 已在队
    active = party_mod.active_party(sv)
    assert "蒙面人" in active and active[0] == "美娜"
    assert sv.characters[party_mod.NAME_TO_SLOT["蒙面人"]].MaxHP > 0


def test_loaded_late_save_keeps_all_members():
    # 原版后期存档 (全角色), active_party 应非空且含美娜
    sv = load_save() if False else None  # 仅在环境变量指向时运行
    import os
    path = os.environ.get("FLYINGSB_SAVE")
    if not path:
        pytest.skip("FLYINGSB_SAVE 未设置")
    sv = load_save(path)
    active = party_mod.active_party(sv)
    assert active and "美娜" in active
