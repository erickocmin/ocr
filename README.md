# Biblioteca comunitaria

API REST y frontend sencillo para administrar libros, ejemplares fisicos, socios y prestamos de una biblioteca comunitaria.

## Requisitos

- Python 3.11+
- Node.js 20+
- Django
- Django REST Framework

## Ejecutar backend

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

La API queda disponible en `http://127.0.0.1:8000/api/`.

## Ejecutar frontend

En otra terminal:

```bash
cd frontend
npm install
npm run dev
```

El frontend queda disponible en `http://127.0.0.1:5173/`. Vite esta configurado para enviar `/api/...` al backend local en `http://127.0.0.1:8000`.

## Endpoints principales

- `GET /api/libros/`
- `POST /api/libros/`
- `PATCH /api/libros/{id}/`
- `GET /api/ejemplares/`
- `GET /api/ejemplares/?disponibles=true`
- `POST /api/ejemplares/`
- `PATCH /api/ejemplares/{id}/`
- `GET /api/prestamos/`
- `GET /api/prestamos/?vencidos=true`
- `POST /api/prestamos/`
- `POST /api/prestamos/{id}/devolver/`
- `GET /api/autores/`
- `POST /api/autores/`
- `GET /api/socios/`
- `POST /api/socios/`

Para crear un prestamo se puede enviar un `ejemplar` concreto o un `libro`. Si se envia `libro`, el servidor selecciona el primer ejemplar disponible. Si no hay ejemplares disponibles, responde `400` con un mensaje claro.

## Pruebas

```bash
python manage.py test
```

Las pruebas cubren la regla principal de disponibilidad, devoluciones, libros retirados, prestamos por libro, libros sin autores y filtro de prestamos vencidos.

## Decisiones de modelado

- Separe `Libro` de `Ejemplar` porque la biblioteca puede tener varias copias fisicas del mismo titulo.
- Modele autores con una relacion muchos-a-muchos porque un libro puede tener varios autores y un autor puede estar en varios libros.
- Un prestamo apunta a un `Ejemplar`, no a un `Libro`, para evitar prestar dos veces la misma copia fisica.
- Tambien permiti crear un prestamo enviando `libro` para cubrir el flujo de "prestar un libro"; el backend elige una copia disponible y mantiene la regla en el servidor.
- La devolucion se registra con `fecha_devolucion`; no se borra el prestamo para conservar el historial.
- `Libro` y `Ejemplar` tienen bandera `retirado` para mantener registros e historial cuando algo sale de la coleccion.
- Use `PROTECT` en relaciones historicas para evitar borrar datos usados por prestamos.
- Agregue una restriccion de base de datos para que solo exista un prestamo activo por ejemplar. La validacion de serializer da mensajes claros y la restriccion protege ante condiciones de carrera.
- SQLite es suficiente para la prueba y mantiene el proyecto facil de ejecutar.

