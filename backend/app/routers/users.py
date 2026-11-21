from fastapi import APIRouter, Depends

from app.dependencies import get_current_user, require_roles
from app.models import User, UserRole
from app.schemas import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return current_user


@router.get("/staff-area")
def staff_area(
    current_user: User = Depends(require_roles(UserRole.admissions_staff, UserRole.administrator)),
) -> dict[str, str]:
    return {"message": f"Access granted for {current_user.role}"}
