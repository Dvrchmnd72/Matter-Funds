from django.urls import path
from . import views

app_name = 'clients'
urlpatterns = [
    path('', views.ClientListView.as_view(), name='client_list'),
    path('new/', views.ClientCreateView.as_view(), name='client_create'),
    path('<int:pk>/', views.ClientDetailView.as_view(), name='client_detail'),
]
