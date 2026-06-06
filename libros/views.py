from django.db import DatabaseError, OperationalError
from django.db.models import Q
from rest_framework import viewsets

from biblioteca.exceptions import (
    CodigoEjemplarDuplicado,
    EjemplarConPrestamos,
    ErrorBaseDatos,
    ErrorValidacion,
    IsbnDuplicado,
    LibroConEjemplares,
)
from biblioteca.mixins import AtomicModelViewSetMixin
from .models import Autor, Ejemplar, Libro
from .serializers import AutorSerializer, EjemplarSerializer, LibroSerializer


def _activos_ids():
    from prestamos.models import Prestamo
    return Prestamo.objects.filter(fecha_devolucion__isnull=True).values('ejemplar_id')


class VistaAutor(AtomicModelViewSetMixin, viewsets.ModelViewSet):
    serializer_class = AutorSerializer

    def get_queryset(self):
        try:
            qs = Autor.objects.all()
            q = self.request.query_params.get('q', '').strip()
            if q:
                qs = qs.filter(nombre__icontains=q)
            return qs
        except (OperationalError, DatabaseError) as exc:
            raise ErrorBaseDatos() from exc


class VistaLibro(AtomicModelViewSetMixin, viewsets.ModelViewSet):
    serializer_class = LibroSerializer
    excepcion_integrity = IsbnDuplicado
    excepcion_referencia = LibroConEjemplares

    def get_queryset(self):
        try:
            qs = Libro.objects.prefetch_related('autores', 'ejemplares')

            q = self.request.query_params.get('q', '').strip()
            if q:
                qs = qs.filter(
                    Q(titulo__icontains=q) |
                    Q(autores__nombre__icontains=q) |
                    Q(isbn__icontains=q) |
                    Q(genero__icontains=q)
                ).distinct()

            genero = self.request.query_params.get('genero', '').strip()
            if genero:
                qs = qs.filter(genero__icontains=genero)

            retirado = self.request.query_params.get('retirado', '').strip().lower()
            if retirado == 'false':
                qs = qs.filter(retirado=False)
            elif retirado == 'true':
                qs = qs.filter(retirado=True)
            elif retirado:
                raise ErrorValidacion(
                    "El parámetro 'retirado' solo acepta los valores 'true' o 'false'."
                )

            return qs
        except (OperationalError, DatabaseError) as exc:
            raise ErrorBaseDatos() from exc


class VistaEjemplar(AtomicModelViewSetMixin, viewsets.ModelViewSet):
    serializer_class = EjemplarSerializer
    excepcion_integrity = CodigoEjemplarDuplicado
    excepcion_referencia = EjemplarConPrestamos

    def get_queryset(self):
        try:
            qs = Ejemplar.objects.select_related('libro').order_by('id')

            q = self.request.query_params.get('q', '').strip()
            if q:
                qs = qs.filter(
                    Q(codigo__icontains=q) | Q(libro__titulo__icontains=q)
                )

            libro_id = self.request.query_params.get('libro', '').strip()
            if libro_id:
                try:
                    qs = qs.filter(libro_id=int(libro_id))
                except ValueError as exc:
                    raise ErrorValidacion(
                        "El parámetro 'libro' debe ser un número entero válido."
                    ) from exc

            estado = self.request.query_params.get('estado', '').strip()
            if estado:
                qs = qs.filter(estado=estado)

            retirado = self.request.query_params.get('retirado', '').strip().lower()
            if retirado == 'false':
                qs = qs.filter(retirado=False)
            elif retirado == 'true':
                qs = qs.filter(retirado=True)
            elif retirado:
                raise ErrorValidacion(
                    "El parámetro 'retirado' solo acepta los valores 'true' o 'false'."
                )

            disponibles = self.request.query_params.get('disponibles', '').strip().lower()
            if disponibles == 'true':
                qs = qs.filter(retirado=False, libro__retirado=False).exclude(
                    id__in=_activos_ids()
                )
            elif disponibles == 'false':
                qs = qs.filter(
                    Q(retirado=True) |
                    Q(libro__retirado=True) |
                    Q(id__in=_activos_ids())
                )
            elif disponibles:
                raise ErrorValidacion(
                    "El parámetro 'disponibles' solo acepta los valores 'true' o 'false'."
                )

            return qs
        except (OperationalError, DatabaseError) as exc:
            raise ErrorBaseDatos() from exc
