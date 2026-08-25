# A 股行情拉取脚本使用说明

脚本文件：`market_fetcher.py`

## 1. 功能

脚本提供三个运行模式：

| 模式 | 作用 |
| --- | --- |
| `list` | 获取 A 股实时股票列表并保存为 `list.csv` |
| `history` | 从股票列表逐只获取历史日线行情 |
| `all` | 先获取股票列表，再获取历史日线行情 |
| `incremental` | 收盘后只请求一次实时列表，生成当天的全市场日线增量 |

支持的主要配置包括：

- 自定义输出目录；
- 指定开始日期、结束日期，或按最近若干自然日查询；
- 前复权、后复权或不复权；
- 自定义每个 CSV 分片包含的股票数量；
- 自定义请求间隔、超时和重试次数；
- 股票列表及历史行情均可选择东方财富或新浪来源；
- 默认排除北交所股票，也可以选择包含；
- 失败股票保存到 `history_failures.csv`；
- 手动中断时保存当前尚未落盘的数据。

## 2. 环境准备

推荐使用 Python 3.10 及以上版本。

安装或升级依赖：

```powershell
python -m pip install -U akshare pandas "numexpr>=2.10.2" "bottleneck>=1.4.2"
```

查看所有参数：

```powershell
python scripts/market_fetcher.py --help
```

## 3. 快速测试

先使用新浪获取股票列表：

```powershell
python scripts/market_fetcher.py list --output-dir test_data --list-source sina
```

只测试前 5 只股票的历史行情：

```powershell
python scripts/market_fetcher.py history --output-dir test_data --limit 5 --history-source sina
```

成功后目录结构类似：

```text
test_data/
├── list.csv
└── a_stock_daily.csv
```

如果有股票最终获取失败，还会生成：

```text
test_data/history_failures.csv
```

## 4. 常用命令

### 每日收盘后生成增量（推荐日常使用）

首次全量任务完成后，交易日每天 15:10 以后运行：

```powershell
python scripts/market_fetcher.py incremental --output-dir data --list-source sina
```

这里的 `data` 是固定数据目录，不需要每天更换目录。脚本会按
当天日期生成独立文件，例如：

```text
20260824/
├── list_20260825.csv
└── daily_increment_20260825.csv
```

同一天重复执行相同命令时，如果增量文件已经存在，脚本会直接跳过，不会再次请求
新浪，也不会重复写入数据。

如果第一次请求失败，没有生成最终增量文件，重复原命令即可。增量文件使用临时文件
写完后再原子替换；程序在写入中途退出不会留下一个被当作成功结果的正式文件。

默认只允许为“今天”生成增量，并检查：

- 今天不是周六或周日；
- 当前时间已经达到 15:10；
- 股票有有效价格和成交量；
- 同一股票、同一日期只保留一条记录。

脚本无法仅凭实时列表可靠识别所有法定休市日；部分接口在节假日可能仍返回上一交易日
的快照。因此必须只在确认开市的交易日执行，不能仅依赖周末检查。

如确实需要绕过日期和时间检查，可使用（一般不建议）：

```powershell
python scripts/market_fetcher.py incremental --output-dir data --list-source sina --force-incremental
```

覆盖当天已经生成的增量：

```powershell
python scripts/market_fetcher.py incremental --output-dir data --list-source sina --overwrite
```

每日增量不会修改首次全量任务的以下文件：

```text
list.csv
history_checkpoint.json
a_stock_daily_*.csv
```

因此不会破坏全量历史任务及其断点续传状态。

### 一次完成列表和历史行情抓取

当前网络环境无法稳定访问东方财富时，建议直接使用新浪：

```powershell
python scripts/market_fetcher.py all --output-dir data --list-source sina --history-source sina
```

### 自动选择数据源

`auto` 会先调用东方财富，失败后切换新浪：

```powershell
python scripts/market_fetcher.py all --output-dir data --list-source auto --history-source auto
```

如果已知东方财富不可访问，直接选择新浪可以避免等待东方财富多次重试。

### 指定日期范围

```powershell
python scripts/market_fetcher.py history --output-dir data --start-date 20260701 --end-date 20260824 --history-source sina
```

日期格式必须是 `YYYYMMDD`。

### 获取最近 90 个自然日

```powershell
python scripts/market_fetcher.py history --output-dir data --days 90 --history-source sina
```

脚本按自然日计算开始日期，返回的数据本身只包含交易日。

### 使用指定股票列表

```powershell
python scripts/market_fetcher.py history --output-dir history_data --list-file .\list.csv --history-source sina
```

股票列表至少需要包含以下两列：

```text
代码,名称
```

股票代码可以是 `600000`，也可以是 `sh600000`、`sz000001`、`bj430017` 等形式。

### 包含北交所股票

```powershell
python scripts/market_fetcher.py history --output-dir data --include-bj --history-source sina
```

### 调整请求速度

```powershell
python scripts/market_fetcher.py history --output-dir data --delay-min 1.5 --delay-max 3.0 --retries 3 --history-source sina
```

新浪接口不适合短时间高频请求，不建议把等待时间设置得过低。

## 5. 输出文件

### 股票列表

```text
输出目录/list.csv
```

文件保存实时股票列表，至少包含 `代码`、`名称` 等字段。

### 历史行情分片

默认每 500 只股票保存一个文件：

```text
a_stock_daily_1.csv
a_stock_daily_2.csv
...
```

脚本按成功股票数分片。为了保证断点续传，每只股票成功后会立即追加到当前编号分片，
最后不足一个完整分片的数据也保留在当前编号文件中。

历史 CSV 主要字段为：

```text
日期,股票代码,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率,名称
```

新浪接口的英文字段会被脚本转换成上述中文结构。新浪成交量原始单位是“股”，脚本会除以 100，转换成与东方财富历史接口一致的“手”。

### 每日增量文件

```text
daily_increment_YYYYMMDD.csv
```

每日增量与历史分片使用相同的核心字段：

```text
日期,股票代码,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率,名称
```

转换关系为：

| 实时列表 | 日线增量 |
| --- | --- |
| 最新价 | 收盘 |
| 今开 | 开盘 |
| 最高 | 最高 |
| 最低 | 最低 |
| 成交量 | 成交量（新浪来源会从“股”换算成“手”） |
| 成交额 | 成交额 |
| 涨跌幅 | 涨跌幅 |
| 涨跌额 | 涨跌额 |
| `(最高-最低)/昨收` | 振幅 |

停牌、成交量为零或价格无效的股票不会写入当天日线。这与历史行情接口通常不为停牌日
生成记录的行为一致。

增量文件保持独立，不会物理追加到原来的大型历史分片。分析时应同时读取：

```text
a_stock_daily_*.csv
daily_increment_*.csv
```

然后按 `股票代码 + 日期` 去重。

### 前复权注意事项

首次全量历史默认使用前复权 `qfq`。前复权以当前价格为锚点，所以正常情况下当天收盘
快照可以作为最新一日使用；但股票发生分红、送转、配股等除权事件后，历史前复权价格
可能整体重新计算，而旧的全量文件不会被每日增量自动回写。

适合短线筛选的维护方式是：

1. 每个交易日使用 `incremental` 生成一天增量；
2. 定期（例如每周或每月）换一个新目录重新抓取最近 60～90 天前复权历史；
3. 需要严格复权一致性的研究，不应长期只追加实时快照。

### 失败清单

```text
输出目录/history_failures.csv
```

包含：

```text
股票代码,名称,错误
```

如果本次没有失败，旧的失败清单会被删除。

## 6. 失败、重试和重新运行

### 单次运行中的重试

每只股票默认最多尝试 3 次，可以通过 `--retries` 修改：

```powershell
python scripts/market_fetcher.py history --output-dir test_data --retries 5 --history-source sina
```

一只股票在所有尝试中都失败后，脚本会：

1. 将它写入 `history_failures.csv`；
2. 继续处理下一只股票；
3. 不会因为单只股票失败而终止全量任务。

### 再次执行和断点续传

当前版本默认启用断点续传，不需要额外参数。

- 每只股票成功后，数据会立即追加到 CSV，然后更新 `history_checkpoint.json`。
- 重启时，脚本会扫描所有已有 `a_stock_daily*.csv` 中的股票代码。
- 已经成功落盘的股票不会再次请求。
- 以前失败的股票和程序退出前尚未处理的股票会继续抓取。
- 如果一次任务已经全部成功，使用相同命令再次执行不会发起行情请求。
- 如果失败股票在下一次运行中成功，它会从 `history_failures.csv` 中移除。

断点文件为：

```text
输出目录/history_checkpoint.json
```

续传时应使用与上一次相同的输出目录、日期范围、复权方式、股票范围和 `--limit`
设置。参数或股票列表发生变化时，脚本会拒绝混写，并提示换目录或使用
`--overwrite` 从头执行。

继续运行只需要重复原命令，例如：

```powershell
python scripts/market_fetcher.py history --output-dir test_data --limit 5 --history-source sina
```

如果原先使用的是 `all` 模式，也可以原样重复。发现检查点后，脚本会沿用原来的
`list.csv` 和日期范围，不会在跨天续传时刷新股票列表或改变查询结束日期：

```powershell
python scripts/market_fetcher.py all --output-dir data --list-source sina --history-source sina
```

强制从头覆盖的示例：

从头覆盖的示例：

```powershell
python scripts/market_fetcher.py history --output-dir test_data --history-source sina --overwrite
```

`--overwrite` 会删除已有日线分片、失败清单和检查点，但不会删除 `list.csv`。

### 手动中断

按 `Ctrl+C` 时会更新检查点并退出。由于每只成功股票都已经单独追加落盘，
不需要等待凑满 500 只，也不会丢失当前分片中已成功的数据。之后重复原命令即可继续。

## 7. 数据源说明

### 股票列表

```text
--list-source auto
--list-source eastmoney
--list-source sina
```

`auto` 默认先重试东方财富，再尝试新浪。

实时接口全部失败时，如果输出目录已经有 `list.csv`，可以选择复用：

```powershell
python scripts/market_fetcher.py all --output-dir data --reuse-list-on-error --history-source sina
```

### 历史行情

```text
--history-source auto
--history-source eastmoney
--history-source sina
```

当前环境中东方财富连接被远端主动断开，建议使用：

```text
--history-source sina
```

## 8. 注意事项

1. 全市场约有数千只股票，按默认等待时间运行可能需要数小时。
2. 不要在不同终端中同时向同一个输出目录运行历史抓取。
3. 正式全量运行前，建议先使用 `--limit 5` 或 `--limit 20` 测试。
4. `--overwrite` 会删除指定输出目录中的历史行情分片，使用前应确认目录正确。
5. 目录名只是输出位置，不自动代表行情数据的最大交易日期；实际日期以 CSV 的 `日期` 字段为准。
