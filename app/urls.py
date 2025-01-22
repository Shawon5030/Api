from django.urls import path
from .views import PDFParsingAPIView
from django.views.generic import TemplateView

from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('api/parse-pdf/', PDFParsingAPIView.as_view(), name='parse_pdf'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)