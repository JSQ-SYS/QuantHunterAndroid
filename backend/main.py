# -*- coding: utf-8 -*-
"""
QuantHunter backend: AkShare market snapshot adapter + signal API.
Run on a Windows PC/VPS; Android app connects to this service.
"""
from __future__ import annotations
import os, io, math, traceback
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="QuantHunter API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

POSITIONS = []

def main_board(code: str) -> bool:
    s = str(code).split(".")[0].zfill(6)
    return s.startswith(("600","601","603","605","000","001","002","003"))

def score_snapshot(r):
    # 仅在14:56附近人工/定时调用时，当前价才可近似代表14:56快照。
    pre = float(r.get("昨收", 0) or 0)
    px = float(r.get("最新价", 0) or 0)
    high = float(r.get("最高", px) or px)
    low = float(r.get("最低", px) or px)
    day_ret = (px/pre-1)*100 if pre > 0 else 0
    pos = (px-low)/(high-low) if high > low else 0.5
    turnover = float(r.get("换手率", 0) or 0)
    amount = float(r.get("成交额", 0) or 0)
    if not (1 <= day_ret <= 6 and 3 <= turnover <= 15 and amount >= 1e8 and pos >= .8):
        return 0, "基础过滤未通过"
    # 只有快照数据时不虚构尾盘涨幅/尾盘量比；评分为可用字段的保守评分。
    s1 = min(max(day_ret/6*25, 0), 25)
    s2 = min(max((pos-.6)/.4*20, 0), 20)
    s3 = 10 if 4 <= turnover <= 10 else 6
    s4 = 15 if amount >= 3e8 else 10
    score = s1+s2+s3+s4
    return round(score, 1), "实时快照初筛；尾盘增量资金/竞价成交尚未验证"

@app.get("/api/health")
def health():
    return {"ok": True, "service": "QuantHunter", "time": datetime.now().isoformat(timespec="seconds"),
            "message": "服务正常。AkShare行情需在A股交易时段调用；真实集合竞价字段不保证可用。"}

@app.get("/api/scan")
def scan(min_score: float = 75.0):
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            return {"items": [], "message": "AkShare未返回行情；请稍后重试或检查网络。"}
        df["代码"] = df["代码"].astype(str).str.zfill(6)
        df = df[df["代码"].map(main_board)]
        df = df[~df["名称"].astype(str).str.contains(r"ST|退", case=False, na=False)]
        rows = []
        for _, r in df.iterrows():
            try:
                score, reason = score_snapshot(r)
                if score >= min_score:
                    rows.append({
                        "symbol": str(r["代码"]), "name": str(r["名称"]), "score": score,
                        "price": float(r.get("最新价", 0) or 0),
                        "change_pct": float(r.get("涨跌幅", 0) or 0),
                        "signal": "观察候选（非买入指令）", "reason": reason
                    })
            except Exception:
                continue
        rows.sort(key=lambda x: x["score"], reverse=True)
        return {"items": rows[:30], "message": f"扫描完成，得到{len(rows)}只初筛候选。请注意：当前实现不将日内快照冒充14:56尾盘数据。"}
    except Exception as e:
        raise HTTPException(502, f"AkShare请求失败：{e}")

@app.get("/api/positions")
def positions():
    return {"items": POSITIONS, "message": "持仓列表；当前版本需通过本地记录/后续导入功能维护。"}

@app.get("/api/backtest/status")
def backtest_status():
    return {"ready": True, "message": "回测引擎接口已预留。请使用项目中的标准CSV模板；需真实收盘竞价与次日开盘竞价数据，不能用日线开盘/收盘替代。"}

@app.post("/api/backtest")
async def backtest(file: UploadFile = File(...)):
    try:
        raw = await file.read()
        df = pd.read_csv(io.BytesIO(raw))
        required = {"date","symbol","name","pre_close","price_1430","price_1456","high_1456","low_1456",
                    "volume_to_1456","volume_1430_1456","amount_to_1456","turnover_rate_to_1456","ma5_prev",
                    "auction_buy_price","auction_buy_matched_amount","next_date","next_auction_price","next_auction_matched_amount"}
        missing = sorted(required - set(df.columns))
        if missing:
            raise HTTPException(400, "CSV缺少字段: " + ",".join(missing))
        # Basic integrity check; detailed backtest is performed by companion CLI strategy.
        if df.empty:
            raise HTTPException(400, "CSV没有数据")
        return {"rows": len(df), "message": "数据格式检查通过。请在电脑端运行 overnight_auction.py backtest 执行完整回测。"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"CSV读取失败：{e}")

@app.post("/api/positions")
def add_position(item: dict):
    required = ["symbol","name","buy_date","buy_price","shares"]
    if any(k not in item for k in required):
        raise HTTPException(400, "持仓字段不完整")
    POSITIONS.append(item)
    return {"ok": True, "items": POSITIONS}

@app.get("/")
def root():
    return {"name": "QuantHunter", "docs": "/docs"}
