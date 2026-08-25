"""Rank next-session A-share candidates from local daily market data.

This is an exploratory factor-ranking tool, not a guarantee of future returns.
It estimates factor directions only from information available before the
prediction date and reports an out-of-sample-like next-day historical summary.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd


CODE = "股票代码"
DATE = "日期"
NAME = "名称"
FEATURES = {
    "ret_1": "1日动量",
    "ret_3": "3日动量",
    "ret_5": "5日动量",
    "trend_5_20": "均线趋势(MA5/MA20)",
    "volume_ratio_20": "量比(当日/20日)",
    "amount_ratio_20": "成交额比(当日/20日)",
    "position_20": "20日价格位置",
    "volatility_10": "10日波动率",
    "gap": "开盘缺口",
}


def load_market_data(data_dir: Path) -> pd.DataFrame:
    files = sorted(data_dir.glob("a_stock_daily*.csv"))
    files += sorted(data_dir.glob("daily_increment_*.csv"))
    if not files:
        raise FileNotFoundError(f"目录中没有历史或增量行情文件：{data_dir}")

    required = {
        DATE, CODE, NAME, "开盘", "收盘", "最高", "最低", "成交量", "成交额"
    }
    frames = []
    for path in files:
        frame = pd.read_csv(path, dtype={CODE: str})
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"{path.name} 缺少字段：{sorted(missing)}")
        frame["_source_order"] = len(frames)
        frames.append(frame)

    data = pd.concat(frames, ignore_index=True)
    data[CODE] = data[CODE].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    data[DATE] = pd.to_datetime(data[DATE], errors="coerce")
    numeric = ["开盘", "收盘", "最高", "最低", "成交量", "成交额", "换手率"]
    for column in numeric:
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=[DATE, CODE, "收盘"]).sort_values(
        [CODE, DATE, "_source_order"]
    )
    # A daily increment wins if it overlaps a historical row loaded earlier.
    data = data.drop_duplicates([CODE, DATE], keep="last").drop(columns="_source_order")
    return data.sort_values([CODE, DATE]).reset_index(drop=True)


def add_features(data: pd.DataFrame) -> pd.DataFrame:
    result = data.copy()
    group = result.groupby(CODE, sort=False)
    close = result["收盘"]
    previous_close = group["收盘"].shift(1)

    result["ret_1"] = close / previous_close - 1
    result["ret_3"] = close / group["收盘"].shift(3) - 1
    result["ret_5"] = close / group["收盘"].shift(5) - 1
    result["ma_5"] = group["收盘"].transform(lambda s: s.rolling(5, min_periods=5).mean())
    result["ma_20"] = group["收盘"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    result["trend_5_20"] = result["ma_5"] / result["ma_20"] - 1
    result["volume_ma20"] = group["成交量"].transform(
        lambda s: s.rolling(20, min_periods=10).mean()
    )
    result["amount_ma20"] = group["成交额"].transform(
        lambda s: s.rolling(20, min_periods=10).mean()
    )
    result["volume_ratio_20"] = result["成交量"] / result["volume_ma20"] - 1
    result["amount_ratio_20"] = result["成交额"] / result["amount_ma20"] - 1
    low_20 = group["最低"].transform(lambda s: s.rolling(20, min_periods=10).min())
    high_20 = group["最高"].transform(lambda s: s.rolling(20, min_periods=10).max())
    result["position_20"] = (close - low_20) / (high_20 - low_20).replace(0, np.nan)
    result["volatility_10"] = result.groupby(CODE, sort=False)["ret_1"].transform(
        lambda s: s.rolling(10, min_periods=6).std()
    )
    result["gap"] = result["开盘"] / previous_close - 1
    result["next_return"] = group["收盘"].shift(-1) / close - 1
    result["history_count"] = group.cumcount() + 1
    return result


def cross_section_rank(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame.groupby(DATE)[column].rank(pct=True, method="average")


def estimate_factor_weights(
    data: pd.DataFrame, ic_days: int
) -> tuple[dict[str, float], pd.DataFrame]:
    usable_dates = sorted(data.loc[data["next_return"].notna(), DATE].unique())[-ic_days:]
    sample = data[data[DATE].isin(usable_dates)].copy()
    target_rank = cross_section_rank(sample, "next_return")
    report_rows = []

    for feature, label in FEATURES.items():
        feature_rank = cross_section_rank(sample, feature)
        pairs = pd.DataFrame(
            {DATE: sample[DATE], "feature": feature_rank, "target": target_rank}
        ).dropna()
        daily_ic = []
        for _, day in pairs.groupby(DATE):
            if len(day) >= 100:
                daily_ic.append(day["feature"].corr(day["target"]))
        mean_ic = float(np.nanmean(daily_ic)) if daily_ic else 0.0
        report_rows.append(
            {
                "因子": feature,
                "含义": label,
                "平均IC": mean_ic,
                "IC为正比例": float(np.mean(np.array(daily_ic) > 0)) if daily_ic else np.nan,
                "有效交易日": len(daily_ic),
            }
        )

    report = pd.DataFrame(report_rows)
    raw = dict(zip(report["因子"], report["平均IC"]))
    denominator = sum(abs(value) for value in raw.values())
    if denominator < 1e-12:
        raise RuntimeError("历史样本不足以估计因子方向，请增加历史数据长度")
    weights = {key: value / denominator for key, value in raw.items()}
    report["模型权重"] = report["因子"].map(weights)
    return weights, report


def rank_latest(
    featured: pd.DataFrame,
    weights: dict[str, float],
    top_n: int,
    min_history: int,
    min_amount: float,
) -> pd.DataFrame:
    latest_date = featured[DATE].max()
    latest = featured[featured[DATE] == latest_date].copy()
    latest = latest[
        (latest["history_count"] >= min_history)
        & (latest["amount_ma20"] >= min_amount)
        & (~latest[NAME].astype(str).str.upper().str.contains("ST", na=False))
    ].copy()
    if latest.empty:
        raise RuntimeError("最新交易日没有满足历史长度和流动性条件的股票")

    score = pd.Series(0.0, index=latest.index)
    for feature, weight in weights.items():
        ranked = latest[feature].rank(pct=True, method="average")
        latest[f"因子分位_{FEATURES[feature]}"] = ranked
        score += (ranked.fillna(0.5) - 0.5) * weight
    latest["综合评分"] = (50 + 100 * score).clip(0, 100)
    latest["预测基准日"] = latest_date.strftime("%Y-%m-%d")
    latest["近20日平均成交额"] = latest["amount_ma20"]
    latest["当日涨跌幅"] = latest["ret_1"] * 100
    latest["近5日涨跌幅"] = latest["ret_5"] * 100
    latest["量比20日"] = latest["volume_ratio_20"] + 1
    latest["波动率10日"] = latest["volatility_10"]

    columns = [
        "预测基准日", CODE, NAME, "综合评分", "收盘", "当日涨跌幅", "近5日涨跌幅",
        "量比20日", "近20日平均成交额", "波动率10日",
    ] + [f"因子分位_{label}" for label in FEATURES.values()]
    return latest.sort_values("综合评分", ascending=False)[columns].head(top_n).reset_index(drop=True)


def add_return_estimates(
    featured: pd.DataFrame, candidates: pd.DataFrame, max_train_days: int = 120
) -> tuple[pd.DataFrame, dict[str, float | int | str]]:
    """Add an experimental ridge return estimate and residual-based interval."""
    usable = featured[featured["next_return"].notna()].copy()
    train_dates = sorted(usable[DATE].dropna().unique())[-max_train_days:]
    usable = usable[usable[DATE].isin(train_dates)]
    ranked = pd.DataFrame(index=usable.index)
    for feature in FEATURES:
        ranked[feature] = usable.groupby(DATE)[feature].rank(pct=True) - 0.5
    ranked["target"] = usable["next_return"]
    ranked = ranked.dropna()
    if len(train_dates) < 5 or len(ranked) < 1000:
        raise RuntimeError("历史样本不足以估计个股预期收益")

    x = ranked[list(FEATURES)].to_numpy(dtype=float)
    y = ranked["target"].to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(x)), x])
    penalty = np.eye(design.shape[1])
    penalty[0, 0] = 0
    coefficients = np.linalg.solve(design.T @ design + 1.0 * penalty, design.T @ y)
    residuals = y - design @ coefficients
    residual_std = max(float(np.std(residuals, ddof=design.shape[1])), 1e-6)

    latest_x = []
    for _, row in candidates.iterrows():
        latest_x.append(
            [float(row[f"因子分位_{FEATURES[feature]}"]) - 0.5 for feature in FEATURES]
        )
    expected = np.column_stack([np.ones(len(latest_x)), np.asarray(latest_x)]) @ coefficients
    normal = NormalDist()
    probability = np.array([normal.cdf(value / residual_std) for value in expected])
    lower = expected - 1.645 * residual_std
    upper = expected + 1.645 * residual_std
    base_price = candidates["收盘"].to_numpy(dtype=float)
    result = candidates.copy()
    result["上涨概率"] = probability
    result["预计次日收益"] = expected
    result["预计收益下限90"] = lower
    result["预计收益上限90"] = upper
    result["预计目标价格"] = base_price * (1 + expected)
    result["预计价格下限90"] = base_price * (1 + lower)
    result["预计价格上限90"] = base_price * (1 + upper)
    # Confidence reflects time coverage, not the probability of being correct.
    result["预测置信度"] = min(1.0, len(train_dates) / 120.0)
    return result, {
        "收益模型": "岭回归（实验性）",
        "收益模型训练交易日": len(train_dates),
        "收益模型训练样本": len(ranked),
        "收益模型残差波动率": residual_std,
        "收益区间置信水平": 0.90,
        "收益模型说明": "上涨概率由预计收益和历史残差分布估算；短历史下置信度较低",
    }


def historical_top_summary(
    featured: pd.DataFrame,
    weights: dict[str, float],
    top_n: int,
    ic_days: int,
    min_history: int,
    min_amount: float,
) -> dict[str, float | int]:
    dates = sorted(featured.loc[featured["next_return"].notna(), DATE].unique())[-ic_days:]
    returns = []
    universe_returns = []
    for day_value in dates:
        day = featured[featured[DATE] == day_value].copy()
        day = day[
            (day["history_count"] >= min_history)
            & (day["amount_ma20"] >= min_amount)
            & day["next_return"].notna()
            & (~day[NAME].astype(str).str.upper().str.contains("ST", na=False))
        ]
        if len(day) < max(100, top_n):
            continue
        score = pd.Series(0.0, index=day.index)
        for feature, weight in weights.items():
            score += (day[feature].rank(pct=True).fillna(0.5) - 0.5) * weight
        selected = day.loc[score.nlargest(top_n).index, "next_return"]
        returns.extend(selected.tolist())
        universe_returns.extend(day["next_return"].tolist())
    if not returns:
        return {"样本内检验交易日": 0}
    return {
        "样本内检验交易日": len(dates),
        "候选样本数": len(returns),
        "候选次日上涨比例": float(np.mean(np.array(returns) > 0)),
        "候选平均次日收益": float(np.mean(returns)),
        "全市场平均次日收益": float(np.mean(universe_returns)),
        "候选相对收益": float(np.mean(returns) - np.mean(universe_returns)),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="基于本地日线数据生成下一交易日候选排名")
    parser.add_argument("--data-dir", type=Path, required=True, help="行情数据目录")
    parser.add_argument("--output-dir", type=Path, help="结果目录；默认 data-dir/predictions")
    parser.add_argument("--top", type=int, default=30, help="输出候选数量，默认 30")
    parser.add_argument("--ic-days", type=int, default=20, help="估计因子有效性的最近交易日数")
    parser.add_argument("--min-history", type=int, default=25, help="股票最少历史记录数")
    parser.add_argument(
        "--min-amount", type=float, default=20_000_000, help="近20日最低平均成交额，默认两千万元"
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if min(args.top, args.ic_days, args.min_history) < 1 or args.min_amount < 0:
        raise SystemExit("参数必须为正数，--min-amount 可以为 0")
    output_dir = args.output_dir or args.data_dir / "predictions"
    output_dir.mkdir(parents=True, exist_ok=True)

    data = load_market_data(args.data_dir)
    featured = add_features(data)
    weights, factor_report = estimate_factor_weights(featured, args.ic_days)
    candidates = rank_latest(
        featured, weights, args.top, args.min_history, args.min_amount
    )
    candidates, return_model_summary = add_return_estimates(featured, candidates)
    summary = historical_top_summary(
        featured, weights, args.top, args.ic_days, args.min_history, args.min_amount
    )
    summary.update(return_model_summary)

    label = candidates.iloc[0]["预测基准日"].replace("-", "")
    candidate_path = output_dir / f"next_day_candidates_{label}.csv"
    factor_path = output_dir / f"factor_report_{label}.csv"
    summary_path = output_dir / f"model_summary_{label}.json"
    candidates.to_csv(candidate_path, index=False, encoding="utf-8-sig")
    factor_report.to_csv(factor_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"数据最新交易日：{candidates.iloc[0]['预测基准日']}")
    print(f"候选结果：{candidate_path}")
    print(f"因子报告：{factor_path}")
    print(f"历史检验：{summary_path}")
    print("前10名：")
    print(candidates[[CODE, NAME, "综合评分", "收盘"]].head(10).to_string(index=False))
    print("历史检验摘要：", summary)
    print("提示：该检验与因子权重使用同一段短历史样本，属于样本内结果，不代表未来胜率。")


if __name__ == "__main__":
    main()
