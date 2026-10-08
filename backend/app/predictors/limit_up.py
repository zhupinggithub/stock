"""Independent next-session limit-up model for non-ST main-board A shares."""
from __future__ import annotations

import argparse
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from backend.app.predictors.multi_factor import load_market_data

DATE, CODE, NAME = "日期", "股票代码", "名称"
OPEN, CLOSE, HIGH, LOW = "开盘", "收盘", "最高", "最低"
VOLUME, AMOUNT, TURNOVER = "成交量", "成交额", "换手率"

FEATURES = {
    "ret_1": "1日涨幅", "ret_3": "3日涨幅", "ret_5": "5日涨幅", "ret_10": "10日涨幅",
    "trend_5_20": "MA5/MA20趋势", "volume_ratio_20": "20日量比", "amount_ratio_20": "20日成交额比",
    "turnover": "换手率", "turnover_change": "换手率变化", "amplitude": "日内振幅",
    "close_location": "收盘位置", "position_20": "20日价格位置", "breakout_20": "突破20日高点",
    "volatility_10": "10日波动率", "up_days_5": "近5日上涨次数", "limit_count_20": "近20日涨停次数",
    "return_rank": "当日涨幅排名", "return_rank_change": "涨幅排名改善", "amount_rank_change": "成交额排名改善",
    "turnover_rank_change": "换手率排名改善", "market_up_rate": "市场上涨比例", "market_limit_rate": "市场涨停比例",
    "market_amount_ratio": "全市场成交额变化",
}


def limit_price(previous_close: float) -> float:
    return float((Decimal(str(previous_close)) * Decimal("1.10")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def is_main_board(code: pd.Series) -> pd.Series:
    value = code.astype(str).str.zfill(6)
    return value.str.startswith(("600", "601", "603", "605", "000", "001", "002", "003"))


def add_limit_features(data: pd.DataFrame) -> pd.DataFrame:
    x = data.copy().sort_values([CODE, DATE]).reset_index(drop=True)
    g = x.groupby(CODE, sort=False)
    prev_close = g[CLOSE].shift(1)
    x["ret_1"] = x[CLOSE] / prev_close - 1
    for n in (3, 5, 10):
        x[f"ret_{n}"] = x[CLOSE] / g[CLOSE].shift(n) - 1
    ma5 = g[CLOSE].transform(lambda s: s.rolling(5, min_periods=5).mean())
    ma20 = g[CLOSE].transform(lambda s: s.rolling(20, min_periods=15).mean())
    x["trend_5_20"] = ma5 / ma20 - 1
    volume20 = g[VOLUME].transform(lambda s: s.rolling(20, min_periods=10).mean())
    amount20 = g[AMOUNT].transform(lambda s: s.rolling(20, min_periods=10).mean())
    x["volume_ratio_20"] = x[VOLUME] / volume20
    x["amount_ratio_20"] = x[AMOUNT] / amount20
    x["turnover"] = pd.to_numeric(x[TURNOVER], errors="coerce")
    x["turnover_change"] = x["turnover"] / x.groupby(CODE)["turnover"].shift(1).replace(0, np.nan) - 1
    x["amplitude"] = (x[HIGH] - x[LOW]) / prev_close
    x["close_location"] = (x[CLOSE] - x[LOW]) / (x[HIGH] - x[LOW]).replace(0, np.nan)
    low20 = g[LOW].transform(lambda s: s.rolling(20, min_periods=15).min())
    high20 = g[HIGH].transform(lambda s: s.rolling(20, min_periods=15).max())
    prior_high20 = g[HIGH].transform(lambda s: s.shift(1).rolling(20, min_periods=15).max())
    x["position_20"] = (x[CLOSE] - low20) / (high20 - low20).replace(0, np.nan)
    x["breakout_20"] = (x[CLOSE] >= prior_high20).astype(float)
    x["volatility_10"] = x.groupby(CODE)["ret_1"].transform(lambda s: s.rolling(10, min_periods=6).std())
    x["up_days_5"] = x.groupby(CODE)["ret_1"].transform(lambda s: s.gt(0).rolling(5, min_periods=3).sum())
    current_limit = pd.Series([limit_price(v) if pd.notna(v) else np.nan for v in prev_close], index=x.index)
    x["is_limit_today"] = (x[CLOSE] >= current_limit - 0.005).astype(float)
    x["limit_count_20"] = x.groupby(CODE)["is_limit_today"].transform(lambda s: s.rolling(20, min_periods=10).sum())

    for source, target in (("ret_1", "return_rank"), (AMOUNT, "amount_rank"), ("turnover", "turnover_rank")):
        x[target] = x.groupby(DATE)[source].rank(pct=True)
        x[f"{target}_change"] = x[target] - x.groupby(CODE)[target].shift(1)
    x["market_up_rate"] = x.groupby(DATE)["ret_1"].transform(lambda s: s.gt(0).mean())
    x["market_limit_rate"] = x.groupby(DATE)["is_limit_today"].transform("mean")
    daily_amount = x.groupby(DATE)[AMOUNT].sum().sort_index()
    x["market_amount_ratio"] = x[DATE].map(daily_amount / daily_amount.shift(1) - 1)

    next_open, next_high, next_low, next_close = (g[c].shift(-1) for c in (OPEN, HIGH, LOW, CLOSE))
    next_limit = pd.Series([limit_price(v) if pd.notna(v) else np.nan for v in x[CLOSE]], index=x.index)
    x["next_touch"] = (next_high >= next_limit - 0.005).astype(float).where(next_high.notna())
    x["next_seal"] = (next_close >= next_limit - 0.005).astype(float).where(next_close.notna())
    x["next_one_price"] = ((next_open >= next_limit - 0.005) & (next_low >= next_limit - 0.005)).astype(float).where(next_open.notna())
    x["next_limit_price"] = next_limit
    x["history_count"] = g.cumcount() + 1
    valid = is_main_board(x[CODE]) & ~x[NAME].astype(str).str.upper().str.contains("ST|退", regex=True, na=False)
    return x[valid].replace([np.inf, -np.inf], np.nan).reset_index(drop=True)


def corrected_probability(model, values: pd.DataFrame, prevalence: float) -> np.ndarray:
    raw = np.clip(model.predict_proba(values)[:, 1], 1e-6, 1 - 1e-6)
    odds = raw / (1 - raw) * prevalence / max(1 - prevalence, 1e-6)
    return odds / (1 + odds)


def fit_model(train: pd.DataFrame, target: str):
    model = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(max_iter=400, class_weight="balanced", C=.35))
    model.fit(train[list(FEATURES)], train[target].astype(int))
    return model, float(train[target].mean())


def rolling_backtest(featured: pd.DataFrame, top_n: int, days: int = 20) -> dict:
    dates = sorted(featured.loc[featured.next_touch.notna(), DATE].unique())
    test_dates = dates[-min(days, max(0, len(dates) - 45)):]
    rows = []
    for day in test_dates:
        train = featured[(featured[DATE] < day) & featured.next_touch.notna() & (featured.history_count >= 20)]
        test = featured[(featured[DATE] == day) & (featured.history_count >= 20)].copy()
        if len(train) < 10000 or len(test) < top_n:
            continue
        model, prevalence = fit_model(train, "next_touch")
        test["probability"] = corrected_probability(model, test[list(FEATURES)], prevalence)
        selected = test.nlargest(top_n, "probability")
        tradable = selected[selected.next_one_price == 0]
        rows.append({"date": str(pd.Timestamp(day).date()), "universe": len(test),
                     "market_touch_rate": float(test.next_touch.mean()), "top_touch_rate": float(selected.next_touch.mean()),
                     "top_seal_rate": float(selected.next_seal.mean()),
                     "tradable_touch_rate": float(tradable.next_touch.mean()) if len(tradable) else 0.0})
    if not rows:
        return {"days": 0, "rows": []}
    frame = pd.DataFrame(rows); market = float(frame.market_touch_rate.mean()); top = float(frame.top_touch_rate.mean())
    return {"days": len(frame), "top_n": top_n, "market_touch_rate": market, "top_touch_rate": top,
            "top_seal_rate": float(frame.top_seal_rate.mean()), "tradable_touch_rate": float(frame.tradable_touch_rate.mean()),
            "lift": top / market if market else None, "rows": rows}


def verify_published(data_dir: Path, featured: pd.DataFrame | None = None) -> int:
    """Verify every published batch once its next trading-day row is available."""
    output = data_dir / "predictions" / "limit_up"
    if not output.exists():
        return 0
    featured = featured if featured is not None else add_limit_features(load_market_data(data_dir))
    lookup = featured.set_index([CODE, DATE], drop=False)
    market_dates = sorted(featured[DATE].unique())
    completed = 0
    for candidate_path in sorted(output.glob("limit_up_candidates_*.csv")):
        label = candidate_path.stem.rsplit("_", 1)[-1]
        base_date = pd.to_datetime(label, format="%Y%m%d")
        future_dates = [value for value in market_dates if value > base_date]
        if not future_dates:
            continue
        actual_date = pd.Timestamp(future_dates[0])
        candidates = pd.read_csv(candidate_path, dtype={CODE: str})
        rows = []
        for candidate in candidates.to_dict("records"):
            code = str(candidate[CODE]).zfill(6)
            key = (code, base_date)
            if key not in lookup.index:
                continue
            source = lookup.loc[key]
            if isinstance(source, pd.DataFrame):
                source = source.iloc[-1]
            next_key = (code, actual_date)
            if next_key not in lookup.index:
                rows.append({"base_date": str(base_date.date()), "actual_trade_date": str(actual_date.date()), "stock_code": code,
                             "stock_name": candidate[NAME], "ranking": int(candidate["ranking"]), "touch_probability": candidate["touch_probability"],
                             "seal_probability": candidate["seal_probability"], "verified": False})
                continue
            actual = lookup.loc[next_key]
            if isinstance(actual, pd.DataFrame):
                actual = actual.iloc[-1]
            price = limit_price(float(source[CLOSE]))
            touched = bool(float(actual[HIGH]) >= price - .005)
            sealed = bool(float(actual[CLOSE]) >= price - .005)
            one_price = bool(float(actual[OPEN]) >= price - .005 and float(actual[LOW]) >= price - .005)
            rows.append({"base_date": str(base_date.date()), "actual_trade_date": str(actual_date.date()), "stock_code": code,
                         "stock_name": candidate[NAME], "ranking": int(candidate["ranking"]), "touch_probability": float(candidate["touch_probability"]),
                         "seal_probability": float(candidate["seal_probability"]), "base_close": float(source[CLOSE]), "limit_price": price,
                         "actual_open": float(actual[OPEN]), "actual_high": float(actual[HIGH]), "actual_low": float(actual[LOW]),
                         "actual_close": float(actual[CLOSE]), "touched": touched, "sealed": sealed, "one_price": one_price,
                         "tradable_touch": touched and not one_price, "verified": True})
        detail = pd.DataFrame(rows)
        if detail.empty:
            continue
        verified = detail[detail.verified]
        summary = {"base_date": str(base_date.date()), "actual_trade_date": str(actual_date.date()), "candidate_count": len(detail),
                   "verified_count": len(verified), "touch_count": int(verified.touched.sum()) if len(verified) else 0,
                   "seal_count": int(verified.sealed.sum()) if len(verified) else 0, "one_price_count": int(verified.one_price.sum()) if len(verified) else 0,
                   "touch_rate": float(verified.touched.mean()) if len(verified) else None,
                   "seal_rate": float(verified.sealed.mean()) if len(verified) else None,
                   "tradable_touch_rate": float(verified.tradable_touch.mean()) if len(verified) else None}
        detail.to_csv(output / f"limit_up_verification_{label}.csv", index=False, encoding="utf-8-sig")
        (output / f"limit_up_verification_{label}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        completed += 1
    return completed


def run(data_dir: Path, top_n: int = 20, backtest_days: int = 20) -> tuple[Path, Path, Path]:
    featured = add_limit_features(load_market_data(data_dir))
    verify_published(data_dir, featured)
    latest_date = featured[DATE].max()
    train = featured[(featured[DATE] < latest_date) & featured.next_touch.notna() & (featured.history_count >= 20)]
    latest = featured[(featured[DATE] == latest_date) & (featured.history_count >= 20)].copy()
    if len(train) < 10000 or latest.empty:
        raise RuntimeError("历史样本不足，无法训练涨停模型")
    touch_model, touch_prior = fit_model(train, "next_touch")
    seal_model, seal_prior = fit_model(train, "next_seal")
    latest["touch_probability"] = corrected_probability(touch_model, latest[list(FEATURES)], touch_prior)
    latest["seal_probability"] = corrected_probability(seal_model, latest[list(FEATURES)], seal_prior)
    latest["score"] = 100 * (.7 * latest.touch_probability.rank(pct=True) + .3 * latest.seal_probability.rank(pct=True))
    latest = latest.sort_values(["score", "touch_probability"], ascending=False).reset_index(drop=True)
    latest["ranking"] = np.arange(1, len(latest) + 1)
    latest["is_candidate"] = latest.ranking <= top_n
    output = data_dir / "predictions" / "limit_up"; output.mkdir(parents=True, exist_ok=True)
    label = pd.Timestamp(latest_date).strftime("%Y%m%d")
    columns = [DATE, CODE, NAME, "ranking", "score", CLOSE, "next_limit_price", "touch_probability", "seal_probability", "is_candidate"] + list(FEATURES)
    ranking_path = output / f"limit_up_rankings_{label}.csv"
    candidate_path = output / f"limit_up_candidates_{label}.csv"
    latest[columns].to_csv(ranking_path, index=False, encoding="utf-8-sig")
    latest.loc[latest.is_candidate, columns].to_csv(candidate_path, index=False, encoding="utf-8-sig")
    backtest = rolling_backtest(featured, top_n, backtest_days)
    coefficients = {target: {feature: float(value) for feature, value in zip(FEATURES, model[-1].coef_[0])}
                    for target, model in (("touch", touch_model), ("seal", seal_model))}
    summary = {"model_code": "limit_up_mainboard", "model_version": "1.0.0", "base_date": str(pd.Timestamp(latest_date).date()),
               "scope": "沪深主板非ST", "top_n": top_n, "universe_count": len(latest), "training_rows": len(train),
               "training_days": int(train[DATE].nunique()), "touch_prevalence": touch_prior, "seal_prevalence": seal_prior,
               "backtest": backtest, "features": FEATURES, "coefficients": coefficients,
               "notes": ["触板指下一交易日最高价达到10%涨停价", "封板指下一交易日收盘仍为涨停价", "一字板仅在事后验证中排除，不承诺可成交", "不包含行业、题材和新闻因子"]}
    summary_path = output / f"limit_up_summary_{label}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "latest.json").write_text(json.dumps({"label": label}), encoding="utf-8")
    verify_published(data_dir, featured)
    return candidate_path, ranking_path, summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description="预测沪深主板非ST股票次日触板和封板概率")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--backtest-days", type=int, default=20)
    args = parser.parse_args()
    paths = run(args.data_dir, args.top, args.backtest_days)
    print("涨停预测完成：" + "，".join(str(path) for path in paths))


if __name__ == "__main__":
    main()
