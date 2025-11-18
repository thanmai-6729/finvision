from django.shortcuts import render, redirect, HttpResponseRedirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.core.mail import send_mail
from django.conf import settings

from .models import Category, Expense, ExpenseLimit
from userpreferences.models import UserPreference

import datetime
import json
import pandas as pd
import requests

from datetime import date, timedelta  # ✅ FIXED — added timedelta
# 🔹 Add these new imports for the advanced dashboard
from django.apps import apps
from django.utils import timezone

# Helpers from the new utils file
from .utils_dashboard import (
    get_income_model,
    df_from_queryset,
    last_n_months_monthly_series,
    compute_metrics
)

# ---------------------------
# ADVANCED UNIFIED DASHBOARD (PHASE 1 - Backend)
# ---------------------------
@login_required(login_url='/authentication/login')
def advanced_dashboard_view(request):
    """
    Render placeholder template for the advanced dashboard.
    The template will call the JSON endpoints to populate widgets.
    """
    return render(request, "dashboard/advanced_dashboard.html", {})


@login_required(login_url='/authentication/login')
def api_dashboard_summary(request):
    """
    Returns summary numbers and monthly series for charts:
      - total_income, total_expense, net_balance
      - monthly labels and monthly income/expense arrays (last 12 months)
      - category breakdown (last 6 months)
      - advanced metrics (savings_rate, burn_rate, volatility, income_consistency)
    """
    user = request.user
    # Attempt to discover income model
    IncomeModel = get_income_model()
    # Expense model should exist already
    Expense = apps.get_model(app_label=request.resolver_match.app_name or 'expenses', model_name='Expense')
    # safe querysets
    income_qs = IncomeModel.objects.filter(user=user) if IncomeModel is not None else IncomeModel.objects.none() if IncomeModel is not None else []
    expense_qs = Expense.objects.filter(owner=user)

    # Normalize to DataFrames
    income_df = df_from_queryset(list(income_qs.values('id', 'amount', 'date', 'description', 'source') if hasattr(income_qs, 'values') else []),
                                 date_field='date', amount_field='amount', extra_fields=['description', 'source'])
    expense_df = df_from_queryset(list(expense_qs.values('id', 'amount', 'date', 'category', 'description') if hasattr(expense_qs, 'values') else []),
                                  date_field='date', amount_field='amount', extra_fields=['category', 'description'])

    # monthly series
    months, income_monthly = last_n_months_monthly_series(income_df, 'date', 'amount', n_months=12)
    _, expense_monthly = last_n_months_monthly_series(expense_df, 'date', 'amount', n_months=12)

    # category breakdown (last 6 months)
    six_months_ago = timezone.now().date() - timedelta(days=180)
    recent_expenses = expense_qs.filter(date__gte=six_months_ago)
    category_counts = {}
    for c in set(recent_expenses.values_list('category', flat=True)):
        category_counts[c or 'Uncategorized'] = round(float(recent_expenses.filter(category=c).aggregate(total=pd.NamedAgg(column='amount', aggfunc='sum'))['total'] or 0.0), 2)

    # compute advanced metrics
    metrics = compute_metrics(income_df, expense_df)

    payload = {
        'months': months,
        'income_monthly': income_monthly,
        'expense_monthly': expense_monthly,
        'category_breakdown': category_counts,
        'totals': {
            'income': metrics['total_income'],
            'expense': metrics['total_expense'],
            'net_balance': metrics['net_balance']
        },
        'metrics': {
            'savings_rate_pct': metrics['savings_rate_pct'],
            'burn_rate_pct': metrics['burn_rate_pct'],
            'volatility_pct': metrics['volatility_pct'],
            'income_consistency_pct': metrics['income_consistency_pct']
        }
    }
    return JsonResponse(payload, safe=True)


@login_required(login_url='/authentication/login')
def api_dashboard_transactions(request):
    """
    Returns merged recent transactions (income + expense), paginated.
    Query params:
      - page (int)
      - page_size (int)
    """
    user = request.user
    IncomeModel = get_income_model()
    Expense = apps.get_model(app_label=request.resolver_match.app_name or 'expenses', model_name='Expense')

    # Build unified list
    transactions = []
    # incomes
    if IncomeModel is not None:
        # adapt field names common in income models: amount, date, description, source
        income_qs = IncomeModel.objects.filter(user=user).values('id', 'amount', 'date', 'description')  # 'source' optional
        for inc in income_qs:
            transactions.append({
                'id': f"in-{inc.get('id')}",
                'date': inc.get('date').isoformat() if getattr(inc.get('date'), 'isoformat', None) else inc.get('date'),
                'type': 'income',
                'amount': float(inc.get('amount') or 0.0),
                'category_or_source': inc.get('description') or 'Income',
                'description': inc.get('description') or ''
            })
    # expenses
    expense_qs = Expense.objects.filter(owner=user).values('id', 'amount', 'date', 'category', 'description')
    for e in expense_qs:
        transactions.append({
            'id': f"exp-{e.get('id')}",
            'date': e.get('date').isoformat() if getattr(e.get('date'), 'isoformat', None) else e.get('date'),
            'type': 'expense',
            'amount': float(e.get('amount') or 0.0),
            'category_or_source': e.get('category') or 'Expense',
            'description': e.get('description') or ''
        })

    # sort by date desc
    try:
        transactions.sort(key=lambda x: x['date'], reverse=True)
    except Exception:
        # fallback: no-op
        pass

    # pagination
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 20))
    start = (page - 1) * page_size
    end = start + page_size
    paginated = transactions[start:end]

    return JsonResponse({
        'page': page,
        'page_size': page_size,
        'total': len(transactions),
        'transactions': paginated
    }, safe=True)


# ------------------------------------------
# SEARCH EXPENSES
# ------------------------------------------
@login_required(login_url='/authentication/login')
def search_expenses(request):
    if request.method == 'POST':
        search_str = json.loads(request.body).get('searchText')

        expenses = Expense.objects.filter(
            amount__istartswith=search_str, owner=request.user
        ) | Expense.objects.filter(
            date__istartswith=search_str, owner=request.user
        ) | Expense.objects.filter(
            description__icontains=search_str, owner=request.user
        ) | Expense.objects.filter(
            category__icontains=search_str, owner=request.user
        )

        return JsonResponse(list(expenses.values()), safe=False)
    
    
# keep other imports already in your file (Expense etc.)

# Forecast view using Prophet with a fallback
@login_required(login_url='/authentication/login')
def forecast(request):
    user = request.user

    # Fetch expenses for this user and convert to DataFrame
    qs = Expense.objects.filter(owner=user).order_by('date').values('date', 'amount')
    df = pd.DataFrame(list(qs))

    # If no data, show a friendly message and empty chart
    if df.empty:
        context = {
            "history_dates": [],
            "history_values": [],
            "forecast_dates": [],
            "forecast_values": [],
            "predicted_next_month_total": 0,
            "predicted_change_pct": None,
            "warning": "Add some expenses first — not enough data to forecast."
        }
        return render(request, "expenses/forecast.html", context)

    # Prepare daily series (Prophet likes ds,y). Aggregate by date in case of multiple per day
    df['date'] = pd.to_datetime(df['date'])
    daily = df.groupby('date', as_index=False)['amount'].sum().rename(columns={'date':'ds', 'amount':'y'})

    # ensure continuous daily index (fill missing days with 0)
    daily = daily.set_index('ds').asfreq('D', fill_value=0.0).reset_index().rename(columns={'index':'ds'})

    # Forecast horizon (30 days)
    horizon_days = 30
    last_date = daily['ds'].max()
    future_end = last_date + pd.Timedelta(days=horizon_days)

    # Try Prophet first, else fallback to linear trend model
    use_prophet = False
    forecast_df = None
    try:
        # Prophet import
        from prophet import Prophet
        use_prophet = True

        m = Prophet(daily_seasonality=True, yearly_seasonality=True, weekly_seasonality=True)
        m.fit(daily)

        future = m.make_future_dataframe(periods=horizon_days, freq='D')
        forecast = m.predict(future)

        # Keep only the forecast portion (after last_date)
        forecast_df = forecast[['ds', 'yhat']].copy()
        forecast_df.rename(columns={'yhat':'yhat'}, inplace=True)

    except Exception as e:
        # Fallback: simple linear regression on time index
        from sklearn.linear_model import LinearRegression
        import numpy as np

        # create numeric time index
        daily = daily.copy()
        daily['t'] = (daily['ds'] - daily['ds'].min()).dt.days
        X = daily[['t']].values
        y = daily['y'].values

        model = LinearRegression()
        model.fit(X, y)

        future_t = np.arange(daily['t'].max() + 1, daily['t'].max() + 1 + horizon_days).reshape(-1, 1)
        future_dates = [daily['ds'].max() + pd.Timedelta(days=i) for i in range(1, horizon_days + 1)]
        preds = model.predict(future_t)

        forecast_df = pd.DataFrame({'ds': future_dates, 'yhat': preds})

    # Compose output arrays for charts: history (last N days) and forecast
    # We'll show last 90 days history to make chart readable
    history_window_days = 90
    hist_start = max(daily['ds'].min(), daily['ds'].max() - pd.Timedelta(days=history_window_days))
    history_df = daily[daily['ds'] >= hist_start].copy()

    history_dates = history_df['ds'].dt.strftime('%Y-%m-%d').tolist()
    history_values = history_df['y'].astype(float).round(2).tolist()

    forecast_dates = forecast_df[forecast_df['ds'] > history_df['ds'].max()]['ds'].dt.strftime('%Y-%m-%d').tolist()
    forecast_values = forecast_df[forecast_df['ds'] > history_df['ds'].max()]['yhat'].astype(float).round(2).tolist()

    # Predicted next-month total: sum forecast for next 30 days
    predicted_next_month_total = float(forecast_df[forecast_df['ds'] > last_date]['yhat'].sum())

    # Compute last completed month's total to compare
    today = datetime.date.today()
    first_of_this_month = today.replace(day=1)
    last_month_end = first_of_this_month - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    last_month_total = Expense.objects.filter(
        owner=user,
        date__gte=last_month_start,
        date__lte=last_month_end
    ).aggregate(total=pd.NamedAgg(column='amount', aggfunc='sum'))['total'] or 0

    predicted_change_pct = None
    if last_month_total and last_month_total > 0:
        predicted_change_pct = ((predicted_next_month_total - last_month_total) / last_month_total) * 100

    # Round numbers for display
    predicted_next_month_total = round(predicted_next_month_total, 2)
    if predicted_change_pct is not None:
        predicted_change_pct = round(predicted_change_pct, 1)

    context = {
        "history_dates": json.dumps(history_dates),
        "history_values": json.dumps(history_values),
        "forecast_dates": json.dumps(forecast_dates),
        "forecast_values": json.dumps(forecast_values),
        "predicted_next_month_total": predicted_next_month_total,
        "predicted_change_pct": predicted_change_pct,
        "prophet_used": use_prophet,
        "warning": None
    }

    return render(request, "expenses/forecast.html", context)



# ------------------------------------------
# EXPENSE LIST PAGE
# ------------------------------------------
@login_required(login_url='/authentication/login')
def index(request):
    categories = Category.objects.all()
    expenses = Expense.objects.filter(owner=request.user)

    sort_order = request.GET.get('sort')

    if sort_order == 'amount_asc':
        expenses = expenses.order_by('amount')
    elif sort_order == 'amount_desc':
        expenses = expenses.order_by('-amount')
    elif sort_order == 'date_asc':
        expenses = expenses.order_by('date')
    elif sort_order == 'date_desc':
        expenses = expenses.order_by('-date')

    paginator = Paginator(expenses, 5)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    try:
        currency = UserPreference.objects.get(user=request.user).currency
    except:
        currency = None

    context = {
        'expenses': expenses,
        'page_obj': page_obj,
        'currency': currency,
        'total': page_obj.paginator.num_pages,
        'sort_order': sort_order,
    }

    return render(request, 'expenses/index.html', context)


# ------------------------------------------
# HELPER — TOTAL OF TODAY
# ------------------------------------------
def get_expense_of_day(user):
    today = date.today()
    expenses = Expense.objects.filter(owner=user, date=today)
    return sum(exp.amount for exp in expenses)


# ------------------------------------------
# ADD EXPENSE
# ------------------------------------------
@login_required(login_url='/authentication/login')
def add_expense(request):
    categories = Category.objects.all()

    if request.method == 'GET':
        return render(request, 'expenses/add_expense.html', {
            'categories': categories,
            'values': request.POST
        })

    if request.method == 'POST':
        amount = request.POST.get('amount')
        date_str = request.POST.get('expense_date')
        description = request.POST.get('description')
        predicted_category = request.POST.get('category')

        if not amount:
            messages.error(request, 'Amount is required')
            return redirect('add-expense')

        if not description:
            messages.error(request, 'Description is required')
            return redirect('add-expense')

        try:
            date_parsed = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()

            if date_parsed > datetime.date.today():
                messages.error(request, 'Date cannot be in the future')
                return redirect('add-expense')

        except ValueError:
            messages.error(request, 'Invalid date format')
            return redirect('add-expense')

        # DAILY LIMIT CHECK
        user = request.user
        expense_limit = ExpenseLimit.objects.filter(owner=user).first()
        limit_value = expense_limit.daily_expense_limit if expense_limit else 5000

        total_today = get_expense_of_day(user) + float(amount)

        if total_today > limit_value:
            subject = "Daily Expense Limit Exceeded"
            message = f"Hello {user.username},\n\nYour spending today exceeded your daily limit."
            send_mail(subject, message, settings.EMAIL_HOST_USER, [user.email])

            messages.warning(request, "Warning: You exceeded your daily limit!")

        # SAVE EXPENSE
        Expense.objects.create(
            owner=user,
            amount=amount,
            date=date_parsed,
            category=predicted_category,
            description=description
        )

        messages.success(request, 'Expense added successfully!')
        return redirect('expenses')


# ------------------------------------------
# EDIT EXPENSE
# ------------------------------------------
@login_required(login_url='/authentication/login')
def expense_edit(request, id):
    expense = Expense.objects.get(pk=id)
    categories = Category.objects.all()

    if request.method == "GET":
        return render(request, 'expenses/edit-expense.html', {
            'expense': expense,
            'categories': categories
        })

    amount = request.POST.get('amount')
    date_str = request.POST.get('expense_date')
    description = request.POST.get('description')
    category = request.POST.get('category')

    if not amount or not description:
        messages.error(request, "All fields are required.")
        return redirect('expense-edit', id=id)

    try:
        date_parsed = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        if date_parsed > datetime.date.today():
            messages.error(request, "Date cannot be in the future.")
            return redirect('expense-edit', id=id)
    except:
        messages.error(request, "Invalid date format.")
        return redirect('expense-edit', id=id)

    expense.amount = amount
    expense.date = date_parsed
    expense.category = category
    expense.description = description
    expense.save()

    messages.success(request, "Expense updated successfully.")
    return redirect('expenses')


# ------------------------------------------
# DELETE EXPENSE
# ------------------------------------------
@login_required(login_url='/authentication/login')
def delete_expense(request, id):
    Expense.objects.get(pk=id).delete()
    messages.success(request, 'Expense removed')
    return redirect('expenses')


# ------------------------------------------
# CATEGORY SUMMARY API
# ------------------------------------------
@login_required(login_url='/authentication/login')
def expense_category_summary(request):
    today = datetime.date.today()
    six_months_ago = today - datetime.timedelta(days=180)

    expenses = Expense.objects.filter(
        owner=request.user,
        date__gte=six_months_ago,
        date__lte=today
    )

    final = {}
    for cat in set(exp.category for exp in expenses):
        final[cat] = sum(exp.amount for exp in expenses.filter(category=cat))

    return JsonResponse({'expense_category_data': final})


# ------------------------------------------
# DAILY LIMIT SETTER
# ------------------------------------------
@login_required(login_url='/authentication/login')
def set_expense_limit(request):
    if request.method == "POST":
        limit = request.POST.get('daily_expense_limit')
        obj = ExpenseLimit.objects.filter(owner=request.user).first()

        if obj:
            obj.daily_expense_limit = limit
            obj.save()
        else:
            ExpenseLimit.objects.create(owner=request.user, daily_expense_limit=limit)

        messages.success(request, "Limit updated successfully!")
        return HttpResponseRedirect('/preferences/')

    return HttpResponseRedirect('/preferences/')


# ------------------------------------------
# DASHBOARD — WITH AI INSIGHTS
# ------------------------------------------
from .utils import generate_insights, generate_suggestions

@login_required(login_url='/authentication/login')
def dashboard(request):
    user = request.user

    expenses = Expense.objects.filter(owner=user).order_by('-date')
    df = pd.DataFrame(list(expenses.values('amount', 'date', 'category')))

    if df.empty:
        df = pd.DataFrame(columns=['amount', 'date', 'category'])

    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df['amount'] = pd.to_numeric(df['amount'], errors='coerce')

    total_expenses = df['amount'].sum()
    current_month = datetime.date.today().month
    monthly_expense = df[df['date'].dt.month == current_month]['amount'].sum()

    category_summary = df.groupby('category')['amount'].sum().to_dict() if not df.empty else {}
    df['week'] = df['date'].dt.isocalendar().week
    weekly_expense = df.groupby('week')['amount'].sum().to_dict() if not df.empty else {}

    insights = generate_insights(user)
    suggestions = generate_suggestions(user)

    context = {
        "total_expenses": total_expenses,
        "monthly_expense": monthly_expense,
        "category_summary": category_summary,
        "weekly_expense": weekly_expense,
        "insights": insights,
        "suggestions": suggestions,
    }

    return render(request, "dashboard/dashboard.html", context)
