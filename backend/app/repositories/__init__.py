"""Repositories: the only layer that talks to the database.

Rule: every query on tenant data (jobs, and later documents, invoices, ...) takes an
`organization_id` and filters by it. Tests in tests/test_org_isolation.py prove it.
"""
