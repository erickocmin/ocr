from django.db import DatabaseError, IntegrityError, OperationalError, transaction
from django.db.models import ProtectedError

from biblioteca.exceptions import ErrorBaseDatos, ErrorDuplicado, ErrorReferencia


class AtomicModelViewSetMixin:
    """
    Envuelve TODOS los métodos del viewset en try/except con excepciones propias.

    Métodos de lectura (list, retrieve):
        - DatabaseError / OperationalError → ErrorBaseDatos

    Métodos de escritura (create, update, partial_update, destroy):
        - transaction.atomic() + IntegrityError → excepcion_integrity
        - transaction.atomic() + ProtectedError → excepcion_referencia
        - DatabaseError / OperationalError     → ErrorBaseDatos

    Las subclases personalizan los tipos de excepción con atributos de clase:
        excepcion_integrity  → default ErrorDuplicado
        excepcion_referencia → default ErrorReferencia
    """
    excepcion_integrity: type = ErrorDuplicado
    excepcion_referencia: type = ErrorReferencia

    # ── Operaciones de lectura ────────────────────────────────────────────────

    def list(self, request, *args, **kwargs):
        try:
            return super().list(request, *args, **kwargs)
        except (OperationalError, DatabaseError) as exc:
            raise ErrorBaseDatos() from exc

    def retrieve(self, request, *args, **kwargs):
        try:
            return super().retrieve(request, *args, **kwargs)
        except (OperationalError, DatabaseError) as exc:
            raise ErrorBaseDatos() from exc

    # ── Operaciones de escritura ──────────────────────────────────────────────

    def create(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                return super().create(request, *args, **kwargs)
        except IntegrityError as exc:
            raise self.excepcion_integrity() from exc
        except ProtectedError as exc:
            raise self.excepcion_referencia() from exc
        except (OperationalError, DatabaseError) as exc:
            raise ErrorBaseDatos() from exc

    def update(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                return super().update(request, *args, **kwargs)
        except IntegrityError as exc:
            raise self.excepcion_integrity() from exc
        except ProtectedError as exc:
            raise self.excepcion_referencia() from exc
        except (OperationalError, DatabaseError) as exc:
            raise ErrorBaseDatos() from exc

    def partial_update(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                return super().partial_update(request, *args, **kwargs)
        except IntegrityError as exc:
            raise self.excepcion_integrity() from exc
        except ProtectedError as exc:
            raise self.excepcion_referencia() from exc
        except (OperationalError, DatabaseError) as exc:
            raise ErrorBaseDatos() from exc

    def destroy(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                return super().destroy(request, *args, **kwargs)
        except IntegrityError as exc:
            raise self.excepcion_integrity() from exc
        except ProtectedError as exc:
            raise self.excepcion_referencia() from exc
        except (OperationalError, DatabaseError) as exc:
            raise ErrorBaseDatos() from exc
