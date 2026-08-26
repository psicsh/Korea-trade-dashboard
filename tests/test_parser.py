import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("u",ROOT/"scripts"/"update_motir.py")
u=importlib.util.module_from_spec(spec); spec.loader.exec_module(u)

def test_period():
    assert u.period_from_title("2026년 7월 수출입 동향")=="2026-07"
    assert u.period_from_title("2026년 6월 및 상반기 수출입 동향")=="2026-06"
    assert u.period_from_title("2026년 7월 정보통신산업(ICT) 수출입 동향") is None

def test_narrative_metric():
    t="반도체 수출(410.1억 달러, +178.8%)은 증가했다."
    assert u.find_metric(t,"반도체")== (410.1,178.8)
    t2="가전 수출(6.1억 달러, -4.1%)은 감소했다."
    assert u.find_metric(t2,"가전")== (6.1,-4.1)

def test_region():
    t="대(對)중국 수출(216.8억 달러, +96.2%)은 증가했다."
    assert u.find_region(t,"중국")== (216.8,96.2)
