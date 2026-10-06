import pandas as pd

df = pd.read_csv("analytics/patient_data_messy.csv")


# 1. Mixed Casing
print("\nProblem 1: Mixed Casing")
cols = ["patient_name", "city", "department",
        "insurance_company", "claim_status"]

for col in cols:
    df[col] = df[col].str.title()

print("Mixed casing fixed successfully.")


# 2. Leading/Trailing Spaces
print("\nProblem 2: Leading/Trailing Spaces")
cols = ["patient_name", "city", "insurance_company", "claim_status"]

for col in cols:
    df[col] = df[col].str.strip()

print("Leading and trailing spaces removed successfully.")


# 3. Missing Values
print("\nProblem 3: Missing Values")

print("Missing values before cleaning:")
print(df[["bill_amount", "phone_number", "age"]].isnull().sum())

df["bill_amount"] = df["bill_amount"].fillna(df["bill_amount"].median())
df["age"] = df["age"].fillna(df["age"].median())
df["phone_number"] = df["phone_number"].fillna("Unknown")

print("Missing values handled successfully.")


# 4. Dates as Text
print("\nProblem 4: Dates as Text")

df["admission_date"] = pd.to_datetime(
    df["admission_date"],
    errors="coerce",
    dayfirst=True
)

print("Admission dates converted successfully.")


# 5. Duplicate Rows
print("\nProblem 5: Duplicate Rows")

print("Duplicate rows found:", df.duplicated().sum())

df = df.drop_duplicates()

print("Duplicate rows removed successfully.")


# 6. Text Correction
print("\nProblem 6: Insurance Company Text")

df["insurance_company"] = df["insurance_company"].str.replace(
    "hdfc ergo", "HDFC Ergo", case=False, regex=False
)

print("Insurance company names corrected successfully.")


print("\nData cleaning completed successfully!")