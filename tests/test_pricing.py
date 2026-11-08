from app import quote

def test_partial_days():
    result=quote('2026-11-10T18:00:00+07:00','2026-11-12T06:00:00+07:00',100000000,'0.11')
    assert result['hours']=='36'
    assert len(result['lines'])==3
    assert abs(result['subtotal']-5000000)<=1

def test_month_boundary():
    result=quote('2026-11-29T00:00:00+07:00','2026-12-03T00:00:00+07:00',100000000,'0.11')
    assert len(result['lines'])==4
    assert abs(result['subtotal']-13118280)<=2
