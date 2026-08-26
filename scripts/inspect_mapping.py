from pathlib import Path
import pandas as pd, re

p = Path(__file__).resolve().parents[1] / "data" / "mti_hsk_mapping.xlsx"
if not p.exists():
    raise SystemExit("data/mti_hsk_mapping.xlsx 가 없습니다.")

xls = pd.ExcelFile(p)
print("sheets:", xls.sheet_names)
for sheet in xls.sheet_names:
    raw = pd.read_excel(p, sheet_name=sheet, header=None, dtype=str)
    print("\n---", sheet, raw.shape, "---")
    for r in range(min(15, len(raw))):
        vals = [str(x) if pd.notna(x) else "" for x in raw.iloc[r].tolist()]
        joined = " | ".join(vals)
        if "MTI" in joined.upper() or "HSK" in joined.upper() or re.search(r"\bHS\b", joined.upper()):
            print(r, joined[:500])
