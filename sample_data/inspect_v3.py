import pandas as pd

print("="*80)
print("COST V3")
print("="*80)
xl = pd.ExcelFile("/app/sample_data/cost_v3.xlsx")
print("Sheets:", xl.sheet_names)
for s in xl.sheet_names:
    df = pd.read_excel("/app/sample_data/cost_v3.xlsx", sheet_name=s)
    print(f"\n-- Sheet '{s}' shape={df.shape} --")
    print("Cols:", list(df.columns))
    print(df.head(5).to_string())

print("\n" + "="*80)
print("LRM + AMZ MAPPING")
print("="*80)
xl2 = pd.ExcelFile("/app/sample_data/lrm_amz_map.xlsx")
print("Sheets:", xl2.sheet_names)
for s in xl2.sheet_names:
    df = pd.read_excel("/app/sample_data/lrm_amz_map.xlsx", sheet_name=s)
    print(f"\n-- Sheet '{s}' shape={df.shape} --")
    print("Cols:", list(df.columns))
    print(df.head(8).to_string())
