"""Service layer for EWC CLI.

Contains pure business logic decoupled from click/rich_click.
All service modules accept dependencies via explicit injection
and use standard Python exceptions instead of ClickException.
"""
