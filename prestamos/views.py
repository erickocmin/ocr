from django.db import DatabaseError, IntegrityError, OperationalError, transaction
from django.db.models import ProtectedError, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from biblioteca.exceptions import (
    CampoPrestamoNoEditable,
    ErrorBaseDatos,
    ErrorValidacion,
    PrestamoConflictoConcurrente,
    PrestamoNoEncontrado,
    PrestamoYaDevuelto,
)
from biblioteca.mixins import AtomicModelViewSetMixin
from .models import Prestamo
from .serializers import CrearPrestamoSerializer, PrestamoSerializer


class VistaPrestamo(AtomicModelViewSetMixin, viewsets.ModelViewSet):
    """
    create, partial_update y devolver tienen lógica propia y
    manejan sus propias transacciones y excepciones.
    """
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_serializer_class(self):
        if self.action == 'create':
            return CrearPrestamoSerializer
        return PrestamoSerializer

    def get_queryset(self):
        try:
            qs = Prestamo.objects.select_related('socio', 'ejemplar__libro')

            q = self.request.query_params.get('q', '').strip()
            if q:
                qs = qs.filter(
                    Q(socio__nombre__icontains=q) |
                    Q(socio__apellido__icontains=q) |
                    Q(ejemplar__codigo__icontains=q) |
                    Q(ejemplar__libro__titulo__icontains=q)
                )

            activos = self.request.query_params.get('activos', '').strip().lower()
            if activos == 'true':
                qs = qs.filter(fecha_devolucion__isnull=True)
            elif activos == 'false':
                qs = qs.filter(fecha_devolucion__isnull=False)
            elif activos:
                raise ErrorValidacion(
                    "El parámetro 'activos' solo acepta los valores 'true' o 'false'."
                )

            vencidos = self.request.query_params.get('vencidos', '').strip().lower()
            if vencidos == 'true':
                qs = qs.filter(
                    fecha_devolucion__isnull=True,
                    fecha_vencimiento__lt=timezone.now().date(),
                )
            elif vencidos and vencidos != 'false':
                raise ErrorValidacion(
                    "El parámetro 'vencidos' solo acepta los valores 'true' o 'false'."
                )

            socio_id = self.request.query_params.get('socio', '').strip()
            if socio_id:
                try:
                    qs = qs.filter(socio_id=int(socio_id))
                except ValueError as exc:
                    raise ErrorValidacion(
                        "El parámetro 'socio' debe ser un número entero válido."
                    ) from exc

            return qs
        except (OperationalError, DatabaseError) as exc:
            raise ErrorBaseDatos() from exc

    def create(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                serializer = CrearPrestamoSerializer(
                    data=request.data, context={'request': request}
                )
                serializer.is_valid(raise_exception=True)
                prestamo = serializer.save()
        except IntegrityError as exc:
            raise PrestamoConflictoConcurrente() from exc
        except ProtectedError as exc:
            raise PrestamoConflictoConcurrente(
                "Error de integridad al registrar el préstamo. Intente nuevamente."
            ) from exc
        except (OperationalError, DatabaseError) as exc:
            raise ErrorBaseDatos() from exc
        return Response(
            PrestamoSerializer(prestamo).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                instance = self.get_object()

                campos_enviados = set(request.data.keys())
                no_permitidos = campos_enviados - {'notas'}
                if no_permitidos:
                    raise CampoPrestamoNoEditable(no_permitidos)

                serializer = PrestamoSerializer(instance, data=request.data, partial=True)
                serializer.is_valid(raise_exception=True)
                serializer.save()
        except IntegrityError as exc:
            raise ErrorBaseDatos(
                "Error de integridad al actualizar el préstamo."
            ) from exc
        except (OperationalError, DatabaseError) as exc:
            raise ErrorBaseDatos() from exc
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def devolver(self, request, pk=None):
        try:
            with transaction.atomic():
                try:
                    prestamo = (
                        self.get_queryset()
                        .select_for_update()
                        .get(pk=pk)
                    )
                except Prestamo.DoesNotExist as exc:
                    raise PrestamoNoEncontrado() from exc

                if prestamo.fecha_devolucion is not None:
                    raise PrestamoYaDevuelto()

                prestamo.fecha_devolucion = timezone.now()
                prestamo.save(update_fields=['fecha_devolucion', 'updated_at'])
        except IntegrityError as exc:
            raise PrestamoConflictoConcurrente(
                "Error al registrar la devolución. Intente nuevamente."
            ) from exc
        except (OperationalError, DatabaseError) as exc:
            raise ErrorBaseDatos() from exc
        return Response(PrestamoSerializer(prestamo).data)
