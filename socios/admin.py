from django.contrib import admin
from .models import Socio


@admin.register(Socio)
class SocioAdmin(admin.ModelAdmin):
    list_display = ['nombre_completo', 'correo', 'telefono', 'activo', 'prestamos_activos_count', 'created_at']
    list_filter = ['activo']
    search_fields = ['nombre', 'apellido', 'correo']
    readonly_fields = ['created_at', 'updated_at']
