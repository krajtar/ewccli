#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details

"""DNS service — record name building and resolution polling.

No ``click`` / ``rich_click`` imports.
"""

import time
import socket
from typing import Optional

from ewccli.logger import get_logger

_LOGGER = get_logger(__name__)


class DnsService:
    """Pure business logic for DNS record operations."""

    @staticmethod
    def build_dns_record_name(
        server_name: str, tenancy_name: str, hosting_location: str
    ) -> str:
        """Build a DNS hostname using the ewcloud pattern.

        Pattern: <machine-name>.<tenancy-name>.<hosting-location>.ewcloud.host
        """
        if not all([server_name, tenancy_name, hosting_location]):
            raise ValueError(
                "All arguments (server_name, tenancy_name, hosting_location) "
                "are required."
            )

        dns_record_name = (
            f"{server_name}.{tenancy_name}.{hosting_location}.ewcloud.host"
        )
        _LOGGER.debug("Built DNS Record Name: %s", dns_record_name)
        return dns_record_name

    @staticmethod
    def wait_for_dns_record(
        dns_record_name: str,
        expected_ip: str,
        interval: int = 60,
        timeout_minutes: int = 5,
    ) -> bool:
        """Wait until dns_record_name resolves to expected_ip."""
        deadline = time.time() + timeout_minutes * 60
        _LOGGER.info(
            "Waiting for %s to resolve to %s...", dns_record_name, expected_ip
        )
        _LOGGER.info(
            "This could take several minutes, grab some snack meanwhile..."
        )

        while time.time() < deadline:
            try:
                resolved_ip = socket.gethostbyname(dns_record_name)

                if resolved_ip == expected_ip:
                    _LOGGER.info(
                        "Success: %s resolved to %s",
                        dns_record_name,
                        resolved_ip,
                    )
                    return True
                else:
                    _LOGGER.debug(
                        "%s currently resolves to %s (expected %s)",
                        dns_record_name,
                        resolved_ip,
                        expected_ip,
                    )

            except socket.gaierror:
                _LOGGER.info(
                    f"{dns_record_name} not found in DNS yet. "
                    f"Retrying in {interval} seconds..."
                )

            time.sleep(interval)

        _LOGGER.warning(
            "Timeout: %s did not resolve to %s within %d minutes.",
            dns_record_name,
            expected_ip,
            timeout_minutes,
        )
        return False
