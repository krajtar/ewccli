"""Service layer for ewccli.

This package contains pure business-logic modules with no
``click`` or ``rich_click`` imports, enabling the logic to run
without a CLI context.  CLI command handlers delegate to these
services so that behaviour is identical whether invoked from the
CLI or programmatically.
"""
