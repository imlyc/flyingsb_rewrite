"""core/prices 的物品价格测试 (C).

数据来自原版物品表 (tools/extract_item_table.py):
  +0x04 = 卖价, +0x08 = 买价,  -1 = 不可交易。
"""

from __future__ import annotations

import pytest

from core import prices

pytestmark = pytest.mark.skipif(
    not prices.has_price_table(),
    reason="assets/items_table.json 未生成 (先跑 tools.extract_item_table)")


@pytest.mark.parametrize("iid,buy,sell", [
    (0, 100, 70),        # 普通帽子
    (1, 200, 140),       # 草帽
    (2, 300, 200),       # 圆锥帽子
    (3, 800, 530),       # 皮帽
    (4, 6500, 4300),     # 魔法头巾
    (299, 50, 30),       # 恢复药
])
def test_known_prices(iid, buy, sell):
    assert prices.buy_price(iid) == buy
    assert prices.sell_price(iid) == sell


@pytest.mark.parametrize("iid", [121, 199, 343])     # 空手 / 如意棒 / 船票
def test_unavailable_items(iid):
    assert prices.buy_price(iid) is None
    assert prices.is_available(iid) is False


def test_non_sellable_still_excluded_from_shops():
    """半透明盔甲: 能卖(90000)但买不到(-1) → 不应上架."""
    assert prices.sell_price(120) == 90000
    assert prices.buy_price(120) is None
    assert prices.is_available(120) is False


def test_sell_price_is_seventy_percent():
    """卖价一般 = 买价的 ~70%; 原版唯一的例外是 314 兴奋剂 (卖1000 > 买700)."""
    checked, over = 0, []
    for iid in range(356):
        b, s = prices.buy_price(iid), prices.sell_price(iid)
        if b is None or s is None:
            continue
        checked += 1
        if s > b:
            over.append((iid, b, s))
    assert checked > 100
    assert over == [(314, 700, 1000)], over


def test_service_prices_are_real_values():
    assert prices.INN_PRICE in prices.INN_PRICES
    assert prices.FERRY_PRICE == 10000
    assert prices.ARENA_TICKET == 10_000_000
