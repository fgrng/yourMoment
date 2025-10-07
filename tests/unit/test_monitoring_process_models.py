"""Unit tests for monitoring process related models."""

import uuid
from datetime import datetime, timedelta

from src.models.monitoring_process import MonitoringProcess
from src.models.monitoring_process_login import MonitoringProcessLogin
from src.models.monitoring_process_prompt import MonitoringProcessPrompt
from src.models.prompt_template import PromptTemplate
from src.models.mymoment_login import MyMomentLogin


class TestMonitoringProcess:
    """Tests for MonitoringProcess helper properties."""

    def test_duration_exceeded_detects_overrun(self):
        process = MonitoringProcess(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            name="Daily monitor",
            max_duration_minutes=30,
            started_at=datetime.utcnow() - timedelta(minutes=31),
            status="running",
        )

        assert process.duration_exceeded is True

    def test_duration_exceeded_false_when_not_running(self):
        process = MonitoringProcess(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            name="Idle monitor",
            max_duration_minutes=30,
            started_at=datetime.utcnow() - timedelta(minutes=31),
            status="created",
        )

        assert process.duration_exceeded is False

    def test_can_start_requires_correct_state(self):
        process = MonitoringProcess(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            name="Monitor",
            status="created",
            is_active=True,
        )

        assert process.can_start is True

        process.status = "running"
        assert process.can_start is False

        process.status = "stopped"
        process.is_active = False
        assert process.can_start is False

    def test_error_message_only_for_failed_status(self):
        process = MonitoringProcess(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            name="Monitor",
            status="running",
            errors_encountered=2,
        )

        assert process.error_message is None

        process.status = "failed"
        process.errors_encountered = 3
        assert process.error_message == "Process failed after 3 errors"

    def test_expires_at_uses_max_duration(self):
        started = datetime.utcnow() - timedelta(minutes=5)
        process = MonitoringProcess(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            name="Monitor",
            status="running",
            started_at=started,
            max_duration_minutes=45,
        )

        assert process.expires_at == started + timedelta(minutes=45)

    def test_prompt_template_ids_filters_active_prompts(self):
        active_id = uuid.uuid4()
        inactive_id = uuid.uuid4()
        process_id = uuid.uuid4()
        process = MonitoringProcess(
            id=process_id,
            user_id=uuid.uuid4(),
            name="Monitor",
        )
        process.monitoring_process_prompts = [
            MonitoringProcessPrompt(
                monitoring_process_id=process_id,
                prompt_template_id=active_id,
                is_active=True,
            ),
            MonitoringProcessPrompt(
                monitoring_process_id=process_id,
                prompt_template_id=inactive_id,
                is_active=False,
            ),
        ]

        assert process.prompt_template_ids == [active_id]

    def test_mymoment_login_ids_filters_active_logins(self):
        login_id = uuid.uuid4()
        process_id = uuid.uuid4()
        process = MonitoringProcess(
            id=process_id,
            user_id=uuid.uuid4(),
            name="Monitor",
        )
        process.monitoring_process_logins = [
            MonitoringProcessLogin(
                monitoring_process_id=process_id,
                mymoment_login_id=login_id,
                is_active=True,
            ),
            MonitoringProcessLogin(
                monitoring_process_id=process_id,
                mymoment_login_id=uuid.uuid4(),
                is_active=False,
            ),
        ]

        assert process.mymoment_login_ids == [login_id]

    def test_get_associated_prompts_returns_only_active_objects(self):
        process_id = uuid.uuid4()
        active_prompt = PromptTemplate(
            id=uuid.uuid4(),
            name="Active",
            system_prompt="sys",
            user_prompt_template="tmpl",
            category="USER",
            user_id=uuid.uuid4(),
        )
        inactive_prompt = PromptTemplate(
            id=uuid.uuid4(),
            name="Inactive",
            system_prompt="sys",
            user_prompt_template="tmpl",
            category="USER",
            user_id=uuid.uuid4(),
        )
        process = MonitoringProcess(
            id=process_id,
            user_id=uuid.uuid4(),
            name="Monitor",
        )
        process.monitoring_process_prompts = [
            MonitoringProcessPrompt(
                monitoring_process_id=process_id,
                prompt_template=active_prompt,
                is_active=True,
            ),
            MonitoringProcessPrompt(
                monitoring_process_id=process_id,
                prompt_template=inactive_prompt,
                is_active=False,
            ),
        ]

        assert process.get_associated_prompts() == [active_prompt]

    def test_get_associated_logins_returns_only_active_objects(self):
        process_id = uuid.uuid4()
        active_login = MyMomentLogin(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            username_encrypted="enc:user",
            password_encrypted="enc:pass",
            name="Account",
        )
        inactive_login = MyMomentLogin(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            username_encrypted="enc:user2",
            password_encrypted="enc:pass2",
            name="Account2",
        )
        process = MonitoringProcess(
            id=process_id,
            user_id=uuid.uuid4(),
            name="Monitor",
        )
        process.monitoring_process_logins = [
            MonitoringProcessLogin(
                monitoring_process_id=process_id,
                mymoment_login=active_login,
                is_active=True,
            ),
            MonitoringProcessLogin(
                monitoring_process_id=process_id,
                mymoment_login=inactive_login,
                is_active=False,
            ),
        ]

        assert process.get_associated_logins() == [active_login]


class TestMonitoringProcessLogin:
    """Tests for MonitoringProcessLogin association validation."""

    def test_is_valid_association_matches_user(self):
        user_id = uuid.uuid4()
        process = MonitoringProcess(id=uuid.uuid4(), user_id=user_id, name="Monitor")
        login = MyMomentLogin(
            id=uuid.uuid4(),
            user_id=user_id,
            username_encrypted="enc:user",
            password_encrypted="enc:pass",
            name="Account",
        )

        mpl = MonitoringProcessLogin(
            id=uuid.uuid4(),
            monitoring_process_id=process.id,
            mymoment_login_id=uuid.uuid4(),
            monitoring_process=process,
            mymoment_login=login,
        )

        assert mpl.is_valid_association is True

        mpl.mymoment_login = MyMomentLogin(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            username_encrypted="enc:user2",
            password_encrypted="enc:pass2",
            name="Account2",
        )
        assert mpl.is_valid_association is False

    def test_is_valid_association_handles_missing_relations(self):
        mpl = MonitoringProcessLogin(
            id=uuid.uuid4(),
            monitoring_process_id=uuid.uuid4(),
            mymoment_login_id=uuid.uuid4(),
        )

        assert mpl.is_valid_association is False


class TestMonitoringProcessPrompt:
    """Tests for MonitoringProcessPrompt weight handling."""

    def test_effective_weight_returns_weight_when_active(self):
        prompt = MonitoringProcessPrompt(weight=2.5, is_active=True)
        assert prompt.effective_weight == 2.5

    def test_effective_weight_zero_when_inactive(self):
        prompt = MonitoringProcessPrompt(weight=2.5, is_active=False)
        assert prompt.effective_weight == 0.0
