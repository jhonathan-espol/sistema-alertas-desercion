from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv

load_dotenv()

from app import database, auth
from app.routes import auth as auth_routes, users as users_routes, alerts as alerts_routes

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Sistema de Alertas API",
    description="API para el sistema de alertas con autenticación y gestión de usuarios",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        os.getenv("FRONTEND_URL", "http://localhost:3000"),
        "https://*.vercel.app",
        "https://*.pages.dev",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router, prefix="/api/auth", tags=["auth"])
app.include_router(users_routes.router, prefix="/api/users", tags=["users"])
app.include_router(alerts_routes.router, prefix="/api/alerts", tags=["alerts"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "sistema-alertas-api"}
