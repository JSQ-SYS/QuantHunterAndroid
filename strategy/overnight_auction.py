#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股沪深主板：尾盘集合竞价买入 / 次日开盘集合竞价卖出
信号模式，不连接券商，不会自动下单。

数据采用标准化 CSV。请先确认数据供应商提供的字段确实代表对应时点，
尤其是 14:56 盘中快照、15:00 收盘集合竞价成交价、次日 9:25 开盘集合竞价成交价。
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class Config:
    min_score: float = 75.0
    max_positions: int = 3
    max_position_pct: float = 0.20
    risk_budget_pct: float = 0.005       # 单笔账户风险预算 0.5%
    stop_loss_pct: float = 0.03          # 仅用于仓位预算；隔夜跳空可能超出
    min_amount_yuan: float = 100_000_000
    min_turnover_pct: float = 3.0
    max_turnover_pct: float = 15.0
    min_day_return_pct: float = 1.0
    max_day_return_pct: float = 6.0
    min_close_position: float = 0.80
    min_tail_return_pct: float = 0.30
    min_tail_volume_ratio: float = 0.08
    max_auction_gap_pct: float = 2.0    # 收盘竞价价相对 14:56 参考价的最大跳升
    max_auction_drop_pct: float = 1.0
    min_buy_matched_amount: float = 5_000_000
    min_sell_matched_amount: float = 5_000_000
    commission_rate: float = 0.0003    # 每边佣金；按券商实际费率修改
    stamp_duty_rate: float = 0.0005    # 卖出印花税，按当前适用规则核实
    transfer_fee_rate: float = 0.00001 # 估算参数，按交易所/券商规则核实
    slippage_bps: float = 5.0           # 每边滑点基点
    initial_cash: float = 100_000.0
    lot_size: int = 100
    max_daily_loss_pct: float = 0.02
    max_consecutive_losses: int = 3


REQUIRED = [
    "date", "symbol", "name", "pre_close", "price_1430", "price_1456",
    "high_1456", "low_1456", "volume_to_1456", "volume_1430_1456",
    "amount_to_1456", "turnover_rate_to_1456", "ma5_prev",
    "auction_buy_price", "auction_buy_matched_amount",
    "next_date", "next_auction_price", "next_auction_matched_amount"
]


def is_main_board(symbol: str) -> bool:
    s = str(symbol).split(".")[0].zfill(6)
    return s.startswith(("600", "601", "603", "605", "000", "001", "002", "003"))


def safe_num(x, default=np.nan):
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"symbol": str})
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError("CSV 缺少必要字段：" + ", ".join(missing))
    for c in REQUIRED:
        if c not in ("date", "symbol", "name", "next_date"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["next_date"] = pd.to_datetime(df["next_date"], errors="coerce")
    df["symbol"] = df["symbol"].astype(str).str.strip()
    return df


def score_row(r: pd.Series, cfg: Config) -> tuple[float, list[str]]:
    """只用 14:56 前可获得的数据评分；auction_buy_price 仅用于事后成交验证。"""
    reasons = []
    vals = {}

    day_ret = (r.price_1456 / r.pre_close - 1) * 100 if r.pre_close > 0 else np.nan
    tail_ret = (r.price_1456 / r.price_1430 - 1) * 100 if r.price_1430 > 0 else np.nan
    rng = r.high_1456 - r.low_1456
    close_pos = (r.price_1456 - r.low_1456) / rng if rng > 0 else 0.5
    tail_vol_ratio = r.volume_1430_1456 / r.volume_to_1456 if r.volume_to_1456 > 0 else 0
    above_ma = r.price_1456 > r.ma5_prev

    vals["day_ret"] = day_ret
    vals["tail_ret"] = tail_ret
    vals["close_pos"] = close_pos
    vals["tail_vol_ratio"] = tail_vol_ratio

    if not is_main_board(r.symbol):
        return 0.0, ["非沪深主板"]
    if "ST" in str(r["name"]).upper() or "退" in str(r["name"]):
        return 0.0, ["ST/退市风险名称过滤"]
    if not (cfg.min_day_return_pct <= day_ret <= cfg.max_day_return_pct):
        return 0.0, ["当日涨幅不符合"]
    if not (cfg.min_turnover_pct <= r.turnover_rate_to_1456 <= cfg.max_turnover_pct):
        return 0.0, ["换手率不符合"]
    if r.amount_to_1456 < cfg.min_amount_yuan:
        return 0.0, ["成交额不足"]
    if tail_ret < cfg.min_tail_return_pct:
        return 0.0, ["尾盘涨幅不足"]
    if close_pos < cfg.min_close_position:
        return 0.0, ["盘中高位收敛不足"]
    if tail_vol_ratio < cfg.min_tail_volume_ratio:
        return 0.0, ["尾盘成交量占比不足"]
    if not above_ma:
        return 0.0, ["低于前一日计算的5日均线"]

    # 分项评分：全部基于 14:56 前快照
    s_tail = min(max((tail_ret / 2.0) * 25, 0), 25)
    s_vol = min(max((tail_vol_ratio / 0.20) * 20, 0), 20)
    s_pos = min(max(((close_pos - 0.60) / 0.40) * 20, 0), 20)
    s_turn = 10 if 4 <= r.turnover_rate_to_1456 <= 10 else 6
    s_money = 15 if r.amount_to_1456 >= 300_000_000 else 10
    s_trend = 10
    score = s_tail + s_vol + s_pos + s_turn + s_money + s_trend
    reasons.append(f"尾盘涨幅{tail_ret:.2f}%")
    reasons.append(f"尾盘量占比{tail_vol_ratio:.1%}")
    reasons.append(f"收盘位置代理值{close_pos:.2f}")
    if above_ma:
        reasons.append("高于前一日MA5")
    return round(score, 2), reasons


def apply_buy_fill_filter(r: pd.Series, cfg: Config) -> tuple[bool, str]:
    px = r.auction_buy_price
    if not np.isfinite(px) or px <= 0:
        return False, "缺少真实收盘竞价成交价"
    gap = (px / r.price_1456 - 1) * 100
    if gap > cfg.max_auction_gap_pct:
        return False, f"收盘竞价跳升过大({gap:.2f}%)"
    if gap < -cfg.max_auction_drop_pct:
        return False, f"收盘竞价明显跳水({gap:.2f}%)"
    if safe_num(r.auction_buy_matched_amount, 0) < cfg.min_buy_matched_amount:
        return False, "收盘竞价成交额/匹配金额不足"
    return True, "通过收盘竞价成交过滤"


def calc_shares(cash: float, price: float, cfg: Config) -> int:
    if price <= 0:
        return 0
    risk_cash = cash * cfg.risk_budget_pct
    by_risk = risk_cash / max(price * cfg.stop_loss_pct, 0.01)
    by_capital = cash * cfg.max_position_pct / price
    shares = min(by_risk, by_capital)
    return max(0, int(shares // cfg.lot_size) * cfg.lot_size)


def fee_buy(notional: float, cfg: Config) -> float:
    return notional * (cfg.commission_rate + cfg.transfer_fee_rate)


def fee_sell(notional: float, cfg: Config) -> float:
    return notional * (cfg.commission_rate + cfg.transfer_fee_rate + cfg.stamp_duty_rate)


def run_backtest(df: pd.DataFrame, cfg: Config, outdir: Path):
    df = df.copy()
    scores, reasons, eligible = [], [], []
    for _, r in df.iterrows():
        sc, why = score_row(r, cfg)
        ok, fill_reason = apply_buy_fill_filter(r, cfg) if sc >= cfg.min_score else (False, "评分不足")
        scores.append(sc)
        reasons.append(";".join(why + [fill_reason]))
        eligible.append(bool(ok and sc >= cfg.min_score))
    df["score"] = scores
    df["reason"] = reasons
    df["eligible"] = eligible
    df = df.sort_values(["date", "score"], ascending=[True, False])

    cash = cfg.initial_cash
    trades = []
    equity = []
    loss_streak = 0
    halted_dates = set()

    for dt, day in df.groupby("date", sort=True):
        day_start_cash = cash
        if loss_streak >= cfg.max_consecutive_losses:
            halted_dates.add(dt)
            equity.append({"date": dt, "equity": cash, "daily_return": 0.0, "halted": True})
            continue

        picks = day[day["eligible"]].head(cfg.max_positions)
        slots = max(1, len(picks))
        day_pnl = 0.0

        for _, r in picks.iterrows():
            buy_px_raw = r.auction_buy_price
            sell_px_raw = r.next_auction_price
            if not np.isfinite(sell_px_raw) or sell_px_raw <= 0:
                trades.append({"date": dt, "symbol": r.symbol, "status": "NO_NEXT_AUCTION_PRICE",
                               "score": r.score, "pnl": np.nan})
                continue
            if safe_num(r.next_auction_matched_amount, 0) < cfg.min_sell_matched_amount:
                trades.append({"date": dt, "symbol": r.symbol, "status": "SELL_LIQUIDITY_WARNING",
                               "score": r.score, "pnl": np.nan})
                continue

            shares = calc_shares(cash, buy_px_raw, cfg)
            if shares < cfg.lot_size:
                continue

            buy_px = buy_px_raw * (1 + cfg.slippage_bps / 10000)
            sell_px = sell_px_raw * (1 - cfg.slippage_bps / 10000)
            buy_value = shares * buy_px
            total_buy = buy_value + fee_buy(buy_value, cfg)
            if total_buy > cash:
                shares = int((cash / (buy_px * (1 + cfg.commission_rate + cfg.transfer_fee_rate))) // cfg.lot_size) * cfg.lot_size
                buy_value = shares * buy_px
                total_buy = buy_value + fee_buy(buy_value, cfg)
            if shares < cfg.lot_size or total_buy > cash:
                continue

            sell_value = shares * sell_px
            total_sell = sell_value - fee_sell(sell_value, cfg)
            pnl = total_sell - total_buy
            ret = pnl / total_buy if total_buy else 0
            cash += pnl
            day_pnl += pnl
            trades.append({
                "date": dt, "next_date": r.next_date, "symbol": r.symbol, "name": r["name"],
                "score": r.score, "shares": shares, "buy_price": buy_px_raw,
                "sell_price": sell_px_raw, "buy_value_with_cost": total_buy,
                "sell_value_after_cost": total_sell, "pnl": pnl, "return_pct": ret * 100,
                "status": "SIMULATED_FILLED", "reason": r.reason
            })
            loss_streak = loss_streak + 1 if pnl < 0 else 0

        daily_ret = (cash - day_start_cash) / day_start_cash if day_start_cash else 0
        equity.append({"date": dt, "equity": cash, "daily_return": daily_ret, "halted": False})

    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity)
    if not equity_df.empty:
        equity_df["peak"] = equity_df["equity"].cummax()
        equity_df["drawdown_pct"] = (equity_df["equity"] / equity_df["peak"] - 1) * 100
    outdir.mkdir(parents=True, exist_ok=True)
    df.to_csv(outdir / "backtest_signals.csv", index=False, encoding="utf-8-sig")
    trades_df.to_csv(outdir / "backtest_trades.csv", index=False, encoding="utf-8-sig")
    equity_df.to_csv(outdir / "equity_curve.csv", index=False, encoding="utf-8-sig")

    filled = trades_df[trades_df.get("status", pd.Series(dtype=str)) == "SIMULATED_FILLED"] if not trades_df.empty else pd.DataFrame()
    if not filled.empty:
        wins = (filled["pnl"] > 0).mean() * 100
        gross_profit = filled.loc[filled.pnl > 0, "pnl"].sum()
        gross_loss = abs(filled.loc[filled.pnl < 0, "pnl"].sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.inf
        total_return = (cash / cfg.initial_cash - 1) * 100
        max_dd = equity_df["drawdown_pct"].min() if not equity_df.empty else 0
        summary = (
            f"初始资金: {cfg.initial_cash:,.2f}\n期末资金: {cash:,.2f}\n"
            f"累计收益: {total_return:.2f}%\n成交笔数: {len(filled)}\n"
            f"胜率: {wins:.2f}%\n盈亏比(Profit Factor): {profit_factor:.2f}\n"
            f"最大回撤: {max_dd:.2f}%\n"
            "注意：这是基于输入数据和简化成交假设的模拟结果，不代表可实现收益。\n"
        )
    else:
        summary = "没有产生可计算的模拟成交。请检查数据、筛选阈值和竞价成交字段。\n"
    (outdir / "summary.txt").write_text(summary, encoding="utf-8")
    print(summary)
    print(f"结果已保存到：{outdir.resolve()}")


def make_signals(df: pd.DataFrame, cfg: Config, outdir: Path):
    """当日14:56快照输入；输出尾盘候选。真实收盘竞价价未取得时只输出观察信号。"""
    rows = []
    for _, r in df.iterrows():
        sc, why = score_row(r, cfg)
        buy_ok, fill_msg = apply_buy_fill_filter(r, cfg) if np.isfinite(r.auction_buy_price) else (False, "等待收盘竞价成交数据")
        status = "BUY_WATCH" if sc >= cfg.min_score else "NO_SIGNAL"
        if sc >= cfg.min_score and np.isfinite(r.auction_buy_price):
            status = "BUY_SIGNAL" if buy_ok else "REJECTED"
        rows.append({
            "date": r.date, "symbol": r.symbol, "name": r["name"],
            "score": sc, "status": status, "reference_price_1456": r.price_1456,
            "auction_buy_price": r.auction_buy_price,
            "reason": ";".join(why + [fill_msg])
        })
    out = pd.DataFrame(rows).sort_values("score", ascending=False)
    outdir.mkdir(parents=True, exist_ok=True)
    out.to_csv(outdir / "today_buy_signals.csv", index=False, encoding="utf-8-sig")
    print(out.head(20).to_string(index=False))
    print(f"\n信号文件：{(outdir / 'today_buy_signals.csv').resolve()}")


def make_sell_signals(path: str, cfg: Config, outdir: Path):
    """
    次日竞价卖出监控输入 CSV 字段：
    symbol,name,buy_date,buy_price,shares,indicative_price_0920,auction_price_0925,
    auction_matched_amount,unmatched_sell_amount,limit_down_price
    indicative_price_0920 是 9:20 后最新可得虚拟参考价；auction_price_0925
    是收盘后才能确认的最终竞价成交价，盘前实时信号时可留空。
    """
    d = pd.read_csv(path, dtype={"symbol": str})
    required = ["symbol", "name", "buy_date", "buy_price", "shares",
                "indicative_price_0920", "auction_price_0925",
                "auction_matched_amount", "unmatched_sell_amount", "limit_down_price"]
    miss = [x for x in required if x not in d.columns]
    if miss:
        raise ValueError("卖出监控 CSV 缺少字段：" + ", ".join(miss))
    out = []
    for _, r in d.iterrows():
        px = safe_num(r.indicative_price_0920)
        final_px = safe_num(r.auction_price_0925)
        buy = safe_num(r.buy_price)
        if not np.isfinite(px) or not np.isfinite(buy) or buy <= 0:
            status, msg = "WAIT_DATA", "等待有效竞价参考价/买入价"
        else:
            gap = (px / buy - 1) * 100
            if gap >= 3:
                status, msg = "SELL_PRIORITY", f"明显高开{gap:.2f}%，优先退出"
            elif gap >= 0:
                status, msg = "SELL", f"平开至高开{gap:.2f}%，按计划退出"
            else:
                status, msg = "SELL_RISK", f"低开{gap:.2f}%，风险退出；不保证可成交"
        if np.isfinite(final_px):
            lim = safe_num(r.limit_down_price)
            matched = safe_num(r.auction_matched_amount, 0)
            if np.isfinite(lim) and final_px <= lim * 1.001 and safe_num(r.unmatched_sell_amount, 0) > matched:
                status, msg = "LOCKED_LIMIT_DOWN", "疑似跌停且卖压大，可能无法成交；不要假设已退出"
        out.append({
            "symbol": r.symbol, "name": r["name"], "status": status,
            "indicative_price_0920": px, "auction_price_0925": final_px,
            "pnl_pct_before_cost": (final_px / buy - 1) * 100 if np.isfinite(final_px) else np.nan,
            "message": msg
        })
    res = pd.DataFrame(out)
    outdir.mkdir(parents=True, exist_ok=True)
    res.to_csv(outdir / "next_day_sell_signals.csv", index=False, encoding="utf-8-sig")
    print(res.to_string(index=False))
    print(f"\n卖出信号文件：{(outdir / 'next_day_sell_signals.csv').resolve()}")


def main():
    p = argparse.ArgumentParser(description="A股尾盘竞价买入/次日竞价卖出信号与回测工具")
    sub = p.add_subparsers(dest="cmd", required=True)
    for cmd in ("backtest", "buy-signals"):
        sp = sub.add_parser(cmd)
        sp.add_argument("--input", required=True, help="标准化 CSV 文件")
        sp.add_argument("--out", default="output")
        sp.add_argument("--min-score", type=float, default=75)
        sp.add_argument("--cash", type=float, default=100000)
    ss = sub.add_parser("sell-signals")
    ss.add_argument("--input", required=True, help="次日竞价监控 CSV")
    ss.add_argument("--out", default="output")

    a = p.parse_args()
    cfg = Config(min_score=getattr(a, "min_score", 75), initial_cash=getattr(a, "cash", 100000))
    out = Path(a.out)
    if a.cmd == "backtest":
        run_backtest(load_data(a.input), cfg, out)
    elif a.cmd == "buy-signals":
        make_signals(load_data(a.input), cfg, out)
    else:
        make_sell_signals(a.input, cfg, out)


if __name__ == "__main__":
    main()
