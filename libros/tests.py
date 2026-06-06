from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from libros.models import Autor, Ejemplar, Libro
from libros.serializers import LibroSerializer
from socios.models import Socio
from prestamos.models import Prestamo
from prestamos.serializers import CrearPrestamoSerializer


class LibroAPITests(APITestCase):
    def setUp(self):
        self.autor = Autor.objects.create(nombre="Ursula K. Le Guin")

    def test_rechaza_libro_sin_autores(self):
        resp = self.client.post(
            reverse("libro-list"),
            {"titulo": "Libro sin autor", "autores_ids": []},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_crea_libro_con_autor(self):
        resp = self.client.post(
            reverse("libro-list"),
            {"titulo": "Los Desposeídos", "autores_ids": [self.autor.id]},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["titulo"], "Los Desposeídos")

    def test_isbn_invalido_es_rechazado(self):
        resp = self.client.post(
            reverse("libro-list"),
            {"titulo": "Test", "autores_ids": [self.autor.id], "isbn": "123ABC"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("isbn", resp.data)

    def test_lista_libros_esta_paginada(self):
        for i in range(12):
            libro = Libro.objects.create(titulo=f"Libro {i:02d}")
            libro.autores.add(self.autor)

        resp = self.client.get(reverse("libro-list"))

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 12)
        self.assertEqual(resp.data["page"], 1)
        self.assertEqual(resp.data["total_pages"], 2)
        self.assertEqual(len(resp.data["results"]), 10)

    def test_pagina_fuera_de_rango_devuelve_lista_vacia(self):
        libro = Libro.objects.create(titulo="Libro único")
        libro.autores.add(self.autor)

        resp = self.client.get(reverse("libro-list"), {"page": 2})

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["total_pages"], 1)
        self.assertEqual(resp.data["page"], 2)
        self.assertEqual(resp.data["results"], [])

    def test_crear_libro_hace_rollback_si_falla_despues_de_guardar(self):
        def crear_y_fallar(serializer, validated_data):
            autores = validated_data.pop("autores", [])
            libro = Libro.objects.create(**validated_data)
            libro.autores.set(autores)
            raise RuntimeError("fallo forzado")

        with patch.object(LibroSerializer, "create", crear_y_fallar):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse("libro-list"),
                    {"titulo": "No debe quedar", "autores_ids": [self.autor.id]},
                    format="json",
                )

        self.assertFalse(Libro.objects.filter(titulo="No debe quedar").exists())


class PrestamoAPITests(APITestCase):
    def setUp(self):
        autor = Autor.objects.create(nombre="Gabriel García Márquez")
        self.libro = Libro.objects.create(titulo="Cien Años de Soledad")
        self.libro.autores.add(autor)
        self.ejemplar = Ejemplar.objects.create(libro=self.libro, codigo="EJ-001")
        self.socio = Socio.objects.create(nombre="Ana", correo="ana@example.com")
        self.vencimiento = timezone.now().date() + timedelta(days=7)

    def test_no_permite_prestar_ejemplar_ya_prestado(self):
        data = {"socio": self.socio.id, "ejemplar": self.ejemplar.id, "fecha_vencimiento": self.vencimiento}
        r1 = self.client.post(reverse("prestamo-list"), data, format="json")
        r2 = self.client.post(reverse("prestamo-list"), data, format="json")
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Prestamo.objects.count(), 1)

    def test_devolver_libera_ejemplar(self):
        prestamo = Prestamo.objects.create(
            socio=self.socio, ejemplar=self.ejemplar, fecha_vencimiento=self.vencimiento
        )
        r_dev = self.client.post(reverse("prestamo-devolver", args=[prestamo.id]))
        r_new = self.client.post(
            reverse("prestamo-list"),
            {"socio": self.socio.id, "ejemplar": self.ejemplar.id, "fecha_vencimiento": self.vencimiento + timedelta(7)},
            format="json",
        )
        self.assertEqual(r_dev.status_code, status.HTTP_200_OK)
        self.assertEqual(r_new.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Prestamo.objects.count(), 2)

    def test_no_permite_prestar_libro_retirado(self):
        self.libro.retirado = True
        self.libro.save()
        resp = self.client.post(
            reverse("prestamo-list"),
            {"socio": self.socio.id, "ejemplar": self.ejemplar.id, "fecha_vencimiento": self.vencimiento},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_prestar_por_libro_asigna_ejemplar_disponible(self):
        resp = self.client.post(
            reverse("prestamo-list"),
            {"socio": self.socio.id, "libro": self.libro.id, "fecha_vencimiento": self.vencimiento},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["ejemplar"], self.ejemplar.id)

    def test_no_permite_prestar_libro_sin_ejemplares_disponibles(self):
        Prestamo.objects.create(
            socio=self.socio, ejemplar=self.ejemplar, fecha_vencimiento=self.vencimiento
        )
        resp = self.client.post(
            reverse("prestamo-list"),
            {"socio": self.socio.id, "libro": self.libro.id, "fecha_vencimiento": self.vencimiento + timedelta(7)},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_filtra_prestamos_vencidos(self):
        vencido = Prestamo.objects.create(
            socio=self.socio,
            ejemplar=self.ejemplar,
            fecha_vencimiento=timezone.now().date() - timedelta(days=1),
        )
        otro = Ejemplar.objects.create(libro=self.libro, codigo="EJ-002")
        Prestamo.objects.create(
            socio=self.socio, ejemplar=otro, fecha_vencimiento=self.vencimiento
        )
        resp = self.client.get(reverse("prestamo-list"), {"vencidos": "true"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["id"], vencido.id)

    def test_no_permite_fecha_vencimiento_pasada(self):
        resp = self.client.post(
            reverse("prestamo-list"),
            {
                "socio": self.socio.id,
                "ejemplar": self.ejemplar.id,
                "fecha_vencimiento": timezone.now().date() - timedelta(days=1),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_permite_socio_inactivo_pedir_prestamo(self):
        self.socio.activo = False
        self.socio.save()
        resp = self.client.post(
            reverse("prestamo-list"),
            {"socio": self.socio.id, "ejemplar": self.ejemplar.id, "fecha_vencimiento": self.vencimiento},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_permite_retirar_libro_con_prestamo_activo(self):
        Prestamo.objects.create(
            socio=self.socio, ejemplar=self.ejemplar, fecha_vencimiento=self.vencimiento
        )
        resp = self.client.patch(
            reverse("libro-detail", args=[self.libro.id]),
            {"retirado": True},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_permite_retirar_ejemplar_con_prestamo_activo(self):
        Prestamo.objects.create(
            socio=self.socio, ejemplar=self.ejemplar, fecha_vencimiento=self.vencimiento
        )
        resp = self.client.patch(
            reverse("ejemplar-detail", args=[self.ejemplar.id]),
            {"retirado": True},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_crear_prestamo_hace_rollback_si_falla_despues_de_guardar(self):
        def crear_y_fallar(serializer, validated_data):
            prestamo = Prestamo.objects.create(
                socio=validated_data["socio"],
                ejemplar=validated_data["ejemplar"],
                fecha_vencimiento=validated_data["fecha_vencimiento"],
                notas=validated_data.get("notas", ""),
            )
            self.assertIsNotNone(prestamo.id)
            raise RuntimeError("fallo forzado")

        with patch.object(CrearPrestamoSerializer, "create", crear_y_fallar):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse("prestamo-list"),
                    {
                        "socio": self.socio.id,
                        "ejemplar": self.ejemplar.id,
                        "fecha_vencimiento": self.vencimiento,
                    },
                    format="json",
                )

        self.assertEqual(Prestamo.objects.count(), 0)
