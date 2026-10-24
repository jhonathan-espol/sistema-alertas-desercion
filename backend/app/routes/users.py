from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from app import database, auth
from fastapi.security import OAuth2PasswordBearer

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


class UserOut(BaseModel):
    id: str
    username: str
    email: str
    role: str
    is_active: bool
    created_at: str


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    role: str = "invitado"


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class PasswordChange(BaseModel):
    password: str


def get_current_user(token: str = Depends(oauth2_scheme)):
    payload = auth.decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
        )
    return payload


def require_admin(user=Depends(get_current_user)):
    if user.get("role") != "administrador":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de administrador",
        )
    return user


@router.get("", response_model=List[UserOut])
async def list_users(current_user=Depends(require_admin)):
    conn = database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, email, role, is_active, created_at FROM users ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "id": str(r["id"]),
            "username": r["username"],
            "email": r["email"],
            "role": r["role"],
            "is_active": r["is_active"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else "",
        }
        for r in rows
    ]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(user_data: UserCreate, current_user=Depends(require_admin)):
    conn = database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM users WHERE username = %s OR email = %s",
                (user_data.username, user_data.email),
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El usuario o email ya existe",
                )
            cur.execute(
                """INSERT INTO users (username, email, password_hash, role, is_active)
                   VALUES (%s, %s, %s, %s, %s)
                   RETURNING id, username, email, role, is_active, created_at""",
                (
                    user_data.username,
                    user_data.email,
                    auth.get_password_hash(user_data.password),
                    user_data.role,
                    True,
                ),
            )
            new_user = cur.fetchone()
            conn.commit()
    finally:
        conn.close()
    return {
        "id": str(new_user["id"]),
        "username": new_user["username"],
        "email": new_user["email"],
        "role": new_user["role"],
        "is_active": new_user["is_active"],
        "created_at": new_user["created_at"].isoformat() if new_user["created_at"] else "",
    }


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: str, current_user=Depends(require_admin)):
    conn = database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, email, role, is_active, created_at FROM users WHERE id = %s",
                (user_id,),
            )
            user = cur.fetchone()
    finally:
        conn.close()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {
        "id": str(user["id"]),
        "username": user["username"],
        "email": user["email"],
        "role": user["role"],
        "is_active": user["is_active"],
        "created_at": user["created_at"].isoformat() if user["created_at"] else "",
    }


@router.put("/{user_id}", response_model=UserOut)
async def update_user(user_id: str, user_data: UserUpdate, current_user=Depends(require_admin)):
    conn = database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Usuario no encontrado")

            update_fields = []
            values = []
            if user_data.email is not None:
                update_fields.append("email = %s")
                values.append(user_data.email)
            if user_data.role is not None:
                update_fields.append("role = %s")
                values.append(user_data.role)
            if user_data.is_active is not None:
                update_fields.append("is_active = %s")
                values.append(user_data.is_active)

            if not update_fields:
                raise HTTPException(status_code=400, detail="No hay campos para actualizar")

            update_fields.append("updated_at = NOW()")
            values.append(user_id)

            query = f"UPDATE users SET {', '.join(update_fields)} WHERE id = %s RETURNING id, username, email, role, is_active, created_at"
            cur.execute(query, values)
            updated = cur.fetchone()
            conn.commit()
    finally:
        conn.close()
    return {
        "id": str(updated["id"]),
        "username": updated["username"],
        "email": updated["email"],
        "role": updated["role"],
        "is_active": updated["is_active"],
        "created_at": updated["created_at"].isoformat() if updated["created_at"] else "",
    }


@router.post("/{user_id}/change-password")
async def change_password(user_id: str, pwd: PasswordChange, current_user=Depends(require_admin)):
    conn = database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Usuario no encontrado")
            cur.execute(
                "UPDATE users SET password_hash = %s, updated_at = NOW() WHERE id = %s",
                (auth.get_password_hash(pwd.password), user_id),
            )
            conn.commit()
    finally:
        conn.close()
    return {"message": "Contraseña actualizada correctamente"}


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str, current_user=Depends(require_admin)):
    conn = database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Usuario no encontrado")
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
            conn.commit()
    finally:
        conn.close()
    return None
