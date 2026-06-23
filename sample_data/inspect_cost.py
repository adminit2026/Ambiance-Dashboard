import pandas as pd
fn = "/app/sample_data/cost_prod.xlsx"
xl = pd.ExcelFile(fn)
print("Sheets:", xl.sheet_names)
for s in xl.sheet_names:
    df = pd.read_excel(fn, sheet_name=s, header=None)
    print(f"\n=== Sheet '{s}' shape={df.shape} ===")
    # Print first 8 rows, first 14 columns
    print(df.iloc[:8, :14].to_string())
    # Find what's in column L (index 11)
    if df.shape[1] > 11:
        col_l = df.iloc[:, 11]
        print(f"\nColumn L (idx 11) — first 10 non-null values: {col_l.dropna().head(10).tolist()}")
        print(f"Column L (idx 11) — header (rows 0-3): {df.iloc[:4, 11].tolist()}")
