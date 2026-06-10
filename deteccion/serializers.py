from rest_framework import serializers

TIPOS_DOCUMENTO = ['DNI', 'DNI_ELECTRONICO']


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class DetectarSerializer(serializers.Serializer):
    imagen = serializers.ImageField(required=False)
    imagen_frente = serializers.ImageField(required=False)
    imagen_reverso = serializers.ImageField(required=False)
    tipo_documento = serializers.ChoiceField(choices=TIPOS_DOCUMENTO)

    def validate(self, attrs):
        frente = attrs.get('imagen_frente') or attrs.get('imagen')
        reverso = attrs.get('imagen_reverso')
        if not frente:
            raise serializers.ValidationError({
                'imagen_frente': 'Sube la imagen frontal del documento de identidad.'
            })
        if not reverso:
            raise serializers.ValidationError({
                'imagen_reverso': 'Sube la imagen posterior del documento de identidad.'
            })
        return attrs
