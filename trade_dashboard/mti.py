from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .utils import safe_hs_text


def load_major_codes(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str).fillna("")
    required = {"industry_code", "industry_name", "mti_prefixes", "display_order"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"20대 품목 파일에 필수 열이 없습니다: {sorted(missing)}")
    frame["display_order"] = pd.to_numeric(frame["display_order"], errors="raise").astype(int)
    return frame.sort_values("display_order").reset_index(drop=True)


def _normalise_header(value: object) -> str:
    return re.sub(r"[^A-Z0-9가-힣]", "", str(value or "").upper())


def _find_columns(columns: list[object]) -> tuple[object, object, object | None, object | None]:
    normal = {column: _normalise_header(column) for column in columns}
    hsk = next(
        (
            column
            for column, name in normal.items()
            if name in {"HSK", "HSK10", "HS코드", "HS부호", "세번", "세번부호"} or "HSK" in name
        ),
        None,
    )
    mti = next((column for column, name in normal.items() if name in {"MTI", "MTI6", "MTI코드"} or "MTI" in name), None)
    hsk_name = next(
        (column for column, name in normal.items() if name in {"HSKNAMEKO", "HSK품명", "HS품명", "품목명"}), None
    )
    mti_name = next((column for column, name in normal.items() if name in {"MTINAMEKO", "MTI품명", "MTI명"}), None)
    if hsk is None or mti is None:
        raise ValueError("HSK 열과 MTI 열을 찾을 수 없습니다.")
    return hsk, mti, hsk_name, mti_name


def _read_mapping_sheet(path: Path, sheet_name: str) -> pd.DataFrame | None:
    preview = pd.read_excel(path, sheet_name=sheet_name, header=None, nrows=40, dtype=str)
    header_row = None
    for index, row in preview.iterrows():
        names = [_normalise_header(value) for value in row.tolist()]
        if any("HSK" in name or name in {"HS코드", "HS부호", "세번", "세번부호"} for name in names) and any(
            "MTI" in name for name in names
        ):
            header_row = int(index)
            break
    if header_row is None:
        return None
    frame = pd.read_excel(path, sheet_name=sheet_name, header=header_row, dtype=str)
    try:
        hsk, mti, hsk_name, mti_name = _find_columns(list(frame.columns))
    except ValueError:
        return None
    mti_values = (
        frame[mti]
        .fillna("")
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.replace(r"\D", "", regex=True)
        .str.zfill(6)
    )
    result = pd.DataFrame(
        {
            "hsk10": frame[hsk].map(safe_hs_text),
            "mti_code": mti_values,
            "hsk_name": frame[hsk_name].fillna("").astype(str) if hsk_name is not None else "",
            "mti_name": frame[mti_name].fillna("").astype(str) if mti_name is not None else "",
        }
    )
    result = result[(result["hsk10"].str.len() == 10) & result["mti_code"].str.fullmatch(r"\d{6}")]
    return result.drop_duplicates("hsk10", keep="last").reset_index(drop=True)


def load_mti_mapping(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"MTI-HSK 연계표가 없습니다: {path}")
    workbook = pd.ExcelFile(path)
    frames = []
    for sheet in workbook.sheet_names:
        parsed = _read_mapping_sheet(path, sheet)
        if parsed is not None and not parsed.empty:
            frames.append(parsed)
    if not frames:
        raise ValueError("MTI-HSK 연계표에 유효한 매핑 행이 없습니다. 공식 2026 연계표로 교체해 주세요.")
    return pd.concat(frames, ignore_index=True).drop_duplicates("hsk10", keep="last")


def _industry_for_mti(mti_code: str, major: pd.DataFrame) -> tuple[str, str] | None:
    for row in major.itertuples(index=False):
        prefixes = [prefix.strip() for prefix in str(row.mti_prefixes).split("|") if prefix.strip()]
        if any(str(mti_code).startswith(prefix) for prefix in prefixes):
            return str(row.industry_code), str(row.industry_name)
    return None


def aggregate_industries(
    hs_rows: pd.DataFrame,
    mapping: pd.DataFrame,
    major: pd.DataFrame,
    *,
    minimum_mapping_ratio: float = 0.90,
) -> pd.DataFrame:
    columns = [
        "period",
        "industry_code",
        "industry_name",
        "export_usd",
        "import_usd",
        "balance_usd",
        "source",
    ]
    if hs_rows.empty:
        return pd.DataFrame(columns=columns)
    data = hs_rows.copy()
    data["hsk10"] = data["hs_code"].map(safe_hs_text)
    data = data[data["hsk10"].str.len() == 10]
    joined = data.merge(mapping[["hsk10", "mti_code"]], how="left", on="hsk10")
    value = joined["export_usd"].abs() + joined["import_usd"].abs()
    denominator = float(value.sum())
    ratio = 1.0 if denominator == 0 else float(value[joined["mti_code"].notna()].sum() / denominator)
    if ratio < minimum_mapping_ratio:
        raise ValueError(f"MTI-HSK 매핑 금액 비율이 {ratio:.1%}로 너무 낮습니다. 연계표 연도를 확인해 주세요.")
    joined = joined[joined["mti_code"].notna()].copy()
    industry = joined["mti_code"].map(lambda code: _industry_for_mti(str(code), major))
    joined["industry_code"] = industry.map(lambda value: value[0] if value else None)
    joined["industry_name"] = industry.map(lambda value: value[1] if value else None)
    selected = joined[joined["industry_code"].notna()].copy()
    if selected.empty:
        return pd.DataFrame(columns=columns)
    result = selected.groupby(["period", "industry_code", "industry_name"], as_index=False)[
        ["export_usd", "import_usd"]
    ].sum()
    result["balance_usd"] = result["export_usd"] - result["import_usd"]
    result["source"] = "관세청 HSK 실적·2026 MTI-HSK 연계 집계"
    return result[columns].sort_values(["period", "industry_code"]).reset_index(drop=True)


def related_major_industries(hs_code: str, mapping: pd.DataFrame, major: pd.DataFrame) -> list[str]:
    code = re.sub(r"\D", "", hs_code)
    if len(code) not in {2, 4, 6}:
        return []
    matched = mapping[mapping["hsk10"].str.startswith(code)]
    names: list[str] = []
    for mti_code in matched["mti_code"].dropna().astype(str).unique():
        industry = _industry_for_mti(mti_code, major)
        if industry and industry[1] not in names:
            names.append(industry[1])
    return names
