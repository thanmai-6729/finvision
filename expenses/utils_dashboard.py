# expenses/utils_dashboard.py
from django.apps import apps
import pandas as pd
from datetime import date, timedelta
import math

def get_income_model():
    """
    Attempt to find an Income model in installed apps.
    Common names: UserIncome, Income, Incomes
    Returns model class or None.
    """
    candidate_names = ['UserIncome', 'Income', 'Incomes']
    for name in candidate_names:
        try:
            # search across apps
            for model in apps.get_models():
                if model.__name__.lower() == name.lower():
                    return model
        except Exception:
            continue
    # fallback: return the first model with 'income' in its name
    for model in apps.get_models():
        if 'income' in model.__name__.lower():
            return model
    return None


def df_from_queryset(qs, date_field='date', amount_field='amount', extra_fields=None):
    """
    Convert a queryset (values or model instances) to a pandas DataFrame with standardized columns.
    - extra_fields: list of other field names to keep (e.g., 'category', 'description')
    """
    extra_fields = extra_fields or []
    # If qs already values() (list of dicts)
    try:
        data = list(qs)
    except Exception:
        data = []
    if not data:
        # empty df with required columns
        cols = [date_field, amount_field] + extra_fields
        return pd.DataFrame(columns=cols)

    # If first item is dict — values() used
    if isinstance(data[0], dict):
        df = pd.DataFrame(data)
    else:
        # model instances -> build dicts
        rows = []
        for obj in data:
            row = {}
            row[date_field] = getattr(obj, date_field, None)
            row[amount_field] = getattr(obj, amount_field, None)
            for f in extra_fields:
                row[f] = getattr(obj, f, None)
            rows.append(row)
        df = pd.DataFrame(rows)

    # Normalize columns
    if date_field in df.columns:
        df[date_field] = pd.to_datetime(df[date_field], errors='coerce')
    else:
        df[date_field] = pd.NaT

    if amount_field in df.columns:
        df[amount_field] = pd.to_numeric(df[amount_field], errors='coerce').fillna(0.0)
    else:
        df[amount_field] = 0.0

    return df


def last_n_months_monthly_series(df, date_col='date', value_col='amount', n_months=12):
    """
    Return list of month labels (YYYY-MM) and monthly sums for last n_months (including current month).
    """
    if df.empty:
        # build list of months ending this month with zeros
        end = pd.to_datetime(date.today()).replace(day=1) + pd.offsets.MonthEnd(0)
        months = [(end - pd.DateOffset(months=i)).strftime('%Y-%m') for i in reversed(range(n_months))]
        return months, [0.0]*n_months

    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
    # floor to month start
    df['month'] = df[date_col].dt.to_period('M').dt.to_timestamp()
    # compute last n months range
    last_month = pd.to_datetime(date.today()).replace(day=1)
    months = [(last_month - pd.DateOffset(months=i)).strftime('%Y-%m') for i in reversed(range(n_months))]
    # aggregate
    agg = df.groupby(df['month'].dt.strftime('%Y-%m'))[value_col].sum().to_dict()
    vals = [round(float(agg.get(m, 0.0)), 2) for m in months]
    return months, vals


def compute_metrics(income_df, expense_df):
    """
    Compute advanced metrics:
      - total_income, total_expense, net_balance
      - savings_rate (%) = (income - expense) / income * 100 (if income > 0)
      - burn_rate (%) = expense / income * 100 (if income > 0)
      - volatility (%) = coefficient of variation of monthly expenses (std/mean) * 100
      - income_consistency (%) = (1 - cv(income_monthly)) * 100 (bounded 0-100)
    """
    total_income = round(float(income_df['amount'].sum()) if not income_df.empty else 0.0, 2)
    total_expense = round(float(expense_df['amount'].sum()) if not expense_df.empty else 0.0, 2)
    net_balance = round(total_income - total_expense, 2)

    # Monthly series (12 months) for volatility and consistency
    _, income_monthly = last_n_months_monthly_series(income_df, 'date', 'amount', n_months=12)
    _, expense_monthly = last_n_months_monthly_series(expense_df, 'date', 'amount', n_months=12)

    import numpy as np
    income_arr = np.array(income_monthly, dtype=float)
    expense_arr = np.array(expense_monthly, dtype=float)

    def coef_var(arr):
        if arr.size == 0 or np.nanmean(arr) == 0:
            return None
        return float(np.nanstd(arr, ddof=0) / (np.nanmean(arr) if np.nanmean(arr) != 0 else float('nan')))

    income_cv = coef_var(income_arr)
    expense_cv = coef_var(expense_arr)

    volatility_pct = None
    if expense_cv is not None:
        volatility_pct = round(float(expense_cv * 100), 2)

    income_consistency_pct = None
    if income_cv is not None:
        # consistency = (1 - cv) bounded 0..1 then *100
        consistency = max(0.0, 1.0 - income_cv)
        income_consistency_pct = round(float(consistency * 100), 1)

    savings_rate = None
    burn_rate = None
    if total_income > 0:
        savings_rate = round(((total_income - total_expense) / total_income) * 100, 2)
        burn_rate = round((total_expense / total_income) * 100, 2)

    return {
        'total_income': total_income,
        'total_expense': total_expense,
        'net_balance': net_balance,
        'savings_rate_pct': savings_rate,
        'burn_rate_pct': burn_rate,
        'volatility_pct': volatility_pct,
        'income_consistency_pct': income_consistency_pct,
        'income_monthly': income_monthly,
        'expense_monthly': expense_monthly
    }
