# A股量化观察台

一个完整的本地 A 股研究项目，覆盖行情采集、多因子预测、盘中观察、次日验证、MySQL 持久化和 Vue 可视化。

## 项目结构

```text
stock/
├── backend/
│   ├── app/
│   │   ├── api/             # FastAPI 分模块路由
│   │   ├── collectors/      # 新浪/东方财富行情采集
│   │   ├── predictors/      # 多因子排名模型
│   │   ├── verifiers/       # 下一交易日验证
│   │   ├── models/          # SQLAlchemy 实体
│   │   ├── repositories/    # MySQL 写入和查询
│   │   ├── schemas/         # Pydantic 响应模型
│   │   ├── services/        # 盘中及业务服务
│   │   ├── jobs/            # 每日流水线
│   │   ├── config.py
│   │   ├── database.py
│   │   └── main.py          # FastAPI 入口
│   ├── migrations/          # 数据库基线及后续迁移
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── router/
│   │   └── views/           # 总览、预测、盘中、验证、行情
│   ├── dist/                # Vite 生产构建，由后端托管
│   └── package.json
├── scripts/                 # 向后兼容的命令入口
│   ├── market_fetcher.py
│   ├── stock_predictor.py
│   ├── verify_predictions.py
│   ├── monitor_predictions_intraday.py
│   ├── stock_pipeline.py
│   └── import_existing_csv.py
├── data/                     # 原始行情、增量及分析结果
├── .env.example
└── start_web.ps1
```

## 安装

```powershell
python -m pip install -r backend/requirements.txt
cd frontend
npm install
npm run build
cd ..
```

复制 `.env.example` 为不会提交的 `.env`，并填写本机 MySQL 用户名和密码。默认连接本机 `127.0.0.1:3306` 的 `stock` 数据库。

## 初始化数据

```powershell
python scripts/import_existing_csv.py --data-dir data
```

## 启动 Web

Windows PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_web.ps1
powershell -ExecutionPolicy Bypass -File .\stop_web.ps1
```

Linux、macOS 或 Git Bash：

```bash
chmod +x start_web.sh
chmod +x stop_web.sh
./start_web.sh
./stop_web.sh
```

也可以不使用启动脚本，直接启动后端：

```bash
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 6688
```

启动脚本会在后台运行 FastAPI，并把 PID 和日志保存在 `.runtime/`；重复启动不会创建第二个进程。停止脚本只终止 PID 文件记录的服务。后端同时托管已经构建到 `frontend/dist` 的 Vue 生产页面。

- 页面：http://127.0.0.1:6688
- API 文档：http://127.0.0.1:6688/docs

页面中的“任务中心”可以后台执行行情增量采集、预测、正式验证、盘中观察和完整每日流水线，并显示任务进度、日志及失败原因。同一时间只允许一个任务运行，避免重复点击造成并发写入。

前端开发模式：

```powershell
cd frontend
npm run dev
```

Vite 会把 `/api` 转发到本机 6688 端口。

## 兼容命令

原脚本的参数保持不变，只需在路径前增加 `scripts/`：

```powershell
python scripts/market_fetcher.py incremental --output-dir data --list-source sina
python scripts/verify_predictions.py --data-dir data
python scripts/stock_predictor.py --data-dir data --top 30
python scripts/monitor_predictions_intraday.py --data-dir data --source sina
```

每日完整流水线：

```powershell
python scripts/stock_pipeline.py --data-dir data --source sina --top 30
```

只基于本地数据重新验证和预测：

```powershell
python scripts/stock_pipeline.py --data-dir data --skip-collect
```

## 测试

```powershell
python -m pytest backend/tests
npm --prefix frontend run build
```

模型输出是研究候选名单，不是买卖建议。当前历史摘要属于短样本内检验，正式效果应以持续的下一交易日验证为准。

`stock_daily` 使用 `(stock_id, trade_date)` 唯一键并通过 upsert 写入；重复导入同一股票同一交易日不会产生重复行情。
