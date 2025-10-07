"""Authentication routes for registering users, issuing JWTs, and managing sessions."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Response, Request, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    UserRegisterRequest,
    UserLoginRequest,
    AuthResponse,
    LogoutResponse,
    ErrorResponse
)
from src.services.auth_service import AuthService, AuthServiceValidationError
from src.config.database import get_session
from src.config.settings import get_settings
from src.models.user import User


# Initialize router
router = APIRouter(prefix="/auth", tags=["authentication"])

# Security scheme for Bearer token (auto_error=False to allow cookie fallback)
security = HTTPBearer(auto_error=False)


async def get_auth_service(db: AsyncSession = Depends(get_session)) -> AuthService:
    """Dependency to get AuthService instance."""
    return AuthService(db)  # Service now reads configuration from environment variables


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    auth_service: AuthService = Depends(get_auth_service),
    access_token: Optional[str] = Cookie(None)
) -> User:
    """
    Dependency to get current authenticated user from JWT token.

    Checks for token in this order:
    1. Authorization header (Bearer token) - for API calls
    2. Cookie (access_token) - for server-rendered pages

    Args:
        request: FastAPI request object
        credentials: HTTP Bearer token (optional)
        auth_service: Authentication service instance
        access_token: JWT token from cookie (optional)

    Returns:
        Authenticated User object

    Raises:
        HTTPException: If token is invalid, missing, or user not found
    """
    try:
        # Try to get token from header first
        token = None
        if credentials:
            token = credentials.credentials
        # Fallback to cookie
        elif access_token:
            token = access_token

        if not token:
            raise HTTPException(
                # status_code=status.HTTP_401_UNAUTHORIZED,
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                detail="No authentication token provided",
                headers={"WWW-Authenticate": "Bearer", "Location": "/login"}
            )

        # Validate token and get user
        user = await auth_service.validate_token(token)
        if not user:
            raise HTTPException(
                # status_code=status.HTTP_401_UNAUTHORIZED,
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer", "Location": "/login"}
            )
        return user
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            # status_code=status.HTTP_401_UNAUTHORIZED,
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer", "Location": "/login"}
        )

async def get_optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    access_token: Optional[str] = Cookie(None)
) -> Optional[User]:
    """
    Try to get current authenticated user, but don't fail if not authenticated.

    This replicates the logic from get_current_user but returns None instead of raising 401.

    Returns:
        User object if authenticated, None if not authenticated
    """
    from src.config.database import get_session
    from src.services.auth_service import AuthService

    # Try to get token from header first, then cookie
    token = None
    if credentials:
        token = credentials.credentials
    elif access_token:
        token = access_token

    if not token:
        return None

    # Validate token
    try:
        # Get database session (FastAPI will handle cleanup)
        async for db in get_session():
            auth_service = AuthService(db)
            user = await auth_service.validate_token(token)
            return user if user else None
    except Exception:
        return None


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user",
    description="Create a new user account with email and password",
    responses={
        201: {"description": "User registered successfully", "model": AuthResponse},
        400: {"description": "Validation error or invalid input", "model": ErrorResponse},
        409: {"description": "User already exists", "model": ErrorResponse},
        422: {"description": "Unprocessable input", "model": ErrorResponse},
    }
)
async def register(
    response: Response,
    user_data: UserRegisterRequest,
    auth_service: AuthService = Depends(get_auth_service)
) -> AuthResponse:
    """
    Register a new user account.

    Creates a new user with the provided email and password.
    Password is securely hashed using bcrypt before storage.
    Returns JWT access token for immediate authentication and sets cookie.
    """
    try:
        # Register user
        user, access_token = await auth_service.register_user(
            email=user_data.email,
            password=user_data.password
        )

        # Set HTTP-only cookie for server-rendered pages
        settings = get_settings()

        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            secure=settings.is_production,
            samesite="lax",
            max_age=1800
        )

        # Return authentication response
        return auth_service.create_auth_response(user, access_token)

    except AuthServiceValidationError as e:
        # Handle registration-specific errors
        if "already exists" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "user_exists", "message": str(e)}
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "registration_error", "message": str(e)}
            )
    except Exception as e:
        # Handle unexpected errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "internal_error", "message": "Registration failed"}
        )


@router.post(
    "/login",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate user",
    description="Authenticate user with email and password, returns JWT access token and sets cookie",
    responses={
        200: {"description": "Login successful", "model": AuthResponse},
        400: {"description": "Invalid request format", "model": ErrorResponse},
        401: {"description": "Invalid credentials", "model": ErrorResponse}
    }
)
async def login(
    response: Response,
    user_data: UserLoginRequest,
    auth_service: AuthService = Depends(get_auth_service)
) -> AuthResponse:
    """
    Authenticate user with email and password.

    Validates user credentials and returns JWT access token
    for accessing protected endpoints. Also sets an HTTP-only
    cookie for server-rendered page authentication.
    """
    try:
        # Authenticate user
        user, access_token = await auth_service.authenticate_user(
            email=user_data.email,
            password=user_data.password
        )

        # Set HTTP-only cookie for server-rendered pages
        # Use secure=False for development/testing over HTTP
        settings = get_settings()

        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,  # Not accessible via JavaScript (XSS protection)
            secure=settings.is_production,  # Only HTTPS in production, allow HTTP in dev/test
            samesite="lax", # CSRF protection
            max_age=1800    # 30 minutes (match JWT expiry)
        )

        # Return authentication response (for API clients and localStorage)
        return auth_service.create_auth_response(user, access_token)

    except AuthServiceValidationError as e:
        # Handle authentication errors
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_credentials", "message": str(e)}
        )
    except Exception as e:
        # Handle unexpected errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "internal_error", "message": "Authentication failed"}
        )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    status_code=status.HTTP_200_OK,
    summary="Logout user",
    description="Invalidate current JWT token, end user session, and clear cookie",
    responses={
        200: {"description": "Logout successful", "model": LogoutResponse},
        401: {"description": "Invalid or expired token", "model": ErrorResponse}
    }
)
async def logout(
    response: Response,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
    access_token: Optional[str] = Cookie(None)
) -> LogoutResponse:
    """
    Logout user by invalidating their current session.

    Revokes the JWT token and marks the associated session as inactive.
    Also clears the authentication cookie.
    """
    try:
        # Get token from cookie if available
        token = access_token

        if token:
            # Logout user (invalidate token/session)
            success = await auth_service.logout_user(token)
        else:
            success = True  # No token to invalidate

        # Clear the authentication cookie
        response.delete_cookie(
            key="access_token",
            httponly=True,
            secure=True,
            samesite="lax"
        )

        if success:
            return LogoutResponse(message="Successfully logged out")
        else:
            # Token was already invalid or expired
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_token", "message": "Invalid or expired token"}
            )

    except Exception as e:
        # Handle unexpected errors - still clear cookie and return success for security
        # (don't reveal whether token was valid or not)
        response.delete_cookie(key="access_token")
        return LogoutResponse(message="Logout completed")
