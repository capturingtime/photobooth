from django.urls import path
from . import views

from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("", views.index, name="index"),
    path("last/", views.last, name="last"),
    path("attract/", views.attract, name="attract"),
    path("last_capture/", views.last_capture, name="last_capture"),
    path("series_capture/", views.series_capture, name="series_capture"),
    path("series_final/", views.series_final, name="series_final"),
    path("single_final/", views.single_final, name="single_final"),
    path("unavailable/", views.unavailable, name="unavailable"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
