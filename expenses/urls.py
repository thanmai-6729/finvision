from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from . import views

urlpatterns = [
    # -------------------------
    # EXPENSES CORE ROUTES
    # -------------------------
    path('', views.index, name="expenses"),

    path('add-expense', views.add_expense, name="add-expenses"),
    path('edit-expense/<int:id>', views.expense_edit, name="expense-edit"),
    path('expense-delete/<int:id>', views.delete_expense, name="expense-delete"),

    path('search-expenses', csrf_exempt(views.search_expenses), name="search_expenses"),

    path('expense_category_summary', views.expense_category_summary, name="expense_category_summary"),

    path('set-daily-expense-limit/', views.set_expense_limit, name="set-daily-expense-limit"),

    # -------------------------
    # EXISTING DASHBOARD (old)
    # -------------------------
    path('dashboard/', views.dashboard, name="dashboard"),

    # -------------------------
    # FORECAST PAGE
    # -------------------------
    path('forecast/', views.forecast, name="forecast"),

    # -------------------------
    # ADVANCED UNIFIED DASHBOARD (NEW)
    # -------------------------
    path('dashboard/advanced/', views.advanced_dashboard_view, name="advanced-dashboard"),

    # API endpoints for advanced dashboard
    path('api/dashboard/summary/', views.api_dashboard_summary, name="api-dashboard-summary"),
    path('api/dashboard/transactions/', views.api_dashboard_transactions, name="api-dashboard-transactions"),
]
