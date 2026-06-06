from django.urls import path
from .views import LoginAdminView, DetectarDocumentoView

urlpatterns = [
    path('deteccion/login/', LoginAdminView.as_view()),
    path('deteccion/detectar/', DetectarDocumentoView.as_view()),
]
