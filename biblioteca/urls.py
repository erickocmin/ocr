from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('libros.urls')),
    path('api/', include('socios.urls')),
    path('api/', include('prestamos.urls')),
    path('api/', include('deteccion.urls')),
]
