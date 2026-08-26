import pandas as pd
import pytest

from backend.app.predictors.multi_factor import add_features


def test_tradeable_return_uses_next_open_to_following_open():
    frame=pd.DataFrame({
        "股票代码":["000001"]*3,"日期":pd.to_datetime(["2026-08-24","2026-08-25","2026-08-26"]),
        "开盘":[10.0,11.0,12.1],"收盘":[10.5,11.5,12.0],"最高":[10.6,11.6,12.2],"最低":[9.9,10.9,11.9],
        "成交量":[100,100,100],"成交额":[1000,1100,1200],"名称":["测试"]*3,
    })
    featured=add_features(frame)
    assert featured.loc[0,"next_return"] == pytest.approx(11.5/10.5-1)
    assert featured.loc[0,"tradeable_return"] == pytest.approx(12.1/11.0-1)
    assert pd.isna(featured.loc[1,"tradeable_return"])
