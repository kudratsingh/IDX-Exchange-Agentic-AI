"""Database access: parameterized, SELECT-only, bounded queries.

Sits below the tool layer. Columns come from `safety.columns.ALLOWLIST`, never
`SELECT *`; result sets are capped at 50 rows.
"""
