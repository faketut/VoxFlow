"""Unit tests for Ultravox tool parameter models."""
import pytest
from pydantic import ValidationError

from app.services.tools_service import (
    QueryCorpusParams,
    ScheduleMeetingParams,
    VerifyParams,
)


def test_query_corpus_params_optional_question():
    p = QueryCorpusParams()
    assert p.question is None

    p2 = QueryCorpusParams(question="What are your hours?")
    assert p2.question == "What are your hours?"


def test_verify_params_defaults_to_empty_strings():
    p = VerifyParams()
    assert p.full_name == ""
    assert p.phone_number == ""


def test_verify_params_accepts_values():
    p = VerifyParams(full_name="Jane Doe", phone_number="4165550100")
    assert p.full_name == "Jane Doe"
    assert p.phone_number == "4165550100"


def test_schedule_meeting_params_requires_all_fields():
    with pytest.raises(ValidationError):
        ScheduleMeetingParams(name="John")  # missing email, purpose, datetime, location


def test_schedule_meeting_params_valid():
    p = ScheduleMeetingParams(
        name="John Smith",
        email="john@example.com",
        purpose="Routine checkup",
        datetime="2026-06-01 10:00",
        location="Downtown",
    )
    assert p.name == "John Smith"
    assert p.email == "john@example.com"
    assert p.location == "Downtown"
