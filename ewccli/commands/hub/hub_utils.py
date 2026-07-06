#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details


"""CLI EWC Hub: utils — thin wrappers delegating to HubDeployService."""

from typing import Optional, List
from pathlib import Path

import rich_click as click

from ewccli.services.hub_deploy_service import HubDeployService
from ewccli.services.exceptions import HubDeployServiceError


def verify_item_is_deployable(item_info: dict):
    """Verify item is deployable."""
    return HubDeployService.verify_item_is_deployable(item_info=item_info)


def prepare_missing_inputs_error_message(missing_inputs: list[str]):
    """Prepare missing item inputs message."""
    return HubDeployService.prepare_missing_inputs_error_message(
        missing_inputs=missing_inputs
    )


def extract_annotations(annotations: Optional[dict] = None):
    """Extract annotations from item info."""
    return HubDeployService.extract_annotations(annotations=annotations)


def classify_source(source: str) -> str:
    """Classify a source string as 'github', 'directory', or raise."""
    try:
        return HubDeployService.classify_source(source=source)
    except HubDeployServiceError as e:
        raise click.BadParameter(str(e))


def is_github_https_url(source: str) -> bool:
    """Detect HTTPS GitHub URLs (owner/repo)."""
    return HubDeployService.is_github_https_url(source=source)
