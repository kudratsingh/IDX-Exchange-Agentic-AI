"""Turns plain-language requests into validated filters.

Stage between the user's message and the db queries; values are checked against
`domain.valid_values`, and anything outside those sets is rejected, not guessed.
"""
