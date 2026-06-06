from django.db import models
from django.utils import timezone


class Prestamo(models.Model):
    socio = models.ForeignKey(
        'socios.Socio',
        on_delete=models.PROTECT,
        related_name='prestamos'
    )
    ejemplar = models.ForeignKey(
        'libros.Ejemplar',
        on_delete=models.PROTECT,
        related_name='prestamos'
    )
    fecha_prestamo = models.DateTimeField(default=timezone.now)
    fecha_vencimiento = models.DateField()
    fecha_devolucion = models.DateTimeField(null=True, blank=True)
    notas = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha_prestamo']
        verbose_name = 'Préstamo'
        verbose_name_plural = 'Préstamos'
        constraints = [
            models.UniqueConstraint(
                fields=['ejemplar'],
                condition=models.Q(fecha_devolucion__isnull=True),
                name='prestamo_activo_unico_por_ejemplar',
            )
        ]

    def __str__(self):
        return f'Préstamo #{self.id}: {self.ejemplar.codigo} → {self.socio}'

    @property
    def activo(self):
        return self.fecha_devolucion is None

    @property
    def vencido(self):
        return self.activo and self.fecha_vencimiento < timezone.now().date()
