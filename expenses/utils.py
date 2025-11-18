from collections import defaultdict
from datetime import datetime, timedelta
from django.db.models import Sum
from expenses.models import Expense


# -------------------------------------------------------------
#  AI INSIGHTS — HIGH LEVEL PATTERNS
# -------------------------------------------------------------
def generate_insights(user):
    """
    Generates AI-style financial insights for the logged-in user.
    Uses actual database expenses.
    """

    insights = []

    # Fetch all user expenses
    expenses = Expense.objects.filter(owner=user).order_by("date")

    if not expenses.exists():
        return ["Start adding expenses to receive smart insights!"]

    # -----------------------------------------------------------
    # 1. Month-over-Month Spending Change
    # -----------------------------------------------------------
    monthly_totals = defaultdict(float)

    for e in expenses:
        month_key = e.date.strftime("%Y-%m")
        monthly_totals[month_key] += float(e.amount)

    months = sorted(monthly_totals.keys())

    for i in range(1, len(months)):
        prev, curr = monthly_totals[months[i-1]], monthly_totals[months[i]]
        if prev > 0:
            change = ((curr - prev) / prev) * 100
            if change > 20:
                insights.append(
                    f"⚠️ Spending increased by {change:.1f}% in {months[i]} compared to {months[i-1]}."
                )
            elif change < -20:
                insights.append(
                    f"✅ Spending decreased by {abs(change):.1f}% in {months[i]} compared to {months[i-1]}."
                )

    # -----------------------------------------------------------
    # 2. Top Spending Category
    # -----------------------------------------------------------
    category_totals = defaultdict(float)

    for e in expenses:
        category_totals[e.category] += float(e.amount)

    if category_totals:
        top_cat, top_val = max(category_totals.items(), key=lambda x: x[1])
        insights.append(f"📌 Highest spending category: **{top_cat}** (₹{top_val:.2f}).")

    # -----------------------------------------------------------
    # 3. Week Summary
    # -----------------------------------------------------------
    today = datetime.today().date()
    week_ago = today - timedelta(days=7)

    last_week_total = (
        Expense.objects.filter(owner=user, date__gte=week_ago)
        .aggregate(Sum("amount"))["amount__sum"]
        or 0
    )

    if last_week_total > 0:
        insights.append(f"📅 In the last 7 days, you spent ₹{last_week_total:.2f}.")

    # -----------------------------------------------------------
    # 4. Monthly Trend Indicator
    # -----------------------------------------------------------
    if len(months) >= 2:
        if monthly_totals[months[-1]] > monthly_totals[months[-2]]:
            insights.append("🔺 Your monthly expenses are rising. Consider reviewing spending habits.")
        else:
            insights.append("🟢 Good job! You're spending less than last month.")

    # -----------------------------------------------------------
    # 5. Motivation Tip
    # -----------------------------------------------------------
    insights.append("💡 Tip: Consistent tracking helps with better financial control.")

    return insights


# -------------------------------------------------------------
#  SMART SUGGESTIONS (JARVIS-LIKE)
# -------------------------------------------------------------
def generate_suggestions(user):
    """
    Produce short actionable suggestions based on recent spending.
    Returns a list of objects:
    { "message": "...", "level": "info"|"warning"|"critical", "detail": "..."}
    """

    suggestions = []

    today = datetime.today().date()
    window_start = today - timedelta(days=90)

    qs = Expense.objects.filter(owner=user, date__gte=window_start).order_by("date")

    if not qs.exists():
        suggestions.append({
            "message": "Add a few expenses to unlock personalized smart suggestions.",
            "level": "info",
            "detail": ""
        })
        return suggestions

    # ----------------------------------------------------------
    # DAILY SPEND AVERAGE
    # ----------------------------------------------------------
    daily_totals = defaultdict(float)

    for e in qs:
        day_key = e.date.strftime("%Y-%m-%d")
        daily_totals[day_key] += float(e.amount)

    days = len(daily_totals.keys()) or 1
    avg_daily = sum(daily_totals.values()) / days
    projected_month = avg_daily * 30

    suggestions.append({
        "message": f"Average daily spend ₹{avg_daily:.0f}. Projected monthly spend ₹{projected_month:.0f}.",
        "level": "info",
        "detail": "Try setting a monthly budget to stay below this projection."
    })

    # ----------------------------------------------------------
    # MONTHLY SPIKE DETECTION (last 30 vs previous 30 days)
    # ----------------------------------------------------------
    last_30 = today - timedelta(days=30)
    prev_30 = today - timedelta(days=60)

    last_30_total = (
        Expense.objects.filter(owner=user, date__gte=last_30)
        .aggregate(Sum("amount"))["amount__sum"]
        or 0
    )

    prev_30_total = (
        Expense.objects.filter(owner=user, date__range=[prev_30, last_30 - timedelta(days=1)])
        .aggregate(Sum("amount"))["amount__sum"]
        or 0
    )

    if prev_30_total > 0:
        pct_change = ((last_30_total - prev_30_total) / prev_30_total) * 100
    else:
        pct_change = 100 if last_30_total > 0 else 0

    if pct_change >= 30:
        suggestions.append({
            "message": f"Spending increased by {pct_change:.0f}% in the last 30 days.",
            "level": "critical",
            "detail": "Review high-value purchases or new recurring costs."
        })
    elif pct_change >= 10:
        suggestions.append({
            "message": f"Spending increased by {pct_change:.0f}% this month.",
            "level": "warning",
            "detail": "Keep an eye on unnecessary expenses."
        })
    else:
        suggestions.append({
            "message": "Your monthly expense trend is stable.",
            "level": "info",
            "detail": ""
        })

    # ----------------------------------------------------------
    # CATEGORY SPIKE DETECTION
    # ----------------------------------------------------------
    last_30_by_cat = (
        Expense.objects.filter(owner=user, date__gte=last_30)
        .values("category")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )

    prev_30_by_cat = (
        Expense.objects.filter(owner=user, date__range=[prev_30, last_30 - timedelta(days=1)])
        .values("category")
        .annotate(total=Sum("amount"))
    )

    prev_map = {x["category"]: x["total"] for x in prev_30_by_cat}

    for item in last_30_by_cat:
        cat = item["category"]
        last_val = item["total"] or 0
        prev_val = prev_map.get(cat, 0)

        if prev_val > 0:
            cat_pct = ((last_val - prev_val) / prev_val) * 100
        else:
            cat_pct = 100 if last_val > 0 else 0

        if cat_pct >= 25 and last_val >= 500:
            level = "critical" if cat_pct >= 50 else "warning"
            suggestions.append({
                "message": f"{cat} spending increased by {cat_pct:.0f}%.",
                "level": level,
                "detail": f"Try reducing {cat} spending or setting a limit."
            })

    # ----------------------------------------------------------
    # SAVINGS SUGGESTION FOR TOP CATEGORY
    # ----------------------------------------------------------
    if last_30_by_cat:
        top = last_30_by_cat[0]
        top_cat = top["category"]
        top_val = top["total"]
        potential_save = top_val * 0.10  # 10% cut suggestion

        if potential_save >= 100:
            suggestions.append({
                "message": f"Reduce {top_cat} spending by 10% to save ~₹{potential_save:.0f}/month.",
                "level": "info",
                "detail": "Small consistent changes can lead to big savings."
            })

    # ----------------------------------------------------------
    # Sort by severity
    # ----------------------------------------------------------
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(suggestions, key=lambda x: order[x["level"]])
