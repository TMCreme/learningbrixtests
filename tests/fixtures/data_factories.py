"""Faker-driven test data with stable, unique-per-run suffixes."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from faker import Faker


fake = Faker()
Faker.seed(int(os.environ.get("FAKER_SEED", "0")) or None)

# All test entities use this prefix so they're easy to identify and sweep.
TEST_PREFIX = "TEST"

# Short unique tag per process — keeps tests collision-free if rerun
# against a shared backend that didn't fully clean up.
_RUN_TAG = uuid.uuid4().hex[:6]


def unique_email(role: str, school_id: str | int = "x") -> str:
    return f"playwright+{role}-{school_id}-{_RUN_TAG}-{uuid.uuid4().hex[:4]}@learningbrix.test"


@dataclass
class PersonData:
    first_name: str
    last_name: str
    email: str
    phone: str
    address: str
    nationality: str
    date_of_birth: str  # dd/mm/yyyy for UI
    gender: str

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


def make_person(role: str, school_id: str | int = "x", *, gender: str = "Male") -> PersonData:
    first = fake.first_name_male() if gender == "Male" else fake.first_name_female()
    last = fake.last_name()
    return PersonData(
        first_name=first,
        last_name=last,
        email=unique_email(role, school_id),
        phone=fake.numerify("020#######"),
        address=fake.street_address(),
        nationality="Ghanaian",
        date_of_birth=fake.date_of_birth(minimum_age=18, maximum_age=50).strftime("%d/%m/%Y"),
        gender=gender,
    )


@dataclass
class SchoolSeed:
    name: str
    address: str
    phone: str
    email: str
    admin_first_name: str
    admin_other_names: str
    admin_email: str

    @classmethod
    def for_scenario(cls, scenario_id: str, school_name: str) -> "SchoolSeed":
        return cls(
            name=school_name,
            address=fake.street_address(),
            phone=fake.numerify("0302######"),
            email=f"contact-{scenario_id}-{_RUN_TAG}@learningbrix.test",
            admin_first_name=fake.first_name(),
            admin_other_names=fake.last_name(),
            admin_email=unique_email("admin", scenario_id),
        )


def run_tag() -> str:
    """Process-wide unique tag (for log correlation)."""
    return _RUN_TAG
