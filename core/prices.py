"""物品 / 服务价格 (C) —— 全部来自原版真实数据, 不再估值.

物品价格来源: `assets/items_table.json`
  由 `tools/extract_item_table.py` 从 FlyingSB.exe 的物品记录表提取
  (VA 0x6954D4, 步长 76 字节):
    +0x04 = 卖价 (sell)   +0x08 = 买价 (buy)   -1 = 不可交易
  原版商店用 `玩家金钱(0x867e7c) - 已付 >= rec[+0x08]` 判断能否买入,
  所以 +0x08 就是商店售价 (与 core/items.py 的物品名逐项对上, 349/356 完全一致)。

服务价格来源: 原版剧本文本 + 扣钱点 (tools/extract_script_table.py 的产物):
  旅馆/住宿 45 / 80 / 120 / 130 / 140 / 150 / 180 / 300 G
  船票 10000 G    妖怪格斗赛门票 10000000 G
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "assets" / "items_table.json"

UNAVAILABLE = -1

# 原版旅馆/住宿的 8 个真实价格 (剧本原文: "住宿費是 130 G" 等)
INN_PRICES = (45, 80, 120, 130, 140, 150, 180, 300)
INN_PRICE = 130                  # 重制版只做了一家旅馆, 取其中一个真实值
FERRY_PRICE = 10000              # 船票 ("祝你旅途愉快.")
ARENA_TICKET = 10_000_000        # 妖怪格斗赛门票


@lru_cache(maxsize=1)
def _table() -> dict:
    if not TABLE.exists():
        return {}
    return json.loads(TABLE.read_text(encoding="utf-8")).get("items", {})


def buy_price(item_id: int) -> int | None:
    """买入价; None = 非卖品 (原版 -1, 或数据表缺失)."""
    e = _table().get(str(item_id))
    if not e:
        return None
    p = e.get("buy", UNAVAILABLE)
    return p if isinstance(p, int) and p > 0 else None


def sell_price(item_id: int) -> int | None:
    """卖出价 (原版回收价, 一般为买入价的 ~70%); None = 不可卖."""
    e = _table().get(str(item_id))
    if not e:
        return None
    p = e.get("sell", UNAVAILABLE)
    return p if isinstance(p, int) and p > 0 else None


def is_available(item_id: int) -> bool:
    """商店可上架 = 表里有买入价."""
    return buy_price(item_id) is not None


def has_price_table() -> bool:
    return bool(_table())
