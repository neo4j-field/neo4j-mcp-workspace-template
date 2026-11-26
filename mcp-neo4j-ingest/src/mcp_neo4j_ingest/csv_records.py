"""Convert pandas missing sentinels into native null query parameters."""
import pandas as pd


def read_csv_records(path):
    frame = pd.read_csv(path)
    # Object dtype is necessary: numeric columns otherwise coerce None back to NaN.
    return frame.astype(object).where(pd.notna(frame), None).to_dict(orient='records')
