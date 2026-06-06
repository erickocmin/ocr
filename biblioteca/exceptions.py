from rest_framework import status


class BibliotecaError(Exception):
    """Base para todas las excepciones propias del sistema."""
    mensaje = "Ha ocurrido un error inesperado."
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    codigo = "error_interno"

    def __init__(self, mensaje=None):
        if mensaje is not None:
            self.mensaje = mensaje
        super().__init__(self.mensaje)


class ErrorValidacion(BibliotecaError):
    """
    Error de validación de formato o contenido en los datos enviados.
    Reemplaza serializers.ValidationError en todo el código propio.
    """
    mensaje = "Los datos enviados no son válidos."
    status_code = status.HTTP_400_BAD_REQUEST
    codigo = "error_validacion"


class ErrorBaseDatos(BibliotecaError):
    mensaje = "Error al acceder a la base de datos."
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    codigo = "error_base_datos"


class ErrorDuplicado(ErrorBaseDatos):
    mensaje = "Ya existe un registro con esos datos."
    status_code = status.HTTP_409_CONFLICT
    codigo = "error_duplicado"


class ErrorReferencia(ErrorBaseDatos):
    mensaje = "No se puede eliminar este registro porque está referenciado por otros registros."
    status_code = status.HTTP_409_CONFLICT
    codigo = "error_referencia"


class ErrorAutor(BibliotecaError):
    status_code = status.HTTP_400_BAD_REQUEST
    codigo = "error_autor"


class AutorNoEncontrado(ErrorAutor):
    mensaje = "El autor solicitado no existe."
    status_code = status.HTTP_404_NOT_FOUND
    codigo = "autor_no_encontrado"


class ErrorLibro(BibliotecaError):
    status_code = status.HTTP_400_BAD_REQUEST
    codigo = "error_libro"


class LibroNoEncontrado(ErrorLibro):
    mensaje = "El libro solicitado no existe."
    status_code = status.HTTP_404_NOT_FOUND
    codigo = "libro_no_encontrado"


class LibroRetirado(ErrorLibro):
    mensaje = "El libro ha sido retirado del catálogo y no admite nuevas operaciones."
    status_code = status.HTTP_409_CONFLICT
    codigo = "libro_retirado"


class LibroConEjemplares(ErrorLibro):
    mensaje = (
        "No se puede eliminar el libro porque tiene ejemplares registrados. "
        "Retire primero todos sus ejemplares."
    )
    status_code = status.HTTP_409_CONFLICT
    codigo = "libro_con_ejemplares"


class LibroConPrestamosActivos(ErrorLibro):
    mensaje = (
        "No se puede retirar el libro porque tiene préstamos activos. "
        "Todos los ejemplares deben ser devueltos antes de retirarlo del catálogo."
    )
    status_code = status.HTTP_409_CONFLICT
    codigo = "libro_con_prestamos_activos"


class LibroSinEjemplares(ErrorLibro):
    mensaje = "El libro no tiene ejemplares disponibles en este momento."
    status_code = status.HTTP_409_CONFLICT
    codigo = "libro_sin_ejemplares"


class IsbnDuplicado(ErrorLibro):
    mensaje = "Ya existe un libro registrado con ese ISBN."
    status_code = status.HTTP_409_CONFLICT
    codigo = "isbn_duplicado"

class ErrorEjemplar(BibliotecaError):
    status_code = status.HTTP_400_BAD_REQUEST
    codigo = "error_ejemplar"


class EjemplarNoEncontrado(ErrorEjemplar):
    mensaje = "El ejemplar solicitado no existe."
    status_code = status.HTTP_404_NOT_FOUND
    codigo = "ejemplar_no_encontrado"


class EjemplarRetirado(ErrorEjemplar):
    mensaje = "El ejemplar ha sido retirado y no puede ser prestado."
    status_code = status.HTTP_409_CONFLICT
    codigo = "ejemplar_retirado"


class EjemplarNoDisponible(ErrorEjemplar):
    mensaje = "El ejemplar no está disponible porque ya cuenta con un préstamo activo."
    status_code = status.HTTP_409_CONFLICT
    codigo = "ejemplar_no_disponible"


class EjemplarConPrestamos(ErrorEjemplar):
    mensaje = (
        "No se puede eliminar el ejemplar porque tiene préstamos registrados en el historial."
    )
    status_code = status.HTTP_409_CONFLICT
    codigo = "ejemplar_con_prestamos"


class EjemplarConPrestamoActivo(ErrorEjemplar):
    mensaje = (
        "No se puede retirar este ejemplar porque tiene un préstamo activo. "
        "El socio debe devolverlo primero."
    )
    status_code = status.HTTP_409_CONFLICT
    codigo = "ejemplar_con_prestamo_activo"


class CodigoEjemplarDuplicado(ErrorEjemplar):
    mensaje = "Ya existe un ejemplar con ese código en este libro."
    status_code = status.HTTP_409_CONFLICT
    codigo = "codigo_ejemplar_duplicado"


class EjemplarReasignacion(ErrorEjemplar):
    mensaje = "No se puede reasignar un ejemplar a un libro diferente."
    status_code = status.HTTP_409_CONFLICT
    codigo = "ejemplar_reasignacion"


class EjemplarCodigoCambio(ErrorEjemplar):
    mensaje = (
        "No se puede cambiar el código de un ejemplar que ya tiene historial de préstamos."
    )
    status_code = status.HTTP_409_CONFLICT
    codigo = "ejemplar_codigo_cambio"


class ErrorSocio(BibliotecaError):
    status_code = status.HTTP_400_BAD_REQUEST
    codigo = "error_socio"


class SocioNoEncontrado(ErrorSocio):
    mensaje = "El socio solicitado no existe."
    status_code = status.HTTP_404_NOT_FOUND
    codigo = "socio_no_encontrado"


class SocioInactivo(ErrorSocio):
    mensaje = "El socio está inactivo y no puede realizar préstamos."
    status_code = status.HTTP_409_CONFLICT
    codigo = "socio_inactivo"


class SocioConPrestamosActivos(ErrorSocio):
    mensaje = (
        "No se puede realizar esta operación porque el socio tiene préstamos activos. "
        "Registre la devolución de todos sus préstamos primero."
    )
    status_code = status.HTTP_409_CONFLICT
    codigo = "socio_con_prestamos_activos"


class SocioConPrestamosVencidos(ErrorSocio):
    mensaje = (
        "El socio tiene préstamos vencidos sin devolver. "
        "Debe regularizar su situación antes de solicitar un nuevo préstamo."
    )
    status_code = status.HTTP_409_CONFLICT
    codigo = "socio_con_prestamos_vencidos"


class CorreoDuplicado(ErrorSocio):
    mensaje = "Ya existe Socio con este correo."
    status_code = status.HTTP_409_CONFLICT
    codigo = "correo_duplicado"


class ErrorPrestamo(BibliotecaError):
    status_code = status.HTTP_400_BAD_REQUEST
    codigo = "error_prestamo"


class PrestamoNoEncontrado(ErrorPrestamo):
    mensaje = "El préstamo solicitado no existe."
    status_code = status.HTTP_404_NOT_FOUND
    codigo = "prestamo_no_encontrado"


class PrestamoYaDevuelto(ErrorPrestamo):
    mensaje = "Este préstamo ya fue registrado como devuelto."
    status_code = status.HTTP_409_CONFLICT
    codigo = "prestamo_ya_devuelto"


class PrestamoConflictoConcurrente(ErrorPrestamo):
    mensaje = (
        "El ejemplar fue asignado a otro préstamo al mismo tiempo. "
        "Intente nuevamente con otro ejemplar disponible."
    )
    status_code = status.HTTP_409_CONFLICT
    codigo = "prestamo_conflicto_concurrente"


class PrestamoMismoLibro(ErrorPrestamo):
    mensaje = "El socio ya tiene en préstamo un ejemplar de este libro."
    status_code = status.HTTP_409_CONFLICT
    codigo = "prestamo_mismo_libro"


class CampoPrestamoNoEditable(ErrorPrestamo):
    status_code = status.HTTP_400_BAD_REQUEST
    codigo = "campo_prestamo_no_editable"

    def __init__(self, campos_no_permitidos):
        nombres = ', '.join(sorted(campos_no_permitidos))
        super().__init__(
            f"Los campos [{nombres}] no se pueden modificar en un préstamo existente. "
            "Solo se pueden editar las notas. "
            "Para registrar una devolución use la acción 'devolver'."
        )
