# Sistema de Alertas

Sistema de gestión de alertas inspirado en el diseño de Mori Studio, construido con **PostgreSQL**, **Python (FastAPI)** y **Next.js**.

## Arquitectura

```
┌─────────────┐      REST API      ┌──────────────┐      PostgreSQL      ┌─────────────┐
│   Next.js   │ ◄─────────────────► │  FastAPI     │ ◄───────────────────► │  Supabase   │
│  (Frontend) │      (JWT Auth)     │  (Backend)   │      (SQL)           │  (db_alertas)│
└─────────────┘                      └──────────────┘                      └─────────────┘
```

## Requisitos previos

- Node.js 18+
- Python 3.10+
- Cuenta de Supabase (base de datos `db_alertas` ya creada)

## Estructura del proyecto

```
sistema-alertas/
├── database/
│   └── schema.sql              # Esquema SQL para Supabase/PostgreSQL
├── backend/
│   ├── app/
│   │   ├── main.py             # Punto de entrada FastAPI
│   │   ├── database.py         # Conexión a PostgreSQL
│   │   ├── auth.py             # Autenticación JWT y bcrypt
│   │   └── routes/
│   │       ├── auth.py         # Login / Logout
│   │       ├── users.py        # CRUD de usuarios (admin)
│   │       └── alerts.py       # CRUD de alertas
│   ├── requirements.txt        # Dependencias Python
│   └── .env                    # Variables de entorno
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── login/          # Página de login
│   │   │   ├── dashboard/      # Dashboard principal
│   │   │   │   ├── page.tsx    # Dashboard
│   │   │   │   ├── entrenamiento/
│   │   │   │   ├── resultados/
│   │   │   │   ├── usuarios/   # Gestión de usuarios (admin)
│   │   │   │   └── configuracion/
│   │   │   └── layout.tsx      # Layout raíz
│   │   ├── components/
│   │   │   ├── Sidebar.tsx     # Sidebar con navegación
│   │   │   ├── Navbar.tsx      # Barra superior
│   │   │   ├── StatCard.tsx    # Tarjetas de estadísticas
│   │   │   └── ui/             # Componentes base (shadcn/ui)
│   │   └── lib/
│   │       ├── api.ts          # Cliente de API
│   │       ├── auth.ts         # Utilidades de auth (localStorage)
│   │       └── utils.ts        # Utilidades de formato
│   ├── .env.local              # Variables de entorno frontend
│   └── package.json
└── README.md
```

## Usuarios por defecto

| Usuario | Contraseña | Rol |
|---------|-----------|-----|
| admin | admin | Administrador |
| invitado | invitado123 | Invitado |

## Instalación y despliegue

### 1. Base de datos (Supabase)

1. Cree una base de datos llamada `db_alertas` en Supabase.
2. Ejecute el script `database/schema.sql` en el SQL Editor de Supabase.
3. Obtiene la `DATABASE_URL` de la configuración de Supabase.

### 2. Backend (Python/FastAPI)

```bash
cd backend
python -m venv venv
venv\Scripts/activate        # Windows
# source venv/bin/activate   # Linux/Mac

pip install -r requirements.txt

# Edite .env con su DATABASE_URL de Supabase
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev
```

La aplicación estará disponible en `http://localhost:3000`.

### 4. Despliegue a producción (Cloudflare + Supabase)

#### Supabase (Base de datos y hosting opcional del backend)
- La base de datos `db_alertas` reside en Supabase.
- Puede desplegar el backend FastAPI en Railway, Render, Fly.io o en una función de Supabase Edge.

#### Cloudflare Pages (Frontend Next.js)
1. Suba el código a GitHub.
2. Conecte el repositorio a **Cloudflare Pages**.
3. Configure el comando de build: `npm run build`
4. Variable de entorno: `NEXT_PUBLIC_API_URL` = URL de su backend en producción.
5. Despliegue.

## Funcionalidades

- ✅ Sistema de login con autenticación JWT
- ✅ Usuarios almacenados en PostgreSQL (no Supabase Auth)
- ✅ Usuario Administrador puede gestionar usuarios (CRUD)
- ✅ Cambio de contraseñas de cualquier usuario (solo admin)
- ✅ Dashboard con estadísticas y alertas recientes
- ✅ Sidebar: Dashboard, Entrenamiento, Resultados, Usuarios, Configuración
- ✅ Diseño inspirado en Mori Studio (limpio, verde esmeralda, tarjetas)
- ✅ Listo para producción en Cloudflare + Supabase

## Notas de seguridad

- Las contraseñas se hashean con **bcrypt** antes de almacenarse.
- La autenticación usa **JWT** con expirable configurable.
- En producción, cambie `SECRET_KEY` por una valor seguro y use HTTPS.
- El CORS está configurado para permitir el frontend.
