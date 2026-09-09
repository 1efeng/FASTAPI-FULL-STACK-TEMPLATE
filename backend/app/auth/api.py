from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm

from app.auth.schema import NewPassword, Token
from app.auth.service import AuthService
from app.core.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.core.response import Message
from app.integrations.email import send_password_recovery_email
from app.user.schema import UserPublic

router = APIRouter(tags=["login"])


def get_auth_service(db: SessionDep) -> AuthService:
    return AuthService(db)


@router.post("/login/access-token")
async def login_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    svc: AuthService = Depends(get_auth_service),
) -> Token:
    user = await svc.authenticate(email=form_data.username, password=form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return Token(access_token=svc.create_access_token(user.id))


@router.post("/login/test-token", response_model=UserPublic)
async def test_token(current_user: CurrentUser) -> Any:
    return current_user


@router.post("/password-recovery/{email}")
async def recover_password(
    email: str,
    background_tasks: BackgroundTasks,
    svc: AuthService = Depends(get_auth_service),
) -> Message:
    email_to = await svc.recover_password(email)
    if email_to:
        background_tasks.add_task(
            send_password_recovery_email, email_to=email_to, email=email
        )
    return Message(
        message="If that email is registered, we sent a password recovery link"
    )


@router.post("/reset-password/")
async def reset_password(
    body: NewPassword, svc: AuthService = Depends(get_auth_service)
) -> Message:
    await svc.reset_password(token=body.token, new_password=body.new_password)
    return Message(message="Password updated successfully")


@router.post(
    "/password-recovery-html-content/{email}",
    dependencies=[Depends(get_current_active_superuser)],
    response_class=HTMLResponse,
)
async def recover_password_html_content(
    email: str, svc: AuthService = Depends(get_auth_service)
) -> Any:
    email_data = await svc.password_recovery_html(email)
    if not email_data:
        raise HTTPException(
            status_code=404,
            detail="The user with this username does not exist in the system.",
        )
    return HTMLResponse(
        content=email_data.html_content, headers={"subject": email_data.subject}
    )
