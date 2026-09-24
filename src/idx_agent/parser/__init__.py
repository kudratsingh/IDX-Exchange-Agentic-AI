"""No parser lives here: the model fills each tool's typed schema and code validates it.

Decided in ADR-0004 (docs/adrs/0004-query-parsing.md). The package stays so the layout
matches docs/ARCHITECTURE.md; a deterministic pre-parser is a gated extension in
docs/DECISIONS.md and would go here if the local parsing evals ever call for it.
"""
