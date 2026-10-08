import pandas as pd
from backend.app.predictors.limit_up import is_main_board,limit_price

def test_limit_price_uses_half_up_rounding():
    assert limit_price(10.05)==11.06

def test_main_board_scope_excludes_growth_star_and_bj():
    values=pd.Series(["600000","002001","300001","688001","830001"])
    assert is_main_board(values).tolist()==[True,True,False,False,False]

def test_limit_touch_uses_price_tolerance():
    assert 11.055 >= limit_price(10.05)-0.005
