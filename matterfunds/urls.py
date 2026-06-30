from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from apps.accounts.views import home

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='home'),
    path('accounts/', include('allauth.urls')),
    path('firms/', include('apps.firms.urls')),
    path('clients/', include('apps.clients.urls')),
    path('matters/', include('apps.matters.urls')),
    path('trust/', include(('apps.trust.urls', 'trust'), namespace='trust')),
    path('audit/', include('apps.audit.urls')),
    path('dashboard/', include('apps.dashboard.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
