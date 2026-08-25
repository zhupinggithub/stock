"""Configurable A-share list and historical行情 downloader.

Examples:
    python market_fetcher.py all --output-dir data/20260824
    python market_fetcher.py list --output-dir data/today
    python market_fetcher.py history --output-dir data/today --days 90
    python market_fetcher.py history --output-dir data/today \
        --start-date 20260101 --end-date 20260824 --include-bj
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd


def load_akshare():
    """Import AkShare only when fetching, so --help works without the dependency."""
    try:
        import akshare
    except ImportError as exc:
        raise RuntimeError(
            "缺少依赖 akshare，请先执行：python -m pip install -U akshare pandas"
        ) from exc
    return akshare


LIST_FILENAME = "list.csv"
FAILURE_FILENAME = "history_failures.csv"
CHECKPOINT_FILENAME = "history_checkpoint.json"
CODE_COLUMN = "代码"
NAME_COLUMN = "名称"


def parse_yyyymmdd(value: str) -> str:
    """Validate a CLI date and return it in AkShare's YYYYMMDD format."""
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"日期 {value!r} 格式错误，应为 YYYYMMDD"
        ) from exc


def normalize_code(value: object) -> tuple[str, str]:
    """Return (six-digit code, optional market prefix)."""
    raw = str(value).strip().lower()
    if raw.endswith(".0"):
        raw = raw[:-2]
    match = re.fullmatch(r"([a-z]*)(\d{1,6})", raw)
    if not match:
        raise ValueError(f"无法识别股票代码：{value!r}")
    return match.group(2).zfill(6), match.group(1)


def is_beijing_stock(code: str, prefix: str) -> bool:
    """Recognise Beijing Stock Exchange codes from old and current list formats."""
    return prefix == "bj" or code.startswith(("4", "8", "920"))


def market_prefixed_code(code: str) -> str:
    """Convert a six-digit code to the symbol format required by Sina."""
    if code.startswith(("4", "8", "920")):
        return f"bj{code}"
    if code.startswith(("5", "6", "9")):
        return f"sh{code}"
    return f"sz{code}"


def normalize_sina_history(frame: pd.DataFrame, code: str) -> pd.DataFrame:
    """Convert Sina history columns and units to the Eastmoney-compatible schema."""
    required = {"date", "open", "close", "high", "low", "volume", "amount"}
    missing = required.difference(frame.columns)
    if missing:
        raise RuntimeError(f"新浪历史行情缺少字段：{sorted(missing)}")

    result = frame.rename(
        columns={
            "date": "日期",
            "open": "开盘",
            "close": "收盘",
            "high": "最高",
            "low": "最低",
            "volume": "成交量",
            "amount": "成交额",
            "turnover": "换手率",
        }
    ).copy()
    result["日期"] = pd.to_datetime(result["日期"]).dt.strftime("%Y-%m-%d")
    previous_close = result["收盘"].shift(1)
    result["涨跌额"] = result["收盘"].diff().round(4)
    result["涨跌幅"] = (result["收盘"].pct_change(fill_method=None) * 100).round(4)
    result["振幅"] = ((result["最高"] - result["最低"]) / previous_close * 100).round(4)
    # Sina volume is shares while Eastmoney's historical interface uses lots.
    result["成交量"] = result["成交量"] / 100
    if "换手率" in result.columns:
        result["换手率"] = result["换手率"] * 100
    else:
        result["换手率"] = pd.NA
    result["股票代码"] = code
    columns = [
        "日期", "股票代码", "开盘", "收盘", "最高", "最低", "成交量", "成交额",
        "振幅", "涨跌幅", "涨跌额", "换手率",
    ]
    return result[columns]


def fetch_stock_list(
    output_dir: Path,
    retries: int,
    source: str,
    reuse_on_error: bool,
    filename: str = LIST_FILENAME,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ak = load_akshare()
    target = output_dir / filename
    providers = {
        "eastmoney": ("东方财富", ak.stock_zh_a_spot_em),
        "sina": ("新浪", ak.stock_zh_a_spot),
    }
    provider_names = ("eastmoney", "sina") if source == "auto" else (source,)
    errors: list[str] = []
    stock_list: pd.DataFrame | None = None

    for provider_name in provider_names:
        display_name, fetcher = providers[provider_name]
        for attempt in range(1, retries + 1):
            print(
                f"正在从{display_name}获取 A 股实时列表（{attempt}/{retries}）……",
                flush=True,
            )
            try:
                stock_list = fetcher()
                if stock_list.empty:
                    raise RuntimeError("接口返回空数据")
                print(f"{display_name}股票列表获取成功", flush=True)
                break
            except Exception as exc:
                errors.append(f"{display_name}第 {attempt} 次：{exc!r}")
                print(f"{display_name}获取失败：{exc}", file=sys.stderr, flush=True)
                if attempt < retries:
                    time.sleep(min(2**attempt, 10) + random.random())
        if stock_list is not None:
            break

    if stock_list is None:
        if reuse_on_error and target.exists():
            print(
                f"所有实时接口均失败，继续使用已有列表：{target}",
                file=sys.stderr,
                flush=True,
            )
            return target
        details = "\n".join(errors)
        raise RuntimeError(f"所有股票列表接口均失败：\n{details}")

    required = {CODE_COLUMN, NAME_COLUMN}
    missing = required.difference(stock_list.columns)
    if missing:
        raise RuntimeError(f"实时列表缺少必要字段：{sorted(missing)}")

    stock_list.to_csv(target, index=False, encoding="utf-8-sig")
    print(f"股票列表已保存：{target}（{len(stock_list)} 行）", flush=True)
    return target


def build_daily_increment(
    list_file: Path,
    output_dir: Path,
    trade_date: str,
    include_bj: bool,
) -> Path:
    """Convert a post-close spot snapshot into an all-market daily increment."""
    spot = pd.read_csv(list_file, dtype={CODE_COLUMN: str})
    required = {
        CODE_COLUMN, NAME_COLUMN, "最新价", "涨跌幅", "涨跌额", "今开", "最高",
        "最低", "昨收", "成交量", "成交额",
    }
    missing = required.difference(spot.columns)
    if missing:
        raise ValueError(f"实时列表缺少生成日增量所需字段：{sorted(missing)}")

    rows: list[dict[str, object]] = []
    invalid = 0
    # Sina codes carry sh/sz/bj prefixes and its volume unit is shares. Eastmoney
    # codes are normally six digits and its spot volume unit is lots.
    prefixed_count = spot[CODE_COLUMN].astype(str).str.match(r"^[A-Za-z]+").sum()
    volume_is_shares = prefixed_count > len(spot) / 2

    for _, source_row in spot.iterrows():
        try:
            code, prefix = normalize_code(source_row[CODE_COLUMN])
            if not include_bj and is_beijing_stock(code, prefix):
                continue
            close = float(source_row["最新价"])
            previous_close = float(source_row["昨收"])
            open_price = float(source_row["今开"])
            high = float(source_row["最高"])
            low = float(source_row["最低"])
            volume = float(source_row["成交量"])
            amount = float(source_row["成交额"])
            change = float(source_row["涨跌额"])
            percent = float(source_row["涨跌幅"])
            # Suspended/untraded stocks do not have a daily history row.
            if volume <= 0 or close <= 0 or previous_close <= 0:
                continue
            amplitude = (high - low) / previous_close * 100
            turnover = source_row.get("换手率", pd.NA)
            if volume_is_shares:
                volume /= 100
            rows.append(
                {
                    "日期": datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d"),
                    "股票代码": code,
                    "开盘": open_price,
                    "收盘": close,
                    "最高": high,
                    "最低": low,
                    "成交量": volume,
                    "成交额": amount,
                    "振幅": round(amplitude, 4),
                    "涨跌幅": percent,
                    "涨跌额": change,
                    "换手率": turnover,
                    "名称": str(source_row[NAME_COLUMN]),
                }
            )
        except (TypeError, ValueError):
            invalid += 1

    if not rows:
        raise RuntimeError("实时列表没有可转换的已成交股票，请确认已经收盘且接口数据有效")
    result = pd.DataFrame(rows).drop_duplicates(["股票代码", "日期"], keep="last")
    target = output_dir / f"daily_increment_{trade_date}.csv"
    temporary = output_dir / f"daily_increment_{trade_date}.csv.tmp"
    result.to_csv(temporary, index=False, encoding="utf-8-sig")
    temporary.replace(target)
    print(
        f"每日增量已保存：{target}（{len(result)} 只，忽略异常记录 {invalid} 条）",
        flush=True,
    )
    return target


def run_incremental(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    trade_date = args.trade_date or date.today().strftime("%Y%m%d")
    trade_day = datetime.strptime(trade_date, "%Y%m%d").date()
    today = date.today()
    now = datetime.now()
    if trade_day > today:
        parser.error("增量交易日期不能晚于今天")
    if not args.force_incremental:
        if trade_day != today:
            parser.error("实时列表只能可靠生成当天增量；补历史日期请使用 history 模式")
        if trade_day.weekday() >= 5:
            parser.error("今天是周末；如确认需要生成，请增加 --force-incremental")
        if now.hour < 15 or (now.hour == 15 and now.minute < 10):
            parser.error("每日增量应在 15:10 后运行；如确认已收盘，请增加 --force-incremental")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / f"daily_increment_{trade_date}.csv"
    if target.exists() and not args.overwrite:
        print(f"当天增量已经存在，跳过请求：{target}", flush=True)
        return
    if target.exists() and args.overwrite:
        target.unlink()

    iso_trade_date = trade_day.strftime("%Y-%m-%d")
    for history_path in history_files(args.output_dir):
        try:
            dates = pd.read_csv(history_path, usecols=["日期"], dtype={"日期": str})
        except Exception as exc:
            raise RuntimeError(f"检查已有历史文件失败：{history_path}：{exc}") from exc
        if iso_trade_date in set(dates["日期"].dropna().unique()):
            print(f"日期 {iso_trade_date} 已存在于历史文件 {history_path.name}，跳过请求", flush=True)
            return

    snapshot_name = f"list_{trade_date}.csv"
    list_file = fetch_stock_list(
        args.output_dir,
        retries=args.retries,
        source=args.list_source,
        reuse_on_error=args.reuse_list_on_error,
        filename=snapshot_name,
    )
    build_daily_increment(
        list_file=list_file,
        output_dir=args.output_dir,
        trade_date=trade_date,
        include_bj=args.include_bj,
    )


def fetch_one_history(
    code: str,
    start_date: str,
    end_date: str,
    adjust: str,
    retries: int,
    timeout: float,
    source: str,
) -> pd.DataFrame:
    ak = load_akshare()
    source_names = ("eastmoney", "sina") if source == "auto" else (source,)
    errors: list[str] = []
    for source_name in source_names:
        for attempt in range(1, retries + 1):
            try:
                if source_name == "eastmoney":
                    return ak.stock_zh_a_hist(
                        symbol=code,
                        period="daily",
                        start_date=start_date,
                        end_date=end_date,
                        adjust=adjust,
                        timeout=timeout,
                    )
                frame = ak.stock_zh_a_daily(
                    symbol=market_prefixed_code(code),
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust,
                )
                return normalize_sina_history(frame, code)
            except Exception as exc:  # Network/data-source errors vary by AkShare version.
                errors.append(f"{source_name}第 {attempt} 次：{exc!r}")
                if attempt < retries:
                    time.sleep(min(2**attempt, 10) + random.random())
    raise RuntimeError("；".join(errors))


def history_files(output_dir: Path) -> list[Path]:
    return sorted(output_dir.glob("a_stock_daily*.csv"))


def scan_completed_codes(files: list[Path]) -> set[str]:
    """Treat data already durable on disk as the source of truth for resume."""
    completed: set[str] = set()
    for path in files:
        try:
            codes = pd.read_csv(path, usecols=["股票代码"], dtype={"股票代码": str})
        except Exception as exc:
            raise RuntimeError(f"无法读取已有分片 {path}，请检查文件是否损坏：{exc}") from exc
        for value in codes["股票代码"].dropna().unique():
            code, _ = normalize_code(value)
            completed.add(code)
    return completed


def next_chunk_number(files: list[Path]) -> int:
    numbers = []
    for path in files:
        match = re.fullmatch(r"a_stock_daily_(\d+)\.csv", path.name)
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def append_history(frame: pd.DataFrame, target: Path) -> int:
    """Append one stock and close the file before checkpointing it as complete."""
    exists = target.exists() and target.stat().st_size > 0
    frame.to_csv(
        target,
        mode="a" if exists else "w",
        header=not exists,
        index=False,
        encoding="utf-8-sig" if not exists else "utf-8",
    )
    return len(frame)


def save_checkpoint(output_dir: Path, state: dict[str, object]) -> None:
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    target = output_dir / CHECKPOINT_FILENAME
    temporary = output_dir / f"{CHECKPOINT_FILENAME}.tmp"
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def load_checkpoint(output_dir: Path) -> dict[str, object] | None:
    target = output_dir / CHECKPOINT_FILENAME
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"检查点文件损坏：{target}：{exc}") from exc


def fetch_histories(
    list_file: Path,
    output_dir: Path,
    start_date: str,
    end_date: str,
    adjust: str,
    batch_size: int,
    delay_min: float,
    delay_max: float,
    retries: int,
    timeout: float,
    history_source: str,
    include_bj: bool,
    overwrite: bool,
    limit: int | None,
) -> None:
    if not list_file.exists():
        raise FileNotFoundError(f"找不到股票列表：{list_file}")
    output_dir.mkdir(parents=True, exist_ok=True)

    stock_list = pd.read_csv(list_file, dtype={CODE_COLUMN: str})
    missing = {CODE_COLUMN, NAME_COLUMN}.difference(stock_list.columns)
    if missing:
        raise ValueError(f"股票列表缺少必要字段：{sorted(missing)}")

    candidates: list[tuple[str, str]] = []
    invalid: list[dict[str, str]] = []
    for _, row in stock_list.iterrows():
        try:
            code, prefix = normalize_code(row[CODE_COLUMN])
        except ValueError as exc:
            invalid.append({"股票代码": str(row[CODE_COLUMN]), "名称": str(row[NAME_COLUMN]), "错误": str(exc)})
            continue
        if not include_bj and is_beijing_stock(code, prefix):
            continue
        candidates.append((code, str(row[NAME_COLUMN])))

    # Keep first occurrence while preserving the source-list order.
    candidates = list(dict.fromkeys(candidates))
    if limit is not None:
        candidates = candidates[:limit]
    if not candidates:
        raise RuntimeError("筛选后没有可抓取的股票")

    existing = history_files(output_dir)
    checkpoint_path = output_dir / CHECKPOINT_FILENAME
    if overwrite:
        for path in existing:
            path.unlink()
        for path in (checkpoint_path, output_dir / FAILURE_FILENAME):
            if path.exists():
                path.unlink()
        existing = []

    candidate_hash = hashlib.sha256(
        "\n".join(code for code, _ in candidates).encode("ascii")
    ).hexdigest()
    signature = {
        "start_date": start_date,
        "end_date": end_date,
        "adjust": adjust,
        "include_bj": include_bj,
        "candidate_hash": candidate_hash,
        "candidate_count": len(candidates),
    }
    old_state = load_checkpoint(output_dir)
    if old_state and not overwrite and old_state.get("signature") != signature:
        raise RuntimeError(
            "本次参数或股票列表与已有检查点不一致。请使用上次相同的日期、复权方式、"
            "股票范围继续，或换一个输出目录；确认要从头重拉时使用 --overwrite。"
        )

    completed = scan_completed_codes(existing)
    candidate_codes = {code for code, _ in candidates}
    completed.intersection_update(candidate_codes)
    pending = [(code, name) for code, name in candidates if code not in completed]
    old_failures = old_state.get("failures", {}) if old_state else {}
    failures_by_code: dict[str, dict[str, str]] = {
        str(code): dict(record)
        for code, record in old_failures.items()
        if str(code) not in completed
    }
    for record in invalid:
        failures_by_code[str(record["股票代码"])] = record

    total_rows = 0
    successful = 0
    chunk_number = next_chunk_number(existing)
    chunk_successes = 0
    target = output_dir / f"a_stock_daily_{chunk_number}.csv"
    state: dict[str, object] = {
        "version": 1,
        "signature": signature,
        "completed": sorted(completed),
        "failures": failures_by_code,
        "status": "running",
    }
    save_checkpoint(output_dir, state)

    print(
        f"任务共 {len(candidates)} 只，已完成 {len(completed)} 只，本次待抓取 {len(pending)} 只；"
        f"日期 {start_date}～{end_date}，复权={adjust or '不复权'}",
        flush=True,
    )
    try:
        for index, (code, name) in enumerate(pending, start=1):
            try:
                frame = fetch_one_history(
                    code, start_date, end_date, adjust, retries, timeout, history_source
                )
                if frame.empty:
                    raise RuntimeError("接口返回空数据")
                frame["股票代码"] = code
                frame["名称"] = name
                total_rows += append_history(frame, target)
                completed.add(code)
                failures_by_code.pop(code, None)
                successful += 1
                chunk_successes += 1
                if chunk_successes >= batch_size:
                    print(f"分片已保存：{target}", flush=True)
                    chunk_number += 1
                    chunk_successes = 0
                    target = output_dir / f"a_stock_daily_{chunk_number}.csv"
            except Exception as exc:
                failures_by_code[code] = {"股票代码": code, "名称": name, "错误": repr(exc)}
                print(f"[{index}/{len(pending)}] 失败 {code} {name}: {exc}", file=sys.stderr, flush=True)

            state["completed"] = sorted(completed)
            state["failures"] = failures_by_code
            save_failures(list(failures_by_code.values()), output_dir, quiet=True)
            save_checkpoint(output_dir, state)
            if index % 20 == 0 or index == len(pending):
                print(
                    f"进度：{index}/{len(pending)}，累计成功 {len(completed)}，"
                    f"当前失败 {len(failures_by_code)}",
                    flush=True,
                )

            if index < len(pending) and delay_max > 0:
                time.sleep(random.uniform(delay_min, delay_max))
    except KeyboardInterrupt:
        state["status"] = "interrupted"
        state["completed"] = sorted(completed)
        state["failures"] = failures_by_code
        save_failures(list(failures_by_code.values()), output_dir)
        save_checkpoint(output_dir, state)
        print("收到中断信号，进度已保存；使用相同命令可继续。", file=sys.stderr, flush=True)
        raise SystemExit(130)

    state["status"] = "complete" if not failures_by_code else "complete_with_failures"
    state["completed"] = sorted(completed)
    state["failures"] = failures_by_code
    save_failures(list(failures_by_code.values()), output_dir)
    save_checkpoint(output_dir, state)
    print(
        f"本次完成：新增成功 {successful} 只、日线 {total_rows} 行；"
        f"累计成功 {len(completed)}/{len(candidates)} 只，失败待重试 {len(failures_by_code)} 只",
        flush=True,
    )


def save_failures(
    failures: list[dict[str, str]], output_dir: Path, quiet: bool = False
) -> None:
    target = output_dir / FAILURE_FILENAME
    if failures:
        pd.DataFrame(failures).to_csv(target, index=False, encoding="utf-8-sig")
        if not quiet:
            print(f"失败记录已保存：{target}", flush=True)
    elif target.exists():
        target.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="获取 A 股实时列表、历史日线和每日增量行情")
    parser.add_argument(
        "mode", choices=("list", "history", "all", "incremental"), help="执行内容"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(datetime.now().strftime("%Y%m%d%H")),
        help="输出目录；默认使用当前年月日小时",
    )
    parser.add_argument("--list-file", type=Path, help="history 模式使用的列表；默认是输出目录/list.csv")
    parser.add_argument("--start-date", type=parse_yyyymmdd, help="开始日期 YYYYMMDD")
    parser.add_argument("--end-date", type=parse_yyyymmdd, help="结束日期 YYYYMMDD；默认今天")
    parser.add_argument("--trade-date", type=parse_yyyymmdd, help="增量交易日期 YYYYMMDD；默认今天")
    parser.add_argument("--days", type=int, default=60, help="未指定开始日期时向前取多少个自然日，默认 60")
    parser.add_argument("--adjust", choices=("", "qfq", "hfq"), default="qfq", help="复权方式，默认 qfq")
    parser.add_argument("--batch-size", type=int, default=500, help="每个分片的股票数，默认 500")
    parser.add_argument("--delay-min", type=float, default=1.0, help="请求间最短等待秒数")
    parser.add_argument("--delay-max", type=float, default=2.5, help="请求间最长等待秒数")
    parser.add_argument("--retries", type=int, default=3, help="单只股票最大尝试次数")
    parser.add_argument("--timeout", type=float, default=15.0, help="单次接口超时秒数")
    parser.add_argument(
        "--history-source",
        choices=("auto", "eastmoney", "sina"),
        default="auto",
        help="历史行情来源；auto 会在东方财富失败后改用新浪",
    )
    parser.add_argument(
        "--list-source",
        choices=("auto", "eastmoney", "sina"),
        default="auto",
        help="股票列表来源；auto 会在东方财富失败后改用新浪",
    )
    parser.add_argument(
        "--reuse-list-on-error",
        action="store_true",
        help="实时列表获取失败时复用输出目录已有的 list.csv",
    )
    parser.add_argument("--include-bj", action="store_true", help="包含北交所股票；默认排除以兼容旧脚本")
    parser.add_argument("--overwrite", action="store_true", help="覆盖输出目录已有日线分片")
    parser.add_argument(
        "--force-incremental",
        action="store_true",
        help="允许在非交易日、非当天或收盘前强制生成增量（谨慎使用）",
    )
    parser.add_argument("--limit", type=int, help="只抓前 N 只，用于小规模测试")
    return parser


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> tuple[str, str]:
    if args.days < 1 or args.batch_size < 1 or args.retries < 1:
        parser.error("--days、--batch-size 和 --retries 必须大于 0")
    if args.delay_min < 0 or args.delay_max < args.delay_min:
        parser.error("等待时间必须满足 0 <= --delay-min <= --delay-max")
    if args.timeout <= 0 or (args.limit is not None and args.limit < 1):
        parser.error("--timeout 和 --limit 必须大于 0")

    end = args.end_date or date.today().strftime("%Y%m%d")
    start = args.start_date or (
        datetime.strptime(end, "%Y%m%d").date() - timedelta(days=args.days)
    ).strftime("%Y%m%d")
    if start > end:
        parser.error("开始日期不能晚于结束日期")
    return start, end


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    start_date, end_date = validate_args(args, parser)
    if args.mode == "incremental":
        run_incremental(args, parser)
        return
    resume_state = None
    if args.mode in {"history", "all"} and not args.overwrite:
        resume_state = load_checkpoint(args.output_dir)
    if resume_state and args.start_date is None and args.end_date is None:
        saved_signature = resume_state.get("signature", {})
        start_date = str(saved_signature["start_date"])
        end_date = str(saved_signature["end_date"])
        print(f"发现检查点，沿用原日期范围 {start_date}～{end_date}", flush=True)

    list_file = args.list_file or args.output_dir / LIST_FILENAME
    if args.mode in {"list", "all"}:
        if args.mode == "all" and resume_state and list_file.exists():
            print(f"发现检查点，续传时沿用原股票列表：{list_file}", flush=True)
        else:
            list_file = fetch_stock_list(
                args.output_dir,
                retries=args.retries,
                source=args.list_source,
                reuse_on_error=args.reuse_list_on_error,
            )
    if args.mode in {"history", "all"}:
        fetch_histories(
            list_file=list_file,
            output_dir=args.output_dir,
            start_date=start_date,
            end_date=end_date,
            adjust=args.adjust,
            batch_size=args.batch_size,
            delay_min=args.delay_min,
            delay_max=args.delay_max,
            retries=args.retries,
            timeout=args.timeout,
            history_source=args.history_source,
            include_bj=args.include_bj,
            overwrite=args.overwrite,
            limit=args.limit,
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
