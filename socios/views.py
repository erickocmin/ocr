from django.db import DatabaseError, OperationalError
from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets

from biblioteca.exceptions import CorreoDuplicado, ErrorBaseDatos, ErrorValidacion, SocioConPrestamosActivos
from biblioteca.mixins import AtomicModelViewSetMixin
from .models import Socio
from .serializers import SocioSerializer


class VistaSocio(AtomicModelViewSetMixin, viewsets.ModelViewSet):
    serializer_class = SocioSerializer
    excepcion_integrity = CorreoDuplicado
    excepcion_referencia = SocioConPrestamosActivos

    def get_queryset(self):
        try:
            qs = Socio.objects.all()

            q = self.request.query_params.get('q', '').strip()
            if q:
                qs = qs.filter(
                    Q(nombre__icontains=q) |
                    Q(apellido__icontains=q) |
                    Q(correo__icontains=q) |
                    Q(telefono__icontains=q)
                )

            activo = self.request.query_params.get('activo', '').strip().lower()
            if activo == 'true':
                qs = qs.filter(activo=True)
            elif activo == 'false':
                qs = qs.filter(activo=False)
            elif activo:
                raise ErrorValidacion(
                    "El parámetro 'activo' solo acepta los valores 'true' o 'false'."
                )

            con_vencidos = self.request.query_params.get('con_vencidos', '').strip().lower()
            if con_vencidos == 'true':
                qs = qs.filter(
                    prestamos__fecha_devolucion__isnull=True,
                    prestamos__fecha_vencimiento__lt=timezone.now().date()
                ).distinct()
            elif con_vencidos and con_vencidos != 'false':
                raise ErrorValidacion(
                    "El parámetro 'con_vencidos' solo acepta los valores 'true' o 'false'."
                )

            return qs
        except (OperationalError, DatabaseError) as exc:
            raise ErrorBaseDatos() from exc
