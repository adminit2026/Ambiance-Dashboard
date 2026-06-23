import pandas as pd
fn = "/app/sample_data/poexport_may.xls"
try:
    xl = pd.ExcelFile(fn, engine="xlrd")
except Exception as e:
    print("xlrd err:", e)
    xl = pd.ExcelFile(fn)
print("Sheets:", xl.sheet_names)
for s in xl.sheet_names:
    df = pd.read_excel(fn, sheet_name=s)
    print(f"\n=== Sheet '{s}' shape={df.shape} ===")
    print("Cols:", list(df.columns))
    print(df.head(5).to_string())
    if "Order date" in df.columns or "PO" in df.columns:
        # filter Leroy Merlin or ship-to?
        for col in df.columns:
            if df[col].dtype == object:
                vals = df[col].dropna().astype(str).unique()
                if any("leroy" in v.lower() for v in vals[:200]):
                    print(f"  Found 'leroy' in column: {col}, values: {[v for v in vals if 'leroy' in v.lower()][:5]}")
    print("\nUnique values in first 5 columns:")
    for col in df.columns[:8]:
        try:
            print(f"  {col}: {df[col].dropna().astype(str).unique()[:8]}")
        except Exception:
            pass
