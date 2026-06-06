import re
from rest_framework import serializers
from biblioteca.exceptions import ErrorValidacion, SocioConPrestamosActivos
from .models import Socio

NOMBRE_RE = re.compile(r"^[a-zA-ZáéíóúÁÉÍÓÚüÜñÑ\s'\-\.]+$")


def _validar_nombre_propio(value, campo='El campo'):
    """Valida formato de nombre propio. Lanza ErrorValidacion si el formato es inválido."""
    value = value.strip()
    if not value:
        raise ErrorValidacion(f"{campo} no puede estar vacío.")
    if len(value) < 2:
        raise ErrorValidacion(f"{campo} debe tener al menos 2 caracteres.")
    if len(value) > 100:
        raise ErrorValidacion(f"{campo} no puede superar los 100 caracteres.")
    if not NOMBRE_RE.match(value):
        raise ErrorValidacion(
            f"{campo} solo puede contener letras, espacios, guiones y apóstrofes. "
            "No se permiten números ni caracteres especiales (@, #, $, %, etc.)."
        )
    if '  ' in value:
        raise ErrorValidacion(f"{campo} no puede contener espacios dobles consecutivos.")
    return value


class SocioSerializer(serializers.ModelSerializer):
    nombre_completo = serializers.CharField(read_only=True)
    prestamos_activos_count = serializers.SerializerMethodField()
    tiene_prestamos_vencidos = serializers.SerializerMethodField()

    class Meta:
        model = Socio
        fields = [
            'id', 'nombre', 'apellido', 'nombre_completo', 'correo',
            'telefono', 'direccion', 'activo', 'notas',
            'prestamos_activos_count', 'tiene_prestamos_vencidos',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_prestamos_activos_count(self, obj):
        return obj.prestamos_activos_count

    def get_tiene_prestamos_vencidos(self, obj):
        return obj.tiene_prestamos_vencidos


    def validate_nombre(self, value):
        return _validar_nombre_propio(value, 'El nombre')

    def validate_apellido(self, value):
        if not value or not value.strip():
            return ''
        return _validar_nombre_propio(value, 'El apellido')

    def validate_correo(self, value):
        value = value.lower().strip()
        if not value:
            raise ErrorValidacion("El correo electrónico es requerido.")
        if len(value) > 254:
            raise ErrorValidacion("El correo electrónico es demasiado largo (máx. 254 caracteres).")
        return value

    def validate_telefono(self, value):
        if not value or not value.strip():
            return ''
        cleaned = re.sub(r'[\s\-\(\)\+]', '', value)
        if not cleaned.isdigit():
            raise ErrorValidacion(
                "El teléfono solo puede contener dígitos, espacios, guiones y paréntesis."
            )
        if len(cleaned) < 7:
            raise ErrorValidacion("El teléfono debe tener al menos 7 dígitos.")
        if len(cleaned) > 15:
            raise ErrorValidacion("El teléfono no puede tener más de 15 dígitos.")
        return value.strip()

    def validate_direccion(self, value):
        if not value:
            return ''
        value = value.strip()
        if len(value) > 300:
            raise ErrorValidacion("La dirección no puede superar los 300 caracteres.")
        if re.search(r'[<>{}\[\]\\^~`]', value):
            raise ErrorValidacion("La dirección contiene caracteres no permitidos.")
        return value

    def validate(self, attrs):
        instance = self.instance

        nombre = attrs.get('nombre', instance.nombre if instance else '')
        apellido = attrs.get('apellido', instance.apellido if instance else '')
        if nombre and apellido and nombre.lower().strip() == apellido.lower().strip():
            raise ErrorValidacion("El nombre y el apellido no pueden ser idénticos.")

        activo = attrs.get('activo', instance.activo if instance else True)
        if not activo and instance and instance.activo:
            count = instance.prestamos_activos_count
            if count > 0:
                raise SocioConPrestamosActivos(
                    f"No se puede desactivar al socio porque tiene {count} "
                    f"préstamo(s) activo(s). Deben ser devueltos primero."
                )

        return attrs
