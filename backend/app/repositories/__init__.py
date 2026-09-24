"""Repositories: the only layer that talks to the database.

Rule: every query on tenant data takes an `organization_id` and filters by it
(added in phase 2 together with the Organization model).
"""
