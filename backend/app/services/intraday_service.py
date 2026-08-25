"""Observe saved next-day candidates against a single intraday spot snapshot."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from backend.app.collectors.market_fetcher import CODE_COLUMN, NAME_COLUMN, fetch_stock_list, normalize_code
from backend.app.predictors.multi_factor import CODE, NAME


def find_latest_prediction(predictions_dir: Path) -> Path:
    files = sorted(predictions_dir.glob("next_day_candidates_*.csv"))
    if not files:
        raise FileNotFoundError(f"没有找到候选文件：{predictions_dir}")
    return files[-1]


def normalize_spot(snapshot: pd.DataFrame) -> pd.DataFrame:
    required = {CODE_COLUMN, NAME_COLUMN, "最新价", "涨跌幅", "涨跌额", "昨收"}
    missing = required.difference(snapshot.columns)
    if missing:
        raise ValueError(f"实时列表缺少字段：{sorted(missing)}")
    rows = []
    for _, row in snapshot.iterrows():
        try:
            code, _ = normalize_code(row[CODE_COLUMN])
            latest = float(row["最新价"])
            previous = float(row["昨收"])
            percent = float(row["涨跌幅"])
            change = float(row["涨跌额"])
            if latest <= 0 or previous <= 0:
                continue
            rows.append(
                {
                    CODE: code,
                    "实时名称": str(row[NAME_COLUMN]),
                    "盘中最新价": latest,
                    "昨收": previous,
                    "盘中涨跌幅": percent / 100,
                    "盘中涨跌额": change,
                }
            )
        except (TypeError, ValueError):
            continue
    if not rows:
        raise RuntimeError("实时列表没有可用行情")
    return pd.DataFrame(rows).drop_duplicates(CODE, keep="last")


def group_metrics(detail: pd.DataFrame, top_n: int, market_return: float) -> dict[str, object]:
    selected = detail.head(top_n)
    valid = selected[selected["预测期内盘中收益"].notna()]
    if valid.empty:
        return {"TopN": top_n, "候选数": len(selected), "有效数": 0}
    average = float(valid["预测期内盘中收益"].mean())
    return {
        "TopN": top_n,
        "候选数": len(selected),
        "有效数": len(valid),
        "当前上涨数": int((valid["预测期内盘中收益"] > 0).sum()),
        "当前下跌数": int((valid["预测期内盘中收益"] < 0).sum()),
        "当前平盘数": int((valid["预测期内盘中收益"] == 0).sum()),
        "当前上涨比例": float((valid["预测期内盘中收益"] > 0).mean()),
        "当前平均收益": average,
        "当前中位收益": float(valid["预测期内盘中收益"].median()),
        "当前最好收益": float(valid["预测期内盘中收益"].max()),
        "当前最差收益": float(valid["预测期内盘中收益"].min()),
        "全市场当前平均涨跌幅": market_return,
        "当前相对全市场收益": average - market_return,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="用单次盘中快照临时观察候选股票表现")
    parser.add_argument("--data-dir", type=Path, required=True, help="行情及 predictions 所在目录")
    parser.add_argument("--prediction-file", type=Path, help="候选文件；默认使用最新候选")
    parser.add_argument(
        "--source", choices=("auto", "eastmoney", "sina"), default="sina", help="实时列表来源"
    )
    parser.add_argument("--retries", type=int, default=3, help="实时列表请求次数")
    parser.add_argument("--top-groups", default="5,10,20,30", help="观察 Top N 分组")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.retries < 1:
        raise SystemExit("--retries 必须大于 0")
    try:
        top_groups = [int(item.strip()) for item in args.top_groups.split(",") if item.strip()]
    except ValueError as exc:
        raise SystemExit("--top-groups 必须是逗号分隔的正整数") from exc
    if not top_groups or any(value <= 0 for value in top_groups):
        raise SystemExit("--top-groups 必须包含正整数")

    predictions_dir = args.data_dir / "predictions"
    prediction_file = args.prediction_file or find_latest_prediction(predictions_dir)
    predictions = pd.read_csv(prediction_file, dtype={CODE: str})
    required = {CODE, NAME, "综合评分", "收盘", "预测基准日"}
    missing = required.difference(predictions.columns)
    if missing:
        raise ValueError(f"候选文件缺少字段：{sorted(missing)}")
    predictions[CODE] = (
        predictions[CODE].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )
    predictions = predictions.sort_values("综合评分", ascending=False).drop_duplicates(CODE)
    predictions["预测排名"] = np.arange(1, len(predictions) + 1)

    now = datetime.now()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    output_dir = predictions_dir / "intraday"
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = fetch_stock_list(
        output_dir,
        retries=args.retries,
        source=args.source,
        reuse_on_error=False,
        filename=f"intraday_snapshot_{stamp}.csv",
    )
    snapshot = pd.read_csv(snapshot_path, dtype={CODE_COLUMN: str})
    spot = normalize_spot(snapshot)
    market_return = float(spot["盘中涨跌幅"].mean())
    market_up_rate = float((spot["盘中涨跌幅"] > 0).mean())

    detail = predictions.merge(spot, on=CODE, how="left")
    detail["观察时间"] = now.isoformat(timespec="seconds")
    detail["预测期内盘中收益"] = detail["盘中最新价"] / detail["收盘"] - 1
    detail["当前是否上涨"] = detail["预测期内盘中收益"].map(
        lambda value: pd.NA if pd.isna(value) else bool(value > 0)
    )
    detail["当前相对全市场"] = detail["预测期内盘中收益"] - market_return
    valid = detail[detail["预测期内盘中收益"].notna()]
    rank_ic = valid["综合评分"].rank().corr(valid["预测期内盘中收益"].rank())
    groups = sorted({min(value, len(detail)) for value in top_groups})
    metrics = [group_metrics(detail, value, market_return) for value in groups]

    summary = {
        "状态": "盘中临时观察，非收盘正式验证",
        "候选文件": prediction_file.name,
        "预测基准日": str(predictions.iloc[0]["预测基准日"]),
        "观察时间": now.isoformat(timespec="seconds"),
        "行情来源": args.source,
        "候选总数": len(detail),
        "有效候选数": len(valid),
        "全市场有效股票数": len(spot),
        "全市场当前平均涨跌幅": market_return,
        "全市场当前上涨比例": market_up_rate,
        "评分与盘中收益RankIC": None if pd.isna(rank_ic) else float(rank_ic),
        "分组结果": metrics,
        "说明": "行情仍会变化；盘中结果不得写入正式验证，也不代表最终收盘表现",
    }
    detail_path = output_dir / f"intraday_detail_{stamp}.csv"
    group_path = output_dir / f"intraday_groups_{stamp}.csv"
    summary_path = output_dir / f"intraday_summary_{stamp}.json"
    detail.to_csv(detail_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(metrics).to_csv(group_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    top_result = metrics[-1]
    print("盘中临时观察（不是正式收盘验证）")
    print(f"观察时间：{summary['观察时间']}")
    print(f"全市场：上涨比例={market_up_rate:.2%}，平均涨跌幅={market_return:.2%}")
    if top_result.get("有效数", 0):
        print(
            f"Top{top_result['TopN']}：上涨比例={top_result['当前上涨比例']:.2%}，"
            f"平均收益={top_result['当前平均收益']:.2%}，"
            f"相对市场={top_result['当前相对全市场收益']:.2%}"
        )
    print("当前前10名表现：")
    print(
        detail[["预测排名", CODE, NAME, "综合评分", "盘中最新价", "预测期内盘中收益"]]
        .head(10)
        .to_string(index=False)
    )
    print(f"详细结果：{detail_path}")
    print(f"汇总结果：{summary_path}")


if __name__ == "__main__":
    main()
