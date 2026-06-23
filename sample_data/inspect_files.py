import pandas as pd

print("=" * 80)
print("CHANNELENGINE CSV")
print("=" * 80)
try:
    df = pd.read_csv("/app/sample_data/channelengine.csv", sep=";", nrows=5)
    print("Shape:", df.shape, "Columns:", list(df.columns))
    print(df.head(2).to_string())
except Exception as e:
    print("semicolon failed:", e)
    df = pd.read_csv("/app/sample_data/channelengine.csv", nrows=5)
    print("Shape:", df.shape, "Columns:", list(df.columns))
    print(df.head(2).to_string())

print("\n" + "=" * 80)
print("BEEZUP XLSX")
print("=" * 80)
xl = pd.ExcelFile("/app/sample_data/beezup.xlsx")
print("Sheets:", xl.sheet_names)
for s in xl.sheet_names[:3]:
    df = pd.read_excel("/app/sample_data/beezup.xlsx", sheet_name=s, nrows=3)
    print(f"\n-- Sheet: {s} -- Shape: {df.shape}")
    print("Cols:", list(df.columns))
    print(df.head(2).to_string())

print("\n" + "=" * 80)
print("AMAZON PO XLS")
print("=" * 80)
try:
    df = pd.read_excel("/app/sample_data/amazon_po.xls", nrows=5, engine="xlrd")
    print("Shape:", df.shape, "Cols:", list(df.columns))
    print(df.head(2).to_string())
except Exception as e:
    print("xlrd failed:", e)
    # Maybe it's html or csv
    with open("/app/sample_data/amazon_po.xls", "rb") as f:
        head = f.read(500)
    print("Head bytes:", head[:200])

print("\n" + "=" * 80)
print("COST PRODUCTION XLSX")
print("=" * 80)
xl = pd.ExcelFile("/app/sample_data/cost_prod.xlsx")
print("Sheets:", xl.sheet_names)
for s in xl.sheet_names[:5]:
    df = pd.read_excel("/app/sample_data/cost_prod.xlsx", sheet_name=s, nrows=5)
    print(f"\n-- Sheet: {s} -- Shape: {df.shape}")
    print("Cols:", list(df.columns))
    print(df.head(3).to_string())
