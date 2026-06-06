from django.contrib import admin

from .models import Autor, Ejemplar, Libro


@admin.register(Autor)
class AutorAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'created_at']
    search_fields = ['nombre']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Libro)
class LibroAdmin(admin.ModelAdmin):
    list_display = ['titulo', 'isbn', 'genero', 'anio_publicacion', 'retirado', 'created_at']
    list_filter = ['retirado', 'genero']
    search_fields = ['titulo', 'isbn']
    filter_horizontal = ['autores']
    readonly_fields = ['fecha_retiro', 'created_at', 'updated_at']


@admin.register(Ejemplar)
class EjemplarAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'libro', 'estado', 'retirado', 'created_at']
    list_filter = ['estado', 'retirado']
    search_fields = ['codigo', 'libro__titulo']
    readonly_fields = ['fecha_retiro', 'created_at', 'updated_at']
