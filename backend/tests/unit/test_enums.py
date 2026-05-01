
"""
tests/unit/test_enums.py  —  Enum and enum helper tests.
"""
import pytest


class TestApplicationStage:
    def test_applied_value(self, app):
        with app.app_context():
            from app.models.enums import ApplicationStage
            assert ApplicationStage.APPLIED == "applied"

    def test_hired_value(self, app):
        with app.app_context():
            from app.models.enums import ApplicationStage
            assert ApplicationStage.HIRED == "hired"

    def test_withdrawn_value(self, app):
        with app.app_context():
            from app.models.enums import ApplicationStage
            assert ApplicationStage.WITHDRAWN == "withdrawn"

    def test_terminal_stages_include_hired(self, app):
        with app.app_context():
            from app.models.enums import ApplicationStage, TERMINAL_STAGES
            assert ApplicationStage.HIRED in TERMINAL_STAGES

    def test_terminal_stages_include_rejected(self, app):
        with app.app_context():
            from app.models.enums import ApplicationStage, TERMINAL_STAGES
            assert ApplicationStage.REJECTED in TERMINAL_STAGES

    def test_terminal_stages_include_withdrawn(self, app):
        with app.app_context():
            from app.models.enums import ApplicationStage, TERMINAL_STAGES
            assert ApplicationStage.WITHDRAWN in TERMINAL_STAGES

    def test_applied_can_advance_to_reviewed(self, app):
        with app.app_context():
            from app.models.enums import ApplicationStage, STAGE_TRANSITIONS
            assert ApplicationStage.REVIEWED in STAGE_TRANSITIONS[ApplicationStage.APPLIED]

    def test_hired_has_no_transitions(self, app):
        with app.app_context():
            from app.models.enums import ApplicationStage, STAGE_TRANSITIONS
            assert len(STAGE_TRANSITIONS[ApplicationStage.HIRED]) == 0


class TestJobStatus:
    def test_values(self, app):
        with app.app_context():
            from app.models.enums import JobStatus
            assert JobStatus.ACTIVE == "active"
            assert JobStatus.DRAFT  == "draft"
            assert JobStatus.PAUSED == "paused"
            assert JobStatus.CLOSED == "closed"


class TestJobType:
    def test_full_time_value(self, app):
        with app.app_context():
            from app.models.enums import JobType
            assert JobType.FULL_TIME == "full-time"

    def test_contract_value(self, app):
        with app.app_context():
            from app.models.enums import JobType
            assert JobType.CONTRACT == "contract"


class TestParseStatus:
    def test_values(self, app):
        with app.app_context():
            from app.models.enums import ParseStatus
            assert ParseStatus.PENDING == "pending"
            assert ParseStatus.SUCCESS == "success"
            assert ParseStatus.FAILED  == "failed"


class TestScoreToLabel:
    def test_excellent(self, app):
        with app.app_context():
            from app.models.enums import ScoreLabel, score_to_label
            assert score_to_label(0.90) == ScoreLabel.EXCELLENT

    def test_good(self, app):
        with app.app_context():
            from app.models.enums import ScoreLabel, score_to_label
            assert score_to_label(0.70) == ScoreLabel.GOOD

    def test_fair(self, app):
        with app.app_context():
            from app.models.enums import ScoreLabel, score_to_label
            assert score_to_label(0.55) == ScoreLabel.FAIR

    def test_weak(self, app):
        with app.app_context():
            from app.models.enums import ScoreLabel, score_to_label
            assert score_to_label(0.40) == ScoreLabel.WEAK

    def test_boundary_excellent(self, app):
        with app.app_context():
            from app.models.enums import ScoreLabel, score_to_label
            assert score_to_label(0.80) == ScoreLabel.EXCELLENT

    def test_boundary_just_below_excellent(self, app):
        with app.app_context():
            from app.models.enums import ScoreLabel, score_to_label
            assert score_to_label(0.799) == ScoreLabel.GOOD

    def test_boundary_zero(self, app):
        with app.app_context():
            from app.models.enums import ScoreLabel, score_to_label
            assert score_to_label(0.0) == ScoreLabel.WEAK

    def test_boundary_one(self, app):
        with app.app_context():
            from app.models.enums import ScoreLabel, score_to_label
            assert score_to_label(1.0) == ScoreLabel.EXCELLENT

    def test_custom_thresholds(self, app):
        with app.app_context():
            from app.models.enums import ScoreLabel, score_to_label
            assert score_to_label(0.75,
                                  threshold_excellent=0.9,
                                  threshold_good=0.7,
                                  threshold_fair=0.5) == ScoreLabel.GOOD


class TestCompanySize:
    def test_all_bands(self, app):
        with app.app_context():
            from app.models.enums import CompanySize
            assert CompanySize.MICRO  == "1-10"
            assert CompanySize.SMALL  == "11-50"
            assert CompanySize.MEDIUM == "51-200"
            assert CompanySize.LARGE  == "201-500"
            assert CompanySize.XLARGE == "500+"