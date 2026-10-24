from logstat import parse_line, summarise


def test_parse_line():
    r = parse_line(open("sample.log").readline())
    assert r["ip"] == "10.0.0.1"
    assert r["status"] == 200
    assert r["path"] == "/"


def test_summarise_sample():
    s = summarise(open("sample.log"))
    assert s["requests"] == 6
    assert s["unique_ips"] == 4
