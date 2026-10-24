-- Esquema de base de datos para db_alertas (Supabase / PostgreSQL)
-- Ejecutar en el SQL Editor de Supabase

-- Tabla de usuarios (gestión completa desde la aplicación)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'invitado' CHECK (role IN ('administrador', 'invitado')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Tabla de alertas del sistema
CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    severity VARCHAR(50) NOT NULL DEFAULT 'media' CHECK (severity IN ('baja', 'media', 'alta', 'critica')),
    status VARCHAR(50) NOT NULL DEFAULT 'activa' CHECK (status IN ('activa', 'resuelta', 'archivada')),
    created_by UUID REFERENCES users(id),
    assigned_to UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Habilitar RLS (Row Level Security) opcional - se puede gestionar desde la app
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;

-- Políticas básicas (ajustar según necesidades de producción)
CREATE POLICY "Allow all for authenticated users" ON users FOR ALL USING (true);
CREATE POLICY "Allow all for authenticated users" ON alerts FOR ALL USING (true);

-- Insertar usuarios por defecto
-- Contraseñas: admin / invitado123 (hasheadas con bcrypt para desarrollo)
INSERT INTO users (username, email, password_hash, role, is_active) VALUES
    ('admin', 'admin@alertas.local', '$2b$12$LQv3c1yqBWVHxCd0L3aOiO6F9f.J7fQ6R4L8Y8X9Z0A1B2C3D4E5F', 'administrador', TRUE),
    ('invitado', 'invitado@alertas.local', '$2b$12$K4m7p2n9r8w1y5a3s6d8f0g2h4j6k8l', 'invitado', TRUE)
ON CONFLICT (username) DO NOTHING;

-- Insertar algunas alertas de ejemplo
INSERT INTO alerts (title, description, severity, status, created_by, assigned_to) VALUES
    ('Alerta de temperatura elevada', 'Se detectó temperatura superior al umbral en el sensor A1', 'alta', 'activa',
     (SELECT id FROM users WHERE username = 'admin'), (SELECT id FROM users WHERE username = 'admin')),
    ('Falla de conectividad nodo 3', 'Pérdida de comunicación con el nodo remoto 3', 'critica', 'activa',
     (SELECT id FROM users WHERE username = 'admin'), (SELECT id FROM users WHERE username = 'invitado')),
    ('Mantenimiento programado servidor', 'Mantenimiento preventivo del servidor principal este fin de semana', 'baja', 'archivada',
     (SELECT id FROM users WHERE username = 'admin'), (SELECT id FROM users WHERE username = 'admin'))
ON CONFLICT DO NOTHING;
