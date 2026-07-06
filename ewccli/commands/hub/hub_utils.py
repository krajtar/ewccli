#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details


"""CLI EWC Hub: EWC Hub interaction utils methods."""

from typing import Optional, List
from pathlib import Path
from urllib.parse import urlparse

import rich_click as click
from rich.console import Console

from ewccli.enums import HubItemTechnologyAnnotation
from ewccli.logger import get_logger
from ewccli.services.hub_deploy_service import HubDeployService
from ewccli.services.exceptions import ValidationError

_LOGGER = get_logger(__name__)


console = Console()
_hub_deploy_service = HubDeployService()


def verify_item_is_deployable(item_info: dict):
    """Verify item is deployable."""
    return _hub_deploy_service.verify_item_is_deployable(item_info)


def prepare_missing_inputs_error_message(missing_inputs: list[str]):
    """Prepare missing item inputs message."""
    return _hub_deploy_service.prepare_missing_inputs_error_message(missing_inputs)


def extract_annotations(annotations: Optional[dict] = None):
    """Extract annotations from item info."""
    return _hub_deploy_service.extract_annotations(annotations)


def classify_source(source: str) -> str:
    """
    Classify a source string as:
      - 'github'     → GitHub HTTPS repo URL compatible with check_github_repo_accessible()
      - 'directory'  → local directory
      - 'unknown'    → neither
  
    Notes:
    - GitHub URLs must be HTTPS and like:
        https://github.com/user/repo
        https://github.com/user/repo.git
    """
    path = Path(source)

    # 1. GitHub URL (only the HTTPS format supported by your check method)
    if is_github_https_url(source):
        return "github"

    # 2. Local directory
    if path.exists() and path.is_dir() and any(path.iterdir()) and path.is_absolute():
        return "directory"

    # 3. Unknown
    raise click.BadParameter(f"Source provided: {source} is not a valid GitHub repo URL or an absolute path to a local directory with content.")


def is_github_https_url(source: str) -> bool:
    """Detect HTTPS GitHub URLs (owner/repo format)."""
    return _hub_deploy_service.is_github_https_url(source)
