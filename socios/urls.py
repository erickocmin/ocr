from rest_framework.routers import DefaultRouter
from .views import VistaSocio

router = DefaultRouter()
router.register('socios', VistaSocio, basename='socio')

urlpatterns = router.urls
