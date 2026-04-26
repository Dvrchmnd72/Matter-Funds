from django.urls import path
from . import views

app_name = 'matters'
urlpatterns = [
    path('', views.MatterListView.as_view(), name='matter_list'),
    path('new/', views.MatterCreateView.as_view(), name='matter_create'),
    path('<int:pk>/', views.MatterDetailView.as_view(), name='matter_detail'),
    path('<int:matter_pk>/ledgers/new/', views.MatterLedgerCreateView.as_view(), name='ledger_create'),
]
