from rest_framework import serializers

TIPOS_DOCUMENTO = ['DNI', 'CARNET_EXTRANJERIA']


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class DetectarSerializer(serializers.Serializer):
    imagen = serializers.ImageField()
    tipo_documento = serializers.ChoiceField(choices=TIPOS_DOCUMENTO)
