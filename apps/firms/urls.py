from django.urls import path
from . import views

app_name = 'firms'
urlpatterns = [
    path('', views.FirmListView.as_view(), name='firm_list'),
    path('new/', views.FirmCreateView.as_view(), name='firm_create'),
    path('<int:pk>/', views.FirmDetailView.as_view(), name='firm_detail'),
]
