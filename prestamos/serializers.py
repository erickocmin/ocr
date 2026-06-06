from datetime import timedelta

from django.db import IntegrityError
from django.utils import timezone
from rest_framework import serializers

from biblioteca.exceptions import (
    CampoPrestamoNoEditable,
    EjemplarNoDisponible,
    EjemplarRetirado,
    ErrorValidacion,
    LibroRetirado,
    LibroSinEjemplares,
    PrestamoConflictoConcurrente,
    PrestamoMismoLibro,
    SocioConPrestamosVencidos,
    SocioInactivo,
)
from libros.models import Ejemplar, Libro
from socios.models import Socio
from .models import Prestamo

DIAS_PRESTAMO_MAXIMO = 60


class PrestamoSerializer(serializers.ModelSerializer):
    socio_nombre = serializers.CharField(source='socio.nombre_completo', read_only=True)
    socio_correo = serializers.CharField(source='socio.correo', read_only=True)
    ejemplar_codigo = serializers.CharField(source='ejemplar.codigo', read_only=True)
    libro_titulo = serializers.CharField(source='ejemplar.libro.titulo', read_only=True)
    libro_id = serializers.IntegerField(source='ejemplar.libro.id', read_only=True)
    vencido = serializers.SerializerMethodField()
    activo = serializers.SerializerMethodField()

    class Meta:
        model = Prestamo
        fields = [
            'id', 'socio', 'socio_nombre', 'socio_correo',
            'ejemplar', 'ejemplar_codigo', 'libro_titulo', 'libro_id',
            'fecha_prestamo', 'fecha_vencimiento', 'fecha_devolucion',
            'notas', 'activo', 'vencido',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['fecha_prestamo', 'fecha_devolucion', 'created_at', 'updated_at']

    def get_vencido(self, obj):
        return obj.vencido

    def get_activo(self, obj):
        return obj.activo

    # ── Validaciones de lógica de negocio ─────────────────────────────────────

    def validate(self, attrs):
        instance = self.instance
        # Campos inmutables: socio, ejemplar y fecha_vencimiento no se pueden editar
        if instance is not None:
            campos_inmutables = {'socio', 'ejemplar', 'fecha_vencimiento'}
            no_permitidos = {campo for campo in campos_inmutables if campo in attrs}
            if no_permitidos:
                raise CampoPrestamoNoEditable(no_permitidos)
        return attrs


class CrearPrestamoSerializer(serializers.Serializer):
    socio = serializers.PrimaryKeyRelatedField(queryset=Socio.objects.all())
    libro = serializers.PrimaryKeyRelatedField(
        queryset=Libro.objects.all(), required=False, allow_null=True
    )
    ejemplar = serializers.PrimaryKeyRelatedField(
        queryset=Ejemplar.objects.all(), required=False, allow_null=True
    )
    fecha_vencimiento = serializers.DateField()
    notas = serializers.CharField(required=False, allow_blank=True, default='')

    # ── Validaciones de campo ──────────────────────────────────────────────────

    def validate_socio(self, value):
        if not value.activo:
            raise SocioInactivo(
                f"El socio '{value.nombre_completo}' está inactivo y no puede realizar préstamos."
            )
        return value

    def validate_fecha_vencimiento(self, value):
        hoy = timezone.now().date()
        limite = hoy + timedelta(days=DIAS_PRESTAMO_MAXIMO)
        if value < hoy:
            raise ErrorValidacion("La fecha de vencimiento no puede ser anterior a hoy.")
        if value > limite:
            raise ErrorValidacion(
                f"La fecha de vencimiento no puede superar {DIAS_PRESTAMO_MAXIMO} días a partir de hoy."
            )
        return value

    # ── Validaciones de lógica de negocio ─────────────────────────────────────

    def validate(self, attrs):
        libro = attrs.get('libro')
        ejemplar = attrs.get('ejemplar')
        socio = attrs.get('socio')

        # Exactamente uno de libro o ejemplar debe indicarse
        if not libro and not ejemplar:
            raise ErrorValidacion("Debes especificar un libro o un ejemplar específico.")
        if libro and ejemplar:
            raise ErrorValidacion("Especifica solo un libro o solo un ejemplar, no ambos.")

        # Socio con préstamos vencidos no puede pedir nuevo préstamo
        if socio and socio.tiene_prestamos_vencidos:
            raise SocioConPrestamosVencidos()

        if libro:
            self._validar_libro(libro, socio)
        if ejemplar:
            self._validar_ejemplar(ejemplar, socio)

        return attrs

    def _validar_libro(self, libro, socio):
        if libro.retirado:
            raise LibroRetirado(
                f"El libro '{libro.titulo}' ha sido retirado del catálogo."
            )
        activos_ids = Prestamo.objects.filter(
            fecha_devolucion__isnull=True
        ).values('ejemplar_id')
        disponibles = Ejemplar.objects.filter(
            libro=libro, retirado=False
        ).exclude(id__in=activos_ids)
        if not disponibles.exists():
            raise LibroSinEjemplares(
                f"'{libro.titulo}' no tiene ejemplares disponibles en este momento."
            )
        if socio:
            ya_tiene = Prestamo.objects.filter(
                socio=socio,
                ejemplar__libro=libro,
                fecha_devolucion__isnull=True,
            ).exists()
            if ya_tiene:
                raise PrestamoMismoLibro(
                    f"El socio '{socio.nombre_completo}' ya tiene en préstamo "
                    f"un ejemplar de '{libro.titulo}'."
                )

    def _validar_ejemplar(self, ejemplar, socio):
        if ejemplar.retirado:
            raise EjemplarRetirado(
                f"El ejemplar '{ejemplar.codigo}' ha sido retirado."
            )
        if ejemplar.libro.retirado:
            raise LibroRetirado(
                f"El libro al que pertenece el ejemplar '{ejemplar.codigo}' "
                "ha sido retirado del catálogo."
            )
        if socio:
            ya_tiene = Prestamo.objects.filter(
                socio=socio,
                ejemplar__libro=ejemplar.libro,
                fecha_devolucion__isnull=True,
            ).exists()
            if ya_tiene:
                raise PrestamoMismoLibro(
                    f"El socio '{socio.nombre_completo}' ya tiene en préstamo "
                    f"un ejemplar de '{ejemplar.libro.titulo}'."
                )

    def create(self, validated_data):
        """
        Corre dentro del transaction.atomic() de VistaPrestamo.create().
        Usa select_for_update() para bloquear filas y evitar condiciones de carrera.
        Re-valida con bloqueo para el caso de dos peticiones concurrentes que
        pasaron validate() simultáneamente.
        """
        socio = validated_data['socio']
        libro = validated_data.get('libro')
        ejemplar = validated_data.get('ejemplar')
        fecha_vencimiento = validated_data['fecha_vencimiento']
        notas = validated_data.get('notas', '')

        # Re-validar con bloqueo de fila
        socio = Socio.objects.select_for_update().get(pk=socio.pk)
        if not socio.activo:
            raise SocioInactivo(
                f"El socio '{socio.nombre_completo}' está inactivo."
            )
        if socio.tiene_prestamos_vencidos:
            raise SocioConPrestamosVencidos()

        if libro:
            libro = Libro.objects.select_for_update().get(pk=libro.pk)
            if libro.retirado:
                raise LibroRetirado(
                    f"El libro '{libro.titulo}' ha sido retirado del catálogo."
                )
            activos_ids = Prestamo.objects.filter(
                fecha_devolucion__isnull=True
            ).values('ejemplar_id')
            ejemplar = (
                Ejemplar.objects.select_for_update()
                .filter(libro=libro, retirado=False)
                .exclude(id__in=activos_ids)
                .first()
            )
            if not ejemplar:
                raise LibroSinEjemplares(
                    f"'{libro.titulo}' ya no tiene ejemplares disponibles. "
                    "Otro socio tomó el último disponible al mismo tiempo."
                )
        else:
            ejemplar = (
                Ejemplar.objects
                .select_related('libro')
                .select_for_update()
                .get(pk=ejemplar.pk)
            )
            if ejemplar.retirado:
                raise EjemplarRetirado(
                    f"El ejemplar '{ejemplar.codigo}' ha sido retirado."
                )
            if ejemplar.libro.retirado:
                raise LibroRetirado(
                    f"El libro '{ejemplar.libro.titulo}' ha sido retirado del catálogo."
                )
            if ejemplar.prestamos.filter(fecha_devolucion__isnull=True).exists():
                raise EjemplarNoDisponible(
                    f"El ejemplar '{ejemplar.codigo}' acaba de ser prestado a otro socio. "
                    "Por favor elige otro ejemplar disponible."
                )

        try:
            prestamo = Prestamo.objects.create(
                socio=socio,
                ejemplar=ejemplar,
                fecha_vencimiento=fecha_vencimiento,
                notas=notas,
            )
        except IntegrityError as exc:
            raise PrestamoConflictoConcurrente() from exc

        return prestamo
