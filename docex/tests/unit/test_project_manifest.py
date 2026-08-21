"""Mod 138: ProjectManifest.name must be a valid DNS label.

The project name enters data-plane identifiers (SG names, Service Connect
namespaces) via ``dns_label``. A mixed-case name would compile to two
disagreeing spellings of its own project segment, so ``ProjectManifest``
rejects a non-conforming name at load rather than letting it reach the
emitters. Underscores are permitted (converted to hyphens by ``dns_label``);
uppercase and other DNS-illegal characters are not.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from docex.cicl.model import ProjectManifest


def _manifest(name: str) -> ProjectManifest:
    return ProjectManifest.model_validate(
        {"name": name, "version": "0.0.1", "docex_version": "0.1.0"}
    )


@pytest.mark.parametrize(
    "name",
    ["docex_smoke_elastic", "sample", "my-proj", "a", "my_test_proj", "proj123"],
)
def test_valid_dns_label_names_accepted(name: str):
    assert _manifest(name).name == name


@pytest.mark.parametrize(
    "name",
    ["MyProject", "My_Proj", "UPPER", "-lead", "trail-", "has space", "dot.name"],
)
def test_non_conforming_names_rejected(name: str):
    with pytest.raises(ValidationError):
        _manifest(name)
