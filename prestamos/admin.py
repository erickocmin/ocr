from django.contrib import admin
from .models import Prestamo


@admin.register(Prestamo)
class PrestamoAdmin(admin.ModelAdmin):
    list_display = ['id', 'socio', 'ejemplar', 'fecha_prestamo', 'fecha_vencimiento', 'fecha_devolucion']
    list_filter = ['fecha_devolucion']
    search_fields = ['socio__nombre', 'socio__apellido', 'ejemplar__codigo']
    readonly_fields = ['fecha_prestamo', 'created_at', 'updated_at']
