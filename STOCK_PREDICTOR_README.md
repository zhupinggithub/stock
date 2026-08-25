# 下一交易日股票候选分析说明

脚本文件：`stock_predictor.py`

## 定位

这个脚本根据本地已有的日线数据，对下一交易日可能表现较强的股票进行横截面排序。
输出是“研究候选名单”，不是确定性预测，也不是买卖建议。

脚本只读取：

```text
a_stock_daily_*.csv
daily_increment_*.csv
```

不会修改、追加或删除原始行情、`list.csv`、每日列表、失败记录和检查点。默认结果写入：

```text
数据目录/predictions/
```

## 运行方法

使用 data 数据目录生成前 30 个候选：

```powershell
python scripts/stock_predictor.py --data-dir data --top 30
```

每日收盘增量生成后，再运行同一条命令，脚本会自动合并最新增量并按最新交易日重新分析。

常用参数：

```powershell
python scripts/stock_predictor.py --data-dir data `
  --top 30 `
  --ic-days 20 `
  --min-history 25 `
  --min-amount 20000000
```

| 参数 | 含义 |
| --- | --- |
| `--top` | 输出多少只候选股票 |
| `--ic-days` | 用最近多少个有次日结果的交易日估计因子方向 |
| `--min-history` | 股票至少需要多少条历史记录 |
| `--min-amount` | 近20日最低平均成交额，用于排除流动性过低的股票 |
| `--output-dir` | 自定义结果目录 |

默认排除名称包含 `ST` 的股票。

## 输出文件

例如数据最新交易日为 2026-08-24：

```text
predictions/
├── next_day_candidates_20260824.csv
├── factor_report_20260824.csv
└── model_summary_20260824.json
```

### 候选名单

`next_day_candidates_YYYYMMDD.csv` 包含：

- 股票代码和名称；
- 最新收盘价；
- 综合评分；
- 当日和近5日涨跌幅；
- 20日量比；
- 近20日平均成交额；
- 10日波动率；
- 每个因子的市场分位数。

综合评分用于候选之间的相对排序，不是上涨概率。评分 90 不表示有 90% 的上涨概率。

### 因子报告

`factor_report_YYYYMMDD.csv` 包含每个因子的：

- 平均 IC：因子排名与下一日收益排名的日度相关性均值；
- IC 为正比例：观察期内因子方向为正的交易日比例；
- 有效交易日数量；
- 根据平均 IC 得到的模型权重。

正权重表示当前短样本中因子越高，下一日表现通常越强；负权重表示短样本中呈现反转关系。
因子方向会随市场阶段改变。

### 历史检验摘要

`model_summary_YYYYMMDD.json` 包含：

- 候选样本的次日上涨比例；
- 候选平均次日收益；
- 同期全市场平均次日收益；
- 候选相对收益。

当前实现使用同一段历史数据估计因子权重并检查候选表现，因此这是“样本内历史检验”，
不是严格样本外回测，结果通常会偏乐观。

## 当前考虑的角度

### 1. 短期价格动量与反转

- 1日收益；
- 3日收益；
- 5日收益。

它们用于判断短期趋势是在延续还是反转。脚本不预设一定追涨，而是根据最近历史中各周期
与次日收益的实际 IC 自动决定正负方向。

### 2. 均线趋势

使用 MA5 与 MA20 的相对位置衡量中短期趋势。均线向上不一定代表下一天继续上涨，
在震荡或高位阶段也可能表现为反转信号。

### 3. 成交量和成交额

- 当日成交量相对20日平均成交量；
- 当日成交额相对20日平均成交额；
- 近20日平均成交额过滤。

成交放大可能意味着趋势确认，也可能意味着短期过热，因此同样让历史 IC 决定方向。

### 4. 价格位置

计算收盘价位于近20日最高价和最低价之间的位置，用于区分接近突破、处于中间区域或
接近阶段低点。

### 5. 波动风险

使用近10日收益波动率。高波动股票可能有更强弹性，也可能有更高回撤和冲高回落风险。

### 6. 开盘缺口

比较当天开盘价和前一日收盘价。跳空可能反映新增信息，也可能在下一日出现缺口回补。

### 7. 可交易性过滤

- 排除 ST；
- 排除历史长度不足；
- 排除近20日成交额过低。

当前数据没有完整的涨跌停可成交状态、停牌原因、公告、财务指标、行业和市场情绪，
因此这些因素尚未进入评分。

## 还应进一步考虑的因素

如果要提高模型可信度，建议后续逐步加入：

1. 大盘状态：指数趋势、市场宽度、上涨家数、成交额环境；
2. 行业中性化：避免候选全部集中在单一热门行业；
3. 涨跌停和可成交性：排除次日实际难以买入的股票；
4. 公告事件：业绩预告、停复牌、减持、监管风险；
5. 基本面：盈利质量、估值、现金流和负债；
6. 更长历史：覆盖牛市、熊市、震荡市和极端行情；
7. 严格时间滚动回测：每一天只使用当时之前的数据训练，再预测下一天；
8. 交易成本：佣金、印花税、滑点和冲击成本；
9. 风险约束：行业上限、单股仓位、波动目标和最大回撤；
10. 多日验证：不要依据单一天候选直接判断模型有效性。

## 当前数据的局限

当前全量数据大约只有 42 个交易日。20日特征形成后，可用于验证的日期很少，容易受
当时市场风格影响。现阶段应把结果当作观察名单，至少持续积累数月增量数据后，再做严格
的滚动样本外检验。

## 验证下一交易日预测

验证脚本：`verify_predictions.py`

它只读取行情和候选文件，验证结果单独写到：

```text
数据目录/predictions/verification/
```

不会修改原始行情或预测候选文件。

### 每日执行顺序

交易日收盘后，建议按以下顺序执行：

1. 获取当天增量：

```powershell
python scripts/market_fetcher.py incremental --output-dir data --list-source sina
```

2. 验证上一交易日的候选：

```powershell
python scripts/verify_predictions.py --data-dir data
```

3. 使用包含当天增量的完整数据，生成下一交易日候选：

```powershell
python scripts/stock_predictor.py --data-dir data --top 30
```

验证脚本默认扫描 `predictions` 目录下所有 `next_day_candidates_*.csv`：

- 已经存在下一交易日行情的候选会生成验证报告；
- 尚无下一交易日行情的候选显示“等待验证”；
- 周末和节假日会自动选择数据中真正的下一个市场交易日，而不是简单增加一个自然日。

也可以只验证指定文件：

```powershell
python scripts/verify_predictions.py `
  --data-dir data `
  --prediction-file data\predictions\next_day_candidates_20260824.csv
```

自定义需要检验的候选范围：

```powershell
python scripts/verify_predictions.py --data-dir data --top-groups 5,10,20,30
```

### 验证输出

每个预测日期生成三个文件：

```text
verification_detail_YYYYMMDD.csv
verification_groups_YYYYMMDD.csv
verification_summary_YYYYMMDD.json
```

验证指标包括：

- 候选上涨、下跌和平盘数量；
- 候选次日上涨比例；
- 平均、中位、最好和最差次日收益；
- 同期全市场平均收益和上涨比例；
- 候选相对全市场收益；
- 综合评分与实际次日收益的 Rank IC；
- Top5、Top10、Top20、Top30 分组表现；
- 因停牌或缺失行情导致的未验证数量和覆盖率。

收益按相邻两个市场交易日的收盘价计算，暂未计入佣金、印花税、滑点、涨跌停无法成交
和冲击成本，因此它验证的是信号方向与排序能力，不等于真实交易账户收益。

## 盘中临时观察

盘中脚本：`monitor_predictions_intraday.py`

运行：

```powershell
python scripts/monitor_predictions_intraday.py --data-dir data --source sina
```

脚本只请求一轮实时股票列表，不会持续轮询。结果写入：

```text
data/predictions/intraday/
├── intraday_snapshot_YYYYMMDD_HHMMSS.csv
├── intraday_detail_YYYYMMDD_HHMMSS.csv
├── intraday_groups_YYYYMMDD_HHMMSS.csv
└── intraday_summary_YYYYMMDD_HHMMSS.json
```

它会显示：

- 全市场当前上涨比例和平均涨跌幅；
- 候选 Top5、Top10、Top20、Top30 当前上涨比例；
- 候选从预测基准日收盘至当前价格的收益；
- 候选相对全市场的盘中表现；
- 综合评分与盘中收益的 Rank IC；
- 每只候选的最新价格和当前表现。

盘中脚本不会生成 `daily_increment_*.csv`，也不会写入正式验证目录。它不会修改历史行情、
候选文件或检查点。

盘中价格随时会变化，早盘表现可能在午后反转。因此盘中结果只能用于观察，正式命中率仍
应在收盘后依次运行：

```powershell
python scripts/market_fetcher.py incremental --output-dir data --list-source sina
python scripts/verify_predictions.py --data-dir data
```

新浪实时列表不适合高频调用，不建议循环运行；人工观察时建议两次请求至少间隔30～60分钟。
