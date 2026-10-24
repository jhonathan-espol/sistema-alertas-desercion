from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional
from app import database, auth
from fastapi.security import OAuth2PasswordBearer
from datetime import datetime

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


class AlertOut(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    severity: str
    status: str
    created_by: Optional[str] = None
    assigned_to: Optional[str] = None
    created_at: str
    updated_at: str


class AlertCreate(BaseModel):
    title: str
    description: Optional[str] = None
    severity: str = "media"
    status: str = "activa"
    assigned_to: Optional[str] = None


class AlertUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[str] = None


def get_current_user(token: str = Depends(oauth2_scheme)):
    payload = auth.decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
        )
    return payload


def require_auth(user=Depends(get_current_user)):
    return user


@router.get("", response_model=List[AlertOut])
async def list_alerts(current_user=Depends(require_auth)):
    conn = database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT a.id, a.title, a.description, a.severity, a.status,
                          a.created_by, a.assigned_to, a.created_at, a.updated_at
                   FROM alerts a ORDER BY a.created_at DESC"""
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "description": r["description"],
            "severity": r["severity"],
            "status": r["status"],
            "created_by": str(r["created_by"]) if r["created_by"] else None,
            "assigned_to": str(r["assigned_to"]) if r["assigned_to"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else "",
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else "",
        }
        for r in rows
    ]


@router.post("", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
async def create_alert(alert: AlertCreate, current_user=Depends(require_auth)):
    conn = database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO alerts (title, description, severity, status, created_by, assigned_to)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   RETURNING id, title, description, severity, status, created_by, assigned_to, created_at, updated_at""",
                (
                    alert.title,
                    alert.description,
                    alert.severity,
                    alert.status,
                    current_user.get("user_id"),
                    alert.assigned_to,
                ),
            )
            new_alert = cur.fetchone()
            conn.commit()
    finally:
        conn.close()
    return {
        "id": str(new_alert["id"]),
        "title": new_alert["title"],
        "description": new_alert["description"],
        "severity": new_alert["severity"],
        "status": new_alert["status"],
        "created_by": str(new_alert["created_by"]) if new_alert["created_by"] else None,
        "assigned_to": str(new_alert["assigned_to"]) if new_alert["assigned_to"] else None,
        "created_at": new_alert["created_at"].isoformat() if new_alert["created_at"] else "",
        "updated_at": new_alert["updated_at"].isoformat() if new_alert["updated_at"] else "",
    }


@router.get("/{alert_id}", response_model=AlertOut)
async def get_alert(alert_id: str, current_user=Depends(require_auth)):
    conn = database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, title, description, severity, status, created_by, assigned_to, created_at, updated_at
                   FROM alerts WHERE id = %s""",
                (alert_id,),
            )
            alert = cur.fetchone()
    finally:
        conn.close()
    if not alert:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    return {
        "id": str(alert["id"]),
        "title": alert["title"],
        "description": alert["description"],
        "severity": alert["severity"],
        "status": alert["status"],
        "created_by": str(alert["created_by"]) if alert["created_by"] else None,
        "assigned_to": str(alert["assigned_to"]) if alert["assigned_to"] else None,
        "created_at": alert["created_at"].isoformat() if alert["created_at"] else "",
        "updated_at": alert["updated_at"].isoformat() if alert["updated_at"] else "",
    }


@router.put("/{alert_id}", response_model=AlertOut)
async def update_alert(alert_id: str, alert_data: AlertUpdate, current_user=Depends(require_auth)):
    conn = database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM alerts WHERE id = %s", (alert_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Alerta no encontrada")

            update_fields = []
            values = []
            if alert_data.title is not None:
                update_fields.append("title = %s")
                values.append(alert_data.title)
            if alert_data.description is not None:
                update_fields.append("description = %s")
                values.append(alert_data.description)
            if alert_data.severity is not None:
                update_fields.append("severity = %s")
                values.append(alert_data.severity)
            if alert_data.status is not None:
                update_fields.append("status = %s")
                values.append(alert_data.status)
            if alert_data.assigned_to is not None:
                update_fields.append("assigned_to = %s")
                values.append(alert_data.assigned_to)

            if not update_fields:
                raise HTTPException(status_code=400, detail="No hay campos para actualizar")

            update_fields.append("updated_at = NOW()")
            values.append(alert_id)

            query = f"UPDATE alerts SET {', '.join(update_fields)} WHERE id = %s RETURNING id, title, description, severity, status, created_by, assigned_to, created_at, updated_at"
            cur.execute(query, values)
            updated = cur.fetchone()
            conn.commit()
    finally:
        conn.close()
    return {
        "id": str(updated["id"]),
        "title": updated["title"],
        "description": updated["description"],
        "severity": updated["severity"],
        "status": updated["status"],
        "created_by": str(updated["created_by"]) if updated["created_by"] else None,
        "assigned_to": str(updated["assigned_to"]) if updated["assigned_to"] else None,
        "created_at": updated["created_at"].isoformat() if updated["created_at"] else "",
        "updated_at": updated["updated_at"].isoformat() if updated["updated_at"] else "",
    }


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(alert_id: str, current_user=Depends(require_auth)):
    conn = database.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM alerts WHERE id = %s", (alert_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Alerta no encontrada")
            cur.execute("DELETE FROM alerts WHERE id = %s", (alert_id,))
            conn.commit()
    finally:
        conn.close()
    return None
