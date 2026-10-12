"""core/story 的测试 (B: 事件 flag + 第2-3章链路)."""

from __future__ import annotations

import pytest

from core import story

pytestmark = pytest.mark.skipif(
    not story.main_story(),
    reason="assets/script/messages.json 未生成 (先跑 tools.extract_script)")


def test_main_story_loaded():
    assert len(story.main_story()) > 2000
    # 每条都带全局下标 (章节锚点用它)
    assert all("_idx" in m for m in story.main_story()[:50])


@pytest.mark.parametrize("kw,want", [
    ("土製炸彈", 131),        # 道具店: "連個礦山都沒有的村莊…"
    ("得到四個", 140),        # 得到四个土制炸弹
    ("請他喝酒", 179),        # 嗜酒老人 300G
    ("*蒙面人*加入", 2944),
    ("禁箍之笛", 3098),
])
def test_anchors_match_walkthrough(kw, want):
    """官方攻略节点在剧本流里的位置 (攻略: 买炸弹 / 300G请酒 / 蒙面人 / 禁箍之笛)."""
    assert story.story_index(kw) == want


def test_every_beat_has_dialogue():
    for b in story.BEATS:
        assert b.messages(), f"{b.id} 没有对白 (区间 {b.start}..{b.end} 可能不对)"


def test_beats_are_markup_free():
    for b in story.BEATS:
        for m in b.messages():
            assert "<" not in m["text"], f"{b.id}: 剧本标记没剥干净: {m['text'][:40]}"


def test_progress_gated_by_flags():
    st = story.StoryState()
    first = st.current()
    assert first is not None and first.id == story.BEATS[0].id
    st.complete(first)
    assert first.sets in st.flags
    # 还没满足 requires 的节点不会成为 current
    for b in story.BEATS:
        if b.id not in st.done and not all(f in st.flags for f in b.requires):
            assert st.current() is not b


def test_cost_blocks_progress():
    """攻略里的 300G 请酒: 钱不够就不能推进."""
    class S:
        money = 0
    st = story.StoryState()
    drunk = next(b for b in story.BEATS if b.cost == 300)
    poor = S()
    poor.money = 10
    assert st.complete(drunk, poor) is False
    assert drunk.sets not in st.flags
    rich = S()
    rich.money = 1000
    assert st.complete(drunk, rich) is True
    assert drunk.sets in st.flags
    assert rich.money == 700


def test_full_chain_walks_to_the_end():
    st = story.StoryState()
    for _ in range(len(story.BEATS)):
        b = st.current()
        if b is None:
            break
        assert st.complete(b) is True
    assert st.remaining() == 0
    assert "WUKONG_JOINED" in st.flags
    assert st.is_complete()
    assert "通关" in st.progress_text()


def test_story_joins_party_into_save():
    """剧情 beat 完成时把角色写入存档 (复刻入队: 蒙面人/悟空)."""
    from core.save_manager import new_game_save
    from core import party as party_mod
    sv = new_game_save()
    st = story.StoryState(save=sv)
    assert st.party == ["美娜"]
    # 直接完成两个入队节点
    masked = next(b for b in story.BEATS if b.id == "c3_masked")
    wukong = next(b for b in story.BEATS if b.id == "c3_wukong")
    st.complete(masked, sv)
    st.complete(wukong, sv)
    assert "蒙面人" in st.party and "孙悟空" in st.party
    # 存档槽位已激活
    assert sv.characters[party_mod.NAME_TO_SLOT["蒙面人"]].MaxHP > 0
    assert sv.characters[party_mod.NAME_TO_SLOT["孙悟空"]].MaxHP > 0


def test_beat_for_location_drives_chain():
    """走到正确地图会自动触发对应节点 (B: 可走的剧情链)."""
    st = story.StoryState()
    # 序章 + 第1章小森林 都是"无地点约束"的开篇节点 (由 current() 串接, 非按地点)
    assert st.current().id == "intro"
    st.complete(st.current())
    assert st.current().id == "c1_forest"
    st.complete(st.current())
    # 进五指村 → 触发抵达 (地点节点, 靠对话/trigger 触发)
    assert st.beat_for_location("TFI0___P").id == "c2_arrive"
    st.complete(st.beat_for_location("TFI0___P"))
    # 再进五指村 → 打听姓孙的 (flags 门控)
    assert st.beat_for_location("TFI0___P").id == "c2_ask"
    # 雅士蘭不触发五指村节点
    assert st.beat_for_location("TAS0___P") is None
    st.complete(st.beat_for_location("TFI0___P"))   # c2_ask
    st.complete(st.beat_for_location("TFI0___P"))   # c2_bomb
    # 五指村 → 嗜酒老人 (需 ASKED, 同在第2章五指村线; 剧本 P[179-202] 属五指村)
    assert st.beat_for_location("TFI0___P").id == "c2_drunk"
    # 五指山 → 蒙面人 (需 LEFT_VILLAGE, 还没到 → None)
    assert st.beat_for_location("TOH0_00P") is None
    # 走完第2章 (嗜酒老人 300G 需钱; 用带钱的假存档)
    class S:
        money = 1000
    st.complete(st.beat_for_location("TFI0___P"), S())   # c2_drunk (300G)
    st.complete(st.beat_for_location("TFI0___P"))        # c2_learn
    assert st.beat_for_location("TOH0_00P").id == "c3_masked"
    st.complete(st.beat_for_location("TOH0_00P"))        # c3_masked
    assert st.beat_for_location("TOH0_00P").id == "c3_wukong"
    st.complete(st.beat_for_location("TOH0_00P"))        # c3_wukong
    # 第2-3章主线已走完: 五行山下一个可触发节点是无名指山的 c3_sprites (同为 TOH0 区域)
    nxt = st.beat_for_location("TOH0_00P")
    assert nxt is not None and nxt.id == "c3_sprites"
    assert "WUKONG_JOINED" in st.flags
    # 后续章节 (序章之后的完整链) 尚余, 主线未通关
    assert not st.is_complete()
    assert st.remaining() == len(story.BEATS) - len(st.done)


def test_director_full_campaign_reaches_ending():
    """Director 把完整章节链推进到结局 (序章→收悟空→各章→决战玉皇→结局)."""
    d = story.Director()
    assert not d.is_complete()
    for _ in range(len(story.BEATS) + 1):
        b = d.current()
        if b is None:
            break
        # complete() = 前置结算 + 标记完成/入队 (剧情战斗节点此处模拟胜利后结算)
        assert d.apply_presave(b) is True
        d.apply_postbattle(b)
    assert d.is_complete()
    assert d.ending_text()
    assert d.state.ending_beat() is not None


def test_director_plan_battle_beat():
    d = story.Director()
    masked = next(b for b in story.BEATS if b.id == "c3_masked")
    plan = d.plan(masked)
    assert plan["battle"] is not None
    assert plan["messages"]  # 战斗前也有对白
    # 结局节点: ending 标志
    ending = next(b for b in story.BEATS if b.ending)
    assert d.plan(ending)["ending"] is True


def test_story_battle_win_marks_done_and_recruits():
    """模拟剧情战斗胜利: 胜利后才标记完成 + 入队; 失败则保留节点可重试."""
    from core.save_manager import new_game_save
    sv = new_game_save()
    d = story.Director(save=sv)
    masked = next(b for b in story.BEATS if b.id == "c3_masked")
    # 走到可推进 (需 LEFT_VILLAGE)
    d.state.flags.add("LEFT_VILLAGE")
    assert d.ready(masked)
    # 前置结算 (扣费 + 置 flag 之外, 这里 mask 无 cost)
    assert d.apply_presave(masked) is True
    # 战斗失败: 不结算
    # (无 hook 调用 apply_postbattle)
    assert masked.id not in d.state.done
    # 胜利: 结算
    d.apply_postbattle(masked, sv)
    assert masked.id in d.state.done
    assert "蒙面人" in d.party
    assert sv.characters[
        __import__("core.party", fromlist=["NAME_TO_SLOT"]).NAME_TO_SLOT["蒙面人"]
    ].MaxHP > 0

