from rest_framework.routers import DefaultRouter

from .views import VistaAutor, VistaEjemplar, VistaLibro

router = DefaultRouter()
router.register('autores', VistaAutor, basename='autor')
router.register('libros', VistaLibro, basename='libro')
router.register('ejemplares', VistaEjemplar, basename='ejemplar')

urlpatterns = router.urls
