#!/usr/bin/env python3
"""Phase 4: Backtesting framework — generic engine + example signal."""

import sys, os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from datetime import datetime, timezone
from db import get_connection


def log(msg: str):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}")


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    direction: str  # "long" or "short"
    size: float = 1.0
    slippage_pct: float = 0.003
    fee_pct: float = 0.001

    @property
    def pnl(self) -> float:
        if self.direction == "long":
            raw = (self.exit_price - self.entry_price) / self.entry_price
        else:
            raw = (self.entry_price - self.exit_price) / self.entry_price
        costs = 2 * (self.slippage_pct + self.fee_pct)
        return (raw - costs) * self.size


@dataclass
class BacktestResult:
    trades: List[Trade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))

    @property
    def total_pnl(self): return sum(t.pnl for t in self.trades)

    @property
    def win_rate(self):
        if not self.trades: return 0.0
        return sum(1 for t in self.trades if t.pnl > 0) / len(self.trades)

    @property
    def sharpe(self):
        if len(self.trades) < 2: return 0.0
        pnls = [t.pnl for t in self.trades]
        m, s = np.mean(pnls), np.std(pnls, ddof=1)
        if s == 0: return 0.0
        dur = self._dur()
        tpy = 365 * max(1, len(self.trades) / max(1, dur))
        return (m / s) * np.sqrt(tpy)

    @property
    def max_drawdown(self):
        if self.equity_curve.empty: return 0.0
        peak = self.equity_curve.expanding().max()
        dd = (self.equity_curve - peak) / peak
        return float(dd.min())

    def _dur(self):
        if not self.trades: return 1.0
        f = min(t.entry_time for t in self.trades)
        l = max(t.exit_time for t in self.trades)
        return max((l - f).total_seconds() / 86400, 1.0)

    def summary(self):
        print("\n" + "=" * 55)
        print("BACKTEST RESULTS")
        print("=" * 55)
        print(f"  Trades:      {len(self.trades)}")
        print(f"  Total P&L:   {self.total_pnl:+.4f} ({self.total_pnl*100:+.2f}%)")
        print(f"  Win rate:    {self.win_rate:.1%}")
        print(f"  Sharpe:      {self.sharpe:.2f}")
        print(f"  Max DD:      {self.max_drawdown:.2%}")
        if self.trades:
            pnls = [t.pnl for t in self.trades]
            durs = [(t.exit_time - t.entry_time).total_seconds()/3600 for t in self.trades]
            print(f"  Avg hold:    {np.mean(durs):.1f}h")
            print(f"  Best trade:  {max(pnls):+.4f}")
            print(f"  Worst trade: {min(pnls):+.4f}")
            longs = sum(1 for t in self.trades if t.direction == "long")
            print(f"  Long: {longs}  Short: {len(self.trades)-longs}")
        print("=" * 55)


class BacktestEngine:
    def __init__(self, prices_df, slippage_pct=0.003, fee_pct=0.001):
        self.prices = prices_df.copy()
        self.slippage = slippage_pct
        self.fee = fee_pct
        if not isinstance(self.prices.index, pd.DatetimeIndex):
            if "timestamp" in self.prices.columns:
                self.prices["datetime"] = pd.to_datetime(self.prices["timestamp"], unit="s", utc=True)
                self.prices = self.prices.set_index("datetime")

    def run(self, signals: pd.Series) -> BacktestResult:
        al = pd.concat([self.prices["close"], signals.rename("sig")], axis=1, join="inner").dropna()
        if al.empty:
            return BacktestResult()

        trades, eq, eq_t = [], [1.0], [al.index[0]]
        pos, etime, eprice = 0, None, None

        for i in range(len(al)):
            t, p, s = al.index[i], al["close"].iloc[i], int(al["sig"].iloc[i])

            if pos != 0 and s != pos:
                tr = Trade(etime, t, eprice, p, "long" if pos == 1 else "short",
                           slippage_pct=self.slippage, fee_pct=self.fee)
                trades.append(tr)
                eq.append(eq[-1] * (1 + tr.pnl))
                eq_t.append(t)
                pos, etime, eprice = 0, None, None

            if pos == 0 and s != 0:
                pos, etime, eprice = s, t, p

        if pos != 0:
            tr = Trade(etime, al.index[-1], eprice, al["close"].iloc[-1],
                       "long" if pos == 1 else "short",
                       slippage_pct=self.slippage, fee_pct=self.fee)
            trades.append(tr)
            eq.append(eq[-1] * (1 + tr.pnl))
            eq_t.append(al.index[-1])

        return BacktestResult(trades=trades, equity_curve=pd.Series(eq, index=eq_t))


class SignalGenerator(ABC):
    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series: ...


class MeanReversionSignal(SignalGenerator):
    def __init__(self, lookback=24, entry_z=2.0, exit_z=0.5):
        self.lookback = lookback
        self.entry_z = entry_z
        self.exit_z = exit_z

    def generate_signals(self, data):
        close = data["close"].resample("1h").last().dropna() if hasattr(data.index, "freq") else data["close"]
        rm = close.rolling(self.lookback, min_periods=self.lookback).mean()
        rs = close.rolling(self.lookback, min_periods=self.lookback).std()
        z = (close - rm) / rs

        signals = pd.Series(0, index=z.index, dtype=int)
        pos = 0
        for i in range(len(z)):
            if pd.isna(z.iloc[i]):
                continue
            zv = z.iloc[i]
            if pos == 0:
                if zv < -self.entry_z: pos = 1
                elif zv > self.entry_z: pos = -1
            elif pos == 1:
                if zv > -self.exit_z: pos = 0
            elif pos == -1:
                if zv < self.exit_z: pos = 0
            signals.iloc[i] = pos
        return signals


def main():
    print("\n" + "=" * 55)
    print("BITTENSOR EDGE — PHASE 4: BACKTEST")
    print("=" * 55 + "\n")

    conn = get_connection()
    prices = pd.read_sql("SELECT * FROM tao_prices ORDER BY timestamp", conn)
    conn.close()

    if prices.empty:
        log("No data. Run collection first."); return

    prices["datetime"] = pd.to_datetime(prices["timestamp"], unit="s", utc=True)
    prices = prices.set_index("datetime").sort_index()
    prices = prices[~prices.index.duplicated(keep="last")]
    log(f"Loaded {len(prices)} prices.")

    engine = BacktestEngine(prices)

    log("Strategy 1: MeanReversion(24h, z=2.0, exit=0.5)")
    s1 = MeanReversionSignal(24, 2.0, 0.5).generate_signals(prices)
    engine.run(s1).summary()

    log("Strategy 2: MeanReversion(48h, z=1.5, exit=0.3)")
    s2 = MeanReversionSignal(48, 1.5, 0.3).generate_signals(prices)
    engine.run(s2).summary()

    log("Phase 4 complete.")


if __name__ == "__main__":
    main()
