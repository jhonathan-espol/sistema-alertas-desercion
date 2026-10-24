from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from app import database, auth

router = APIRouter()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: dict


@router.post("/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    conn = database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, email, password_hash, role, is_active FROM users WHERE username = %s",
                (form_data.username,),
            )
            user = cur.fetchone()
    finally:
        conn.close()

    if not user or not auth.verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario inactivo",
        )

    access_token = auth.create_access_token(
        data={"sub": user["username"], "user_id": str(user["id"]), "role": user["role"]}
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": str(user["id"]),
            "username": user["username"],
            "email": user["email"],
            "role": user["role"],
        },
    }


@router.post("/logout")
async def logout():
    return {"message": "Sesión cerrada"}
