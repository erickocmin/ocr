from rest_framework.routers import DefaultRouter
from .views import VistaPrestamo

router = DefaultRouter()
router.register('prestamos', VistaPrestamo, basename='prestamo')

urlpatterns = router.urls
