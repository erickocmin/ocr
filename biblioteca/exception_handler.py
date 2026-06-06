from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, OperationalError
from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .exceptions import BibliotecaError


def manejador_excepciones(exc, context):
    """
    Manejador centralizado de excepciones para toda la API.

    Orden de prioridad:
      1. Excepciones propias (BibliotecaError) → mensaje y código ya definidos
      2. ProtectedError → intento de borrar un registro referenciado
      3. IntegrityError → violación de constraint de unicidad en BD
      4. OperationalError → error operacional de BD (conexión, timeout, etc.)
      5. ObjectDoesNotExist → .get() sin resultado
      6. Manejador estándar de DRF (APIException, Http404, PermissionDenied, ValidationError)
      7. Excepción no controlada → 500 amigable
    """

    if isinstance(exc, BibliotecaError):
        return Response(
            {'error': exc.mensaje, 'codigo': exc.codigo},
            status=exc.status_code,
        )

    if isinstance(exc, ProtectedError):
        return Response(
            {
                'error': (
                    "No se puede eliminar este registro porque está siendo utilizado "
                    "por otros registros del sistema."
                ),
                'codigo': 'error_referencia',
            },
            status=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, IntegrityError):
        return Response(
            {
                'error': (
                    "Ya existe un registro con esos datos. "
                    "Verifique los campos que deben ser únicos."
                ),
                'codigo': 'error_duplicado',
            },
            status=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, OperationalError):
        return Response(
            {
                'error': (
                    "No se pudo completar la operación por un problema con la base de datos. "
                    "Por favor, intente más tarde."
                ),
                'codigo': 'error_base_datos',
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if isinstance(exc, ObjectDoesNotExist):
        return Response(
            {
                'error': 'El registro solicitado no existe.',
                'codigo': 'no_encontrado',
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    response = drf_exception_handler(exc, context)
    if response is not None:
        return response

    return Response(
        {
            'error': (
                'Ha ocurrido un error interno del servidor. '
                'Por favor, intente más tarde.'
            ),
            'codigo': 'error_interno',
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
