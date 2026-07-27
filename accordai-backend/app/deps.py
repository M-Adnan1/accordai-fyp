"""FastAPI dependencies for JWT authentication and role checks.

Tenant context on every protected route comes exclusively from the
authenticated user's client_id — never from caller-supplied parameters.
"""
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.security import decode_access_token
import app.crud as crud

# auto_error=False so we can return a clean 401 (not FastAPI's default 403)
# when the Authorization header is missing entirely.
bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise _unauthorized("Not authenticated")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token expired")
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid token")

    # Load the user fresh so deactivation and role changes take effect
    # immediately instead of living on in old tokens.
    user = await crud.get_user_by_id(db, int(payload["sub"]))
    if user is None or not user.is_active:
        raise _unauthorized("Account not found or deactivated")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user