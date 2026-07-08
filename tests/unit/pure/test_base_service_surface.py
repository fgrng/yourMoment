"""Pure unit tests for BaseService's shared surface."""

from src.services.auth_service import AuthService
from src.services.base_service import BaseService
from src.services.mymoment_credentials_service import MyMomentCredentialsService
from src.services.mymoment_session_service import MyMomentSessionService
from src.services.student_backup_service import StudentBackupService
from src.services.user_service import UserService


def test_base_service_dead_helpers_stay_removed() -> None:
    """Unused transaction and pagination helpers should not return."""
    for method_name in (
        "safe_commit",
        "safe_rollback",
        "safe_refresh",
        "handle_integrity_error",
        "execute_with_transaction",
        "validate_required_field",
        "get_paginated_results",
    ):
        assert not hasattr(BaseService, method_name)


def test_base_service_subclasses_import() -> None:
    """Known BaseService subclasses should still import cleanly."""
    assert issubclass(AuthService, BaseService)
    assert issubclass(UserService, BaseService)
    assert issubclass(MyMomentSessionService, BaseService)
    assert issubclass(MyMomentCredentialsService, BaseService)
    assert issubclass(StudentBackupService, BaseService)
