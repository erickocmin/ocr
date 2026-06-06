from django.db import models
from django.utils import timezone


class Autor(models.Model):
    nombre = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Autor'
        verbose_name_plural = 'Autores'

    def __str__(self):
        return self.nombre


class Libro(models.Model):
    titulo = models.CharField(max_length=200)
    autores = models.ManyToManyField(Autor, related_name='libros')
    isbn = models.CharField(max_length=20, blank=True, null=True, unique=True)
    genero = models.CharField(max_length=100, blank=True)
    anio_publicacion = models.PositiveIntegerField(
        null=True, blank=True, verbose_name='Año de publicación'
    )
    retirado = models.BooleanField(default=False)
    fecha_retiro = models.DateTimeField(null=True, blank=True)
    notas = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['titulo']
        verbose_name = 'Libro'
        verbose_name_plural = 'Libros'

    def __str__(self):
        return self.titulo

    @property
    def total_ejemplares(self):
        return self.ejemplares.filter(retirado=False).count()

    @property
    def ejemplares_disponibles(self):
        from prestamos.models import Prestamo
        activos_ids = Prestamo.objects.filter(
            fecha_devolucion__isnull=True
        ).values('ejemplar_id')
        return self.ejemplares.filter(retirado=False).exclude(id__in=activos_ids).count()

    def tiene_prestamos_activos(self):
        return self.ejemplares.filter(
            prestamos__fecha_devolucion__isnull=True
        ).exists()


class EstadoEjemplar(models.TextChoices):
    NUEVO = 'NUEVO', 'Nuevo'
    BUENO = 'BUENO', 'Bueno'
    REGULAR = 'REGULAR', 'Regular'
    MALO = 'MALO', 'Malo'
    DETERIORADO = 'DETERIORADO', 'Deteriorado'


class Ejemplar(models.Model):
    libro = models.ForeignKey(
        Libro, on_delete=models.PROTECT, related_name='ejemplares'
    )
    codigo = models.CharField(max_length=30)
    estado = models.CharField(
        max_length=20,
        choices=EstadoEjemplar.choices,
        default=EstadoEjemplar.BUENO,
    )
    retirado = models.BooleanField(default=False)
    fecha_retiro = models.DateTimeField(null=True, blank=True)
    notas = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Ejemplar'
        verbose_name_plural = 'Ejemplares'
        unique_together = [('libro', 'codigo')]

    def __str__(self):
        return f'{self.codigo} — {self.libro.titulo}'

    @property
    def disponible(self):
        return (
            not self.retirado
            and not self.libro.retirado
            and not self.prestamos.filter(fecha_devolucion__isnull=True).exists()
        )

    def tiene_prestamo_activo(self):
        return self.prestamos.filter(fecha_devolucion__isnull=True).exists()
