"""Server-rendered routes that power the yourMoment dashboard and settings UI."""

from fastapi import APIRouter, Request, Depends, HTTPException, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os
import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc

from src.api.auth import get_current_user, get_optional_user
from src.models.user import User
from src.config.database import get_session
from src.config.settings import get_settings
from src.services.auth_service import AuthService, AuthServiceValidationError, AuthServiceError
from src.services.mymoment_credentials_service import MyMomentCredentialsService
from src.services.prompt_service import PromptService
from src.models.ai_comment import AIComment
from src.services.prompt_placeholders import SUPPORTED_PLACEHOLDERS

# Configure templates
templates_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=templates_dir)

router = APIRouter(
    tags=["Web Interface"],
    include_in_schema=False  # Don't include in API docs
)

@router.get("/", response_class=HTMLResponse)
async def home(request: Request, current_user: Optional[User] = Depends(get_optional_user)):
    """Home page - redirect to dashboard if logged in, otherwise show landing."""
    if current_user:
          return RedirectResponse(url="/dashboard", status_code=302)

    return templates.TemplateResponse("simple_login.html", {
        "request": request,
        "current_user": current_user,
        "is_authenticated": current_user is not None
    })



@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, current_user: Optional[User] = Depends(get_optional_user)):
    """Login page - redirect to dashboard if already authenticated."""
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=302)

    return templates.TemplateResponse("simple_login.html", {
        "request": request,
        "current_user": None,
        "is_authenticated": False,
        "error_message": None,
        "form_email": ""
    })


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: AsyncSession = Depends(get_session)
):
    """Handle login form submission via standard POST."""
    auth_service = AuthService(session)

    try:
        user, access_token = await auth_service.authenticate_user(
            email=email,
            password=password
        )
    except AuthServiceValidationError as exc:
        return templates.TemplateResponse(
            "simple_login.html",
            {
                "request": request,
                "current_user": None,
                "is_authenticated": False,
                "error_message": str(exc),
                "form_email": email,
            },
            status_code=400
        )
    except AuthServiceError:
        return templates.TemplateResponse(
            "simple_login.html",
            {
                "request": request,
                "current_user": None,
                "is_authenticated": False,
                "error_message": "Unable to sign in. Please try again.",
                "form_email": email,
            },
            status_code=400
        )

    response = RedirectResponse(url="/dashboard", status_code=302)

    settings = get_settings()
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=auth_service.token_expiry_minutes * 60
    )

    return response


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, current_user: Optional[User] = Depends(get_optional_user)):
    """Registration page - redirect to dashboard if already authenticated."""
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=302)

    return templates.TemplateResponse("simple_register.html", {
        "request": request,
        "current_user": None,
        "is_authenticated": False,
        "error_message": None,
        "form_email": ""
    })


@router.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    agree_terms: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_session)
):
    """Handle registration form submission via standard POST."""
    if not agree_terms:
        return templates.TemplateResponse(
            "simple_register.html",
            {
                "request": request,
                "current_user": None,
                "is_authenticated": False,
                "error_message": "You must accept the Terms of Service to continue.",
                "form_email": email,
            },
            status_code=400
        )

    auth_service = AuthService(session)

    try:
        user, access_token = await auth_service.register_user(
            email=email,
            password=password
        )
    except AuthServiceValidationError as exc:
        return templates.TemplateResponse(
            "simple_register.html",
            {
                "request": request,
                "current_user": None,
                "is_authenticated": False,
                "error_message": str(exc),
                "form_email": email,
            },
            status_code=400
        )
    except AuthServiceError:
        return templates.TemplateResponse(
            "simple_register.html",
            {
                "request": request,
                "current_user": None,
                "is_authenticated": False,
                "error_message": "Unable to create account. Please try again.",
                "form_email": email,
            },
            status_code=400
        )

    response = RedirectResponse(url="/dashboard", status_code=302)

    settings = get_settings()
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=auth_service.token_expiry_minutes * 60
    )

    return response


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: User = Depends(get_current_user)):
    """Main dashboard - requires authentication via cookie or header."""
    return templates.TemplateResponse("simple_dashboard.html", {
        "request": request,
        "user": user,
        "current_user": user,
        "is_authenticated": True
    })


@router.get("/profile", response_class=HTMLResponse)
async def profile(request: Request, user: User = Depends(get_current_user)):
    """User profile page."""
    return templates.TemplateResponse("simple_profile.html", {
        "request": request,
        "user": user,
        "current_user": user,
        "is_authenticated": True
    })


@router.get("/processes", response_class=HTMLResponse)
async def processes(request: Request, user: User = Depends(get_current_user)):
    """Monitoring processes page."""
    return templates.TemplateResponse("monitoring_processes/index.html", {
        "request": request,
        "user": user,
        "current_user": user,
        "is_authenticated": True
    })


@router.get("/processes/new", response_class=HTMLResponse)
async def new_process(request: Request, user: User = Depends(get_current_user)):
    """Create new monitoring process page."""
    return templates.TemplateResponse("monitoring_processes/form.html", {
        "request": request,
        "user": user,
        "current_user": user,
        "is_authenticated": True,
        "process_id": None
    })


@router.get("/processes/{process_id}/edit", response_class=HTMLResponse)
async def edit_process(request: Request, process_id: str, user: User = Depends(get_current_user)):
    """Edit monitoring process page."""
    return templates.TemplateResponse("monitoring_processes/form.html", {
        "request": request,
        "user": user,
        "current_user": user,
        "is_authenticated": True,
        "process_id": process_id
    })


@router.get("/articles", response_class=HTMLResponse)
async def articles(request: Request, user: User = Depends(get_current_user)):
    """Articles browsing page."""
    return templates.TemplateResponse("articles/index.html", {
        "request": request,
        "user": user
    })


@router.get("/articles/{article_id}", response_class=HTMLResponse)
async def article_detail(request: Request, article_id: str, user: User = Depends(get_current_user)):
    """Article detail page."""
    return templates.TemplateResponse("articles/detail.html", {
        "request": request,
        "user": user,
        "article_id": article_id
    })


@router.get("/articles/{article_id}/comments", response_class=HTMLResponse)
async def article_comments(request: Request, article_id: str, user: User = Depends(get_current_user)):
    """Article comments page."""
    return templates.TemplateResponse("articles/comments.html", {
        "request": request,
        "user": user,
        "article_id": article_id
    })


@router.get("/ai-comments", response_class=HTMLResponse)
async def ai_comments_index(
    request: Request,
    user: User = Depends(get_current_user)
):
    """AI comments archive page (client-side rendered)."""
    return templates.TemplateResponse("ai_comments/index.html", {
        "request": request,
        "user": user,
        "current_user": user,
        "is_authenticated": True
    })


@router.get("/processes/{process_id}/ai-comments", response_class=HTMLResponse)
async def process_ai_comments(
    request: Request,
    process_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """AI comments for a specific monitoring process (client-side rendered)."""
    # Validate UUID format
    try:
        process_uuid = uuid.UUID(process_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid process ID format")

    # Verify process exists and belongs to user
    from src.models.monitoring_process import MonitoringProcess
    process_stmt = select(MonitoringProcess).where(
        and_(
            MonitoringProcess.id == process_uuid,
            MonitoringProcess.user_id == user.id
        )
    )
    process_result = await session.execute(process_stmt)
    process = process_result.scalar_one_or_none()

    if not process:
        raise HTTPException(status_code=404, detail="Process not found")

    return templates.TemplateResponse("ai_comments/index.html", {
        "request": request,
        "user": user,
        "current_user": user,
        "is_authenticated": True
    })


@router.get("/ai-comments/{comment_id}", response_class=HTMLResponse)
async def ai_comment_detail(request: Request, comment_id: str, user: User = Depends(get_current_user)):
    """AI comment detail page."""
    return templates.TemplateResponse("ai_comments/detail.html", {
        "request": request,
        "user": user,
        "current_user": user,
        "is_authenticated": True,
        "comment_id": comment_id
    })


# Settings pages
@router.get("/settings", response_class=HTMLResponse)
async def settings(request: Request, user: User = Depends(get_current_user)):
    """Settings page - redirect to profile."""
    return RedirectResponse(url="/profile")


@router.get("/settings/llm-providers", response_class=HTMLResponse)
async def llm_providers_index(request: Request, user: User = Depends(get_current_user)):
    """LLM providers listing page."""
    return templates.TemplateResponse("llm_providers/index.html", {
        "request": request,
        "user": user,
        "current_user": user,
        "is_authenticated": True
    })


@router.get("/settings/llm-providers/new", response_class=HTMLResponse)
async def llm_providers_new(request: Request, user: User = Depends(get_current_user)):
    """Create LLM provider page."""
    return templates.TemplateResponse("llm_providers/form.html", {
        "request": request,
        "user": user,
        "current_user": user,
        "is_authenticated": True,
        "provider_id": None
    })


@router.get("/settings/llm-providers/{provider_id}/edit", response_class=HTMLResponse)
async def llm_providers_edit(request: Request, provider_id: str, user: User = Depends(get_current_user)):
    """Edit LLM provider page."""
    return templates.TemplateResponse("llm_providers/form.html", {
        "request": request,
        "user": user,
        "current_user": user,
        "is_authenticated": True,
        "provider_id": provider_id
    })


@router.get("/settings/mymoment-credentials", response_class=HTMLResponse)
async def mymoment_credentials_settings(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """myMoment credentials settings page."""
    service = MyMomentCredentialsService(session)
    credentials = await service.get_user_credentials(user.id)

    credential_view = []
    for cred in credentials:
        try:
            username = cred.username
        except Exception:
            username = "(decryption failed)"

        credential_view.append({
            "id": str(cred.id),
            "name": cred.name,
            "username": username,
            "is_active": cred.is_active,
            "created_at": cred.created_at,
            "last_used": cred.last_used,
        })

    return templates.TemplateResponse("mymoment_credentials/index.html", {
        "request": request,
        "user": user,
        "current_user": user,
        "is_authenticated": True,
        "credentials": credential_view,
    })


@router.get("/settings/mymoment-credentials/new", response_class=HTMLResponse)
async def new_mymoment_credential(request: Request, user: User = Depends(get_current_user)):
    """Add new myMoment credential page."""
    return templates.TemplateResponse("mymoment_credentials/form.html", {
        "request": request,
        "user": user,
        "current_user": user,
        "is_authenticated": True,
        "credential_id": None
    })


@router.get("/settings/mymoment-credentials/{credential_id}/edit", response_class=HTMLResponse)
async def edit_mymoment_credential(request: Request, credential_id: str, user: User = Depends(get_current_user)):
    """Edit myMoment credential page."""
    return templates.TemplateResponse("mymoment_credentials/form.html", {
        "request": request,
        "user": user,
        "current_user": user,
        "is_authenticated": True,
        "credential_id": credential_id
    })

@router.get("/settings/prompt-templates", response_class=HTMLResponse)
async def prompt_templates_index(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Prompt templates listing page."""
    service = PromptService(session)

    user_templates = await service.list_templates(
        user_id=user.id,
        category="USER",
        active_only=False,
        limit=200
    )

    system_templates = await service.list_templates(
        category="SYSTEM",
        active_only=True,
        limit=200
    )

    def serialize_template(template):
        return {
            "id": str(template.id),
            "name": template.name,
            "description": template.description,
            "system_prompt": template.system_prompt,
            "user_prompt_template": template.user_prompt_template,
            "category": template.category,
            "is_active": template.is_active,
            "created_at": template.created_at,
        }

    context_user_templates = [serialize_template(tpl) for tpl in user_templates]
    context_system_templates = [serialize_template(tpl) for tpl in system_templates]

    placeholders = list(SUPPORTED_PLACEHOLDERS.values())

    return templates.TemplateResponse("prompt_templates/index.html", {
        "request": request,
        "user": user,
        "current_user": user,
        "is_authenticated": True,
        "user_templates": context_user_templates,
        "system_templates": context_system_templates,
        "placeholders": placeholders
    })


@router.get("/settings/prompt-templates/new", response_class=HTMLResponse)
async def prompt_templates_new(request: Request, user: User = Depends(get_current_user)):
    """Create prompt template page."""
    placeholders = list(SUPPORTED_PLACEHOLDERS.values())

    return templates.TemplateResponse("prompt_templates/form.html", {
        "request": request,
        "user": user,
        "current_user": user,
        "is_authenticated": True,
        "template_id": None,
        "placeholders": placeholders
    })


@router.get("/settings/prompt-templates/{template_id}/edit", response_class=HTMLResponse)
async def prompt_templates_edit(request: Request, template_id: str, user: User = Depends(get_current_user)):
    """Edit prompt template page."""
    placeholders = list(SUPPORTED_PLACEHOLDERS.values())

    return templates.TemplateResponse("prompt_templates/form.html", {
        "request": request,
        "user": user,
        "current_user": user,
        "is_authenticated": True,
        "template_id": template_id,
        "placeholders": placeholders
    })

# Error pages
@router.get("/error", response_class=HTMLResponse)
async def error_page(request: Request):
    """Generic error page."""
    return templates.TemplateResponse("auth/login.html", {
        "request": request,
        "error": "An error occurred"
    })


@router.get("/unauthorized", response_class=HTMLResponse)
async def unauthorized_page(request: Request):
    """Unauthorized access page."""
    return templates.TemplateResponse("auth/login.html", {
        "request": request,
        "error": "Please log in to access this page"
    })
