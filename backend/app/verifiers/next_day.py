"""Verify saved next-day candidate rankings against later local market data.

The verifier is read-only with respect to market data and prediction files.
It writes separate detail and summary files under predictions/verification.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from backend.app.predictors.multi_factor import CODE, DATE, NAME, load_market_data


def prediction_date_from_file(path: Path, predictions: pd.DataFrame) -> pd.Timestamp:
    if "预测基准日" in predictions.columns and predictions["预测基准日"].notna().any():
        values = pd.to_datetime(predictions["预测基准日"].dropna().unique(), errors="coerce")
        values = values[~pd.isna(values)]
        if len(values) != 1:
            raise ValueError(f"{path.name} 中的预测基准日不唯一")
        return pd.Timestamp(values[0])
    match = re.search(r"(\d{8})", path.stem)
    if not match:
        raise ValueError(f"无法从 {path.name} 判断预测基准日")
    return pd.to_datetime(match.group(1), format="%Y%m%d")


def next_market_date(data: pd.DataFrame, base_date: pd.Timestamp) -> pd.Timestamp | None:
    later = data.loc[data[DATE] > base_date, DATE]
    return pd.Timestamp(later.min()) if not later.empty else None


def safe_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def calculate_group_metrics(
    detail: pd.DataFrame,
    benchmark_return: float,
    top_n: int,
) -> dict[str, object]:
    selected = detail.head(top_n)
    verified = selected[selected["实际次日收益"].notna()]
    if verified.empty:
        return {
            "TopN": top_n,
            "候选数": len(selected),
            "已验证数": 0,
            "覆盖率": 0.0,
        }
    average_return = float(verified["实际次日收益"].mean())
    return {
        "TopN": top_n,
        "候选数": len(selected),
        "已验证数": len(verified),
        "覆盖率": len(verified) / len(selected),
        "上涨数量": int((verified["实际次日收益"] > 0).sum()),
        "下跌数量": int((verified["实际次日收益"] < 0).sum()),
        "平盘数量": int((verified["实际次日收益"] == 0).sum()),
        "上涨比例": float((verified["实际次日收益"] > 0).mean()),
        "平均收益": average_return,
        "中位收益": float(verified["实际次日收益"].median()),
        "最好收益": float(verified["实际次日收益"].max()),
        "最差收益": float(verified["实际次日收益"].min()),
        "全市场平均收益": benchmark_return,
        "相对全市场收益": average_return - benchmark_return,
    }


def verify_one(
    prediction_file: Path,
    market_data: pd.DataFrame,
    output_dir: Path,
    top_groups: list[int],
) -> tuple[str, dict[str, object] | None]:
    predictions = pd.read_csv(prediction_file, dtype={CODE: str})
    required = {CODE, NAME, "综合评分"}
    missing = required.difference(predictions.columns)
    if missing:
        raise ValueError(f"{prediction_file.name} 缺少字段：{sorted(missing)}")
    predictions[CODE] = (
        predictions[CODE].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )
    predictions = predictions.sort_values("综合评分", ascending=False).drop_duplicates(CODE)
    predictions["预测排名"] = np.arange(1, len(predictions) + 1)

    base_date = prediction_date_from_file(prediction_file, predictions)
    actual_date = next_market_date(market_data, base_date)
    label = base_date.strftime("%Y%m%d")
    if actual_date is None:
        return "pending", {
            "预测文件": prediction_file.name,
            "预测基准日": base_date.strftime("%Y-%m-%d"),
            "状态": "等待下一交易日行情",
        }

    base = market_data[market_data[DATE] == base_date][[CODE, "收盘"]].rename(
        columns={"收盘": "基准收盘"}
    )
    actual = market_data[market_data[DATE] == actual_date][[CODE, "收盘", NAME]].rename(
        columns={"收盘": "实际次日收盘", NAME: "实际名称"}
    )
    pair = base.merge(actual, on=CODE, how="inner")
    pair["实际次日收益"] = pair["实际次日收盘"] / pair["基准收盘"] - 1
    if pair.empty:
        raise RuntimeError(f"{base_date.date()} 与 {actual_date.date()} 没有可比较股票")

    benchmark_return = float(pair["实际次日收益"].mean())
    benchmark_up_rate = float((pair["实际次日收益"] > 0).mean())
    detail = predictions.merge(
        pair[[CODE, "基准收盘", "实际次日收盘", "实际次日收益"]],
        on=CODE,
        how="left",
    )
    detail["预测基准日"] = base_date.strftime("%Y-%m-%d")
    detail["实际交易日"] = actual_date.strftime("%Y-%m-%d")
    detail["是否上涨"] = detail["实际次日收益"].map(
        lambda value: pd.NA if pd.isna(value) else bool(value > 0)
    )
    detail["相对全市场收益"] = detail["实际次日收益"] - benchmark_return

    verified = detail[detail["实际次日收益"].notna()]
    rank_ic = verified["综合评分"].rank().corr(verified["实际次日收益"].rank())
    groups = sorted({min(value, len(detail)) for value in top_groups if value > 0})
    group_metrics = [calculate_group_metrics(detail, benchmark_return, value) for value in groups]
    summary: dict[str, object] = {
        "预测文件": prediction_file.name,
        "预测基准日": base_date.strftime("%Y-%m-%d"),
        "实际交易日": actual_date.strftime("%Y-%m-%d"),
        "候选总数": len(detail),
        "已验证候选数": len(verified),
        "未验证候选数": int(detail["实际次日收益"].isna().sum()),
        "全市场可比较股票数": len(pair),
        "全市场平均收益": benchmark_return,
        "全市场上涨比例": benchmark_up_rate,
        "评分与实际收益RankIC": safe_float(rank_ic),
        "分组结果": group_metrics,
        "说明": "收益为相邻两个市场交易日收盘价之比，未计交易成本、滑点和涨跌停可成交性",
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    detail_path = output_dir / f"verification_detail_{label}.csv"
    summary_path = output_dir / f"verification_summary_{label}.json"
    group_path = output_dir / f"verification_groups_{label}.csv"
    detail.to_csv(detail_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(group_metrics).to_csv(group_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return "verified", summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="用下一交易日行情验证候选股票预测结果")
    parser.add_argument("--data-dir", type=Path, required=True, help="行情数据目录")
    parser.add_argument(
        "--prediction-file", type=Path, help="指定一个候选文件；默认验证 predictions 下全部候选"
    )
    parser.add_argument(
        "--predictions-dir", type=Path, help="候选目录；默认 data-dir/predictions"
    )
    parser.add_argument(
        "--output-dir", type=Path, help="验证结果目录；默认 predictions/verification"
    )
    parser.add_argument(
        "--top-groups", default="5,10,20,30", help="分组验证范围，例如 5,10,20,30"
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    predictions_dir = args.predictions_dir or args.data_dir / "predictions"
    output_dir = args.output_dir or predictions_dir / "verification"
    try:
        top_groups = [int(value.strip()) for value in args.top_groups.split(",") if value.strip()]
    except ValueError as exc:
        raise SystemExit("--top-groups 必须是逗号分隔的正整数") from exc
    if not top_groups or any(value <= 0 for value in top_groups):
        raise SystemExit("--top-groups 必须包含正整数")

    files = [args.prediction_file] if args.prediction_file else sorted(
        predictions_dir.glob("next_day_candidates_*.csv")
    )
    if not files:
        raise FileNotFoundError(f"没有找到候选文件：{predictions_dir}")

    market_data = load_market_data(args.data_dir)
    verified_count = 0
    pending_count = 0
    for path in files:
        status, summary = verify_one(path, market_data, output_dir, top_groups)
        if status == "pending":
            pending_count += 1
            print(
                f"等待验证：{path.name}（基准日 {summary['预测基准日']}，尚无下一交易日行情）"
            )
            continue
        verified_count += 1
        top_result = summary["分组结果"][-1]
        if top_result.get("已验证数", 0):
            print(
                f"验证完成：{path.name} -> {summary['实际交易日']}；"
                f"Top{top_result['TopN']} 上涨比例={top_result['上涨比例']:.2%}，"
                f"平均收益={top_result['平均收益']:.2%}，"
                f"相对市场={top_result['相对全市场收益']:.2%}"
            )
        else:
            print(f"验证完成：{path.name}，但候选股票均缺少下一交易日行情")
    print(f"汇总：完成 {verified_count} 个，等待行情 {pending_count} 个；结果目录：{output_dir}")


if __name__ == "__main__":
    main()
