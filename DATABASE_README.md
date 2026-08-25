# MySQL 数据库使用

默认连接本机 `127.0.0.1:3306` 的 `stock` 数据库。连接参数通过环境变量覆盖：
`STOCK_DB_HOST`、`STOCK_DB_PORT`、`STOCK_DB_USER`、`STOCK_DB_PASSWORD`、`STOCK_DB_NAME`。

首次导入或重新同步现有文件：

```powershell
python scripts/import_existing_csv.py --data-dir data
```

交易日收盘后的完整流程（增量采集、验证上一期、生成新预测并同步数据库）：

```powershell
python scripts/stock_pipeline.py --data-dir data --source sina --top 30
```

只重新执行验证和预测、不联网采集：

```powershell
python scripts/stock_pipeline.py --data-dir data --skip-collect
```

CSV 文件仍会保留，作为原始文件和故障恢复依据。数据库使用唯一键执行幂等导入，可安全重复运行。
