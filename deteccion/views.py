from django.contrib.auth import authenticate
from rest_framework.authtoken.models import Token
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from .serializers import LoginSerializer, DetectarSerializer
from . import ocr


class LoginAdminView(APIView):
    """
    POST /api/deteccion/login/
    Devuelve un token de autenticación para usuarios con permisos de staff.
    Solo usuarios is_staff=True pueden obtener token.
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {'error': 'Credenciales incorrectas.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if not user.is_staff:
            return Response(
                {'error': 'Solo los administradores pueden usar esta función.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not user.is_active:
            return Response(
                {'error': 'Esta cuenta está desactivada.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        token, _ = Token.objects.get_or_create(user=user)
        return Response({'token': token.key, 'username': user.username})


class DetectarDocumentoView(APIView):
    """
    POST /api/deteccion/detectar/
    Recibe ambas caras de un DNI azul o DNI electronico.
    Devuelve los campos detectados mediante OCR.
    Requiere autenticación con token de admin.
    """
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request):
        serializer = DetectarSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        imagen_frente_file = (
            serializer.validated_data.get('imagen_frente')
            or serializer.validated_data.get('imagen')
        )
        imagen_reverso_file = serializer.validated_data.get('imagen_reverso')
        tipo_documento = serializer.validated_data['tipo_documento']

        # Validar tamaño máximo: 10 MB
        for imagen_file in (imagen_frente_file, imagen_reverso_file):
            if imagen_file.size > 10 * 1024 * 1024:
                return Response(
                    {'error': 'Cada imagen no puede superar los 10 MB.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            frente_bytes = imagen_frente_file.read()
            reverso_bytes = imagen_reverso_file.read()
            resultado = ocr.detectar(frente_bytes, tipo_documento, reverso_bytes)
        except RuntimeError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            return Response(
                {'error': f'Error inesperado al procesar el documento: {exc}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(resultado)
