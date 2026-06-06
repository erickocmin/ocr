import re

from django.utils import timezone
from rest_framework import serializers

from biblioteca.exceptions import (
    CodigoEjemplarDuplicado,
    EjemplarCodigoCambio,
    EjemplarConPrestamoActivo,
    EjemplarReasignacion,
    ErrorValidacion,
    LibroConPrestamosActivos,
)
from .models import Autor, Ejemplar, EstadoEjemplar, Libro

NOMBRE_RE = re.compile(r"^[a-zA-ZáéíóúÁÉÍÓÚüÜñÑ\s'\-\.]+$")


def _validar_nombre_propio(value, campo='El campo'):
    """Valida formato de nombre propio. Lanza ErrorValidacion si el formato es inválido."""
    value = value.strip()
    if not value:
        raise ErrorValidacion(f"{campo} no puede estar vacío.")
    if len(value) < 2:
        raise ErrorValidacion(f"{campo} debe tener al menos 2 caracteres.")
    if len(value) > 150:
        raise ErrorValidacion(f"{campo} no puede superar los 150 caracteres.")
    if not NOMBRE_RE.match(value):
        raise ErrorValidacion(
            f"{campo} solo puede contener letras, espacios, guiones y apóstrofes. "
            "No se permiten números ni caracteres especiales."
        )
    if '  ' in value:
        raise ErrorValidacion(f"{campo} no puede tener espacios dobles consecutivos.")
    return value


class AutorSerializer(serializers.ModelSerializer):
    libros_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Autor
        fields = ['id', 'nombre', 'libros_count', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_libros_count(self, obj):
        return obj.libros.count()

    def validate_nombre(self, value):
        return _validar_nombre_propio(value, 'El nombre del autor')


class LibroSerializer(serializers.ModelSerializer):
    autores = AutorSerializer(many=True, read_only=True)
    autores_ids = serializers.PrimaryKeyRelatedField(
        queryset=Autor.objects.all(),
        many=True,
        write_only=True,
        source='autores',
        required=False,
    )
    total_ejemplares = serializers.SerializerMethodField()
    ejemplares_disponibles = serializers.SerializerMethodField()

    class Meta:
        model = Libro
        fields = [
            'id', 'titulo', 'autores', 'autores_ids', 'isbn', 'genero',
            'anio_publicacion', 'retirado', 'fecha_retiro', 'notas',
            'total_ejemplares', 'ejemplares_disponibles',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['fecha_retiro', 'created_at', 'updated_at']

    def get_total_ejemplares(self, obj):
        return obj.total_ejemplares

    def get_ejemplares_disponibles(self, obj):
        return obj.ejemplares_disponibles


    def validate_titulo(self, value):
        value = value.strip()
        if not value:
            raise ErrorValidacion("El título no puede estar vacío.")
        if len(value) < 2:
            raise ErrorValidacion("El título debe tener al menos 2 caracteres.")
        if len(value) > 200:
            raise ErrorValidacion("El título no puede superar los 200 caracteres.")
        return value

    def validate_isbn(self, value):
        if not value or not value.strip():
            return None
        value = value.strip().replace('-', '').replace(' ', '')
        if not re.match(r'^\d{10}(\d{3})?$', value):
            raise ErrorValidacion(
                "El ISBN debe contener exactamente 10 o 13 dígitos numéricos."
            )
        return value

    def validate_genero(self, value):
        if not value:
            return value
        value = value.strip()
        if len(value) > 100:
            raise ErrorValidacion("El género no puede superar los 100 caracteres.")
        if re.search(r'[<>{}\[\]\\|^~`]', value):
            raise ErrorValidacion("El género contiene caracteres no permitidos.")
        return value

    def validate_anio_publicacion(self, value):
        if value is None:
            return value
        anio_actual = timezone.now().year
        if value < 1000:
            raise ErrorValidacion("El año de publicación debe ser mayor a 1000.")
        if value > anio_actual:
            raise ErrorValidacion(
                f"El año de publicación no puede ser mayor al año actual ({anio_actual})."
            )
        return value

    def validate_autores(self, value):
        if not value:
            raise ErrorValidacion("El libro debe tener al menos un autor.")
        if len(value) > 20:
            raise ErrorValidacion("Un libro no puede tener más de 20 autores registrados.")
        return value


    def validate(self, attrs):
        instance = self.instance

        if instance is None and not attrs.get('autores'):
            raise ErrorValidacion("El libro debe tener al menos un autor.")

        # No se puede retirar un libro que tiene préstamos activos
        retirado_nuevo = attrs.get('retirado', instance.retirado if instance else False)
        if retirado_nuevo and instance and not instance.retirado:
            if instance.tiene_prestamos_activos():
                raise LibroConPrestamosActivos()

        return attrs

    def create(self, validated_data):
        autores = validated_data.pop('autores', [])
        libro = Libro.objects.create(**validated_data)
        libro.autores.set(autores)
        return libro

    def update(self, instance, validated_data):
        autores = validated_data.pop('autores', None)

        retirado = validated_data.get('retirado', instance.retirado)
        if retirado and not instance.retirado:
            validated_data['fecha_retiro'] = timezone.now()
        elif not retirado and instance.retirado:
            validated_data['fecha_retiro'] = None

        instance = super().update(instance, validated_data)

        if autores is not None:
            instance.autores.set(autores)

        return instance


class EjemplarSerializer(serializers.ModelSerializer):
    libro_titulo = serializers.CharField(source='libro.titulo', read_only=True)
    disponible = serializers.SerializerMethodField()
    estado_display = serializers.CharField(source='get_estado_display', read_only=True)

    class Meta:
        model = Ejemplar
        fields = [
            'id', 'libro', 'libro_titulo', 'codigo', 'estado', 'estado_display',
            'retirado', 'fecha_retiro', 'notas', 'disponible',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['fecha_retiro', 'created_at', 'updated_at']
        validators = []

    def get_disponible(self, obj):
        return obj.disponible


    def validate_codigo(self, value):
        value = value.strip().upper()
        if not value:
            raise ErrorValidacion("El código no puede estar vacío.")
        if len(value) > 30:
            raise ErrorValidacion("El código no puede superar los 30 caracteres.")
        if not re.match(r'^[A-Z0-9\-_\.]+$', value):
            raise ErrorValidacion(
                "El código solo puede contener letras, números, guiones, puntos y guiones bajos."
            )
        return value

    def validate_estado(self, value):
        estados_validos = [e.value for e in EstadoEjemplar]
        if value not in estados_validos:
            raise ErrorValidacion(
                f"Estado físico inválido. Valores aceptados: {', '.join(estados_validos)}."
            )
        return value


    def validate(self, attrs):
        instance = self.instance

        libro = attrs.get('libro', instance.libro if instance else None)
        codigo = attrs.get('codigo', instance.codigo if instance else None)

        if instance and 'libro' in attrs and attrs['libro'] != instance.libro:
            raise EjemplarReasignacion()

        if libro and codigo:
            qs = Ejemplar.objects.filter(libro=libro, codigo=codigo)
            if instance:
                qs = qs.exclude(pk=instance.pk)
            if qs.exists():
                raise CodigoEjemplarDuplicado(
                    f'El libro "{libro.titulo}" ya tiene un ejemplar con el código "{codigo}".'
                )

        if instance and 'codigo' in attrs and attrs['codigo'] != instance.codigo:
            if instance.prestamos.exists():
                raise EjemplarCodigoCambio()

        retirado_nuevo = attrs.get('retirado', instance.retirado if instance else False)
        if retirado_nuevo and instance and not instance.retirado:
            if instance.tiene_prestamo_activo():
                raise EjemplarConPrestamoActivo()

        return attrs

    def update(self, instance, validated_data):
        retirado = validated_data.get('retirado', instance.retirado)
        if retirado and not instance.retirado:
            validated_data['fecha_retiro'] = timezone.now()
        elif not retirado and instance.retirado:
            validated_data['fecha_retiro'] = None
        return super().update(instance, validated_data)
