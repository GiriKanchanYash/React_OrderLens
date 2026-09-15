from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import AuthUser, Role, create_access_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    user_id: str
    password: str


USER_STORE: dict[str, dict[str, str | Role]] = {
    "admin.user": {"name": "Admin", "password": "orderlens", "role": "admin"},
    "sales.user": {"name": "Sales Operations", "password": "orderlens", "role": "sales_ops"},
    "planning.user": {"name": "Demand Planning", "password": "orderlens", "role": "planning"},
    "exec.user": {"name": "Executive", "password": "orderlens", "role": "exec"},
}


@router.post("/login")
def login(body: LoginRequest):
    from fastapi import HTTPException, status

    user_id = body.user_id.strip().lower()
    user = USER_STORE.get(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown user. Use admin.user, sales.user, planning.user, or exec.user",
        )
    if body.password.strip() != user["password"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password. Demo password is: orderlens",
        )
    role = user["role"]
    name = str(user["name"])
    token = create_access_token(name=name, role=role)  # type: ignore[arg-type]
    return {"access_token": token, "token_type": "bearer", "user": {"name": name, "role": role}}


@router.get("/me")
def me(user: AuthUser = Depends(get_current_user)):
    return {"name": user.name, "role": user.role}
