from django.db import models
from django.utils import timezone


class Socio(models.Model):
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100, blank=True)
    correo = models.EmailField(unique=True)
    telefono = models.CharField(max_length=20, blank=True)
    direccion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    notas = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['apellido', 'nombre']
        verbose_name = 'Socio'
        verbose_name_plural = 'Socios'

    def __str__(self):
        return self.nombre_completo

    @property
    def nombre_completo(self):
        parts = [self.nombre, self.apellido]
        return ' '.join(p for p in parts if p).strip()

    @property
    def prestamos_activos_count(self):
        return self.prestamos.filter(fecha_devolucion__isnull=True).count()

    @property
    def tiene_prestamos_vencidos(self):
        return self.prestamos.filter(
            fecha_devolucion__isnull=True,
            fecha_vencimiento__lt=timezone.now().date()
        ).exists()
