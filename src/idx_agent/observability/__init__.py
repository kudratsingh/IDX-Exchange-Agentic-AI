"""Structured logging, trace ids, and redaction.

Every log line in the package goes through `logging.log_event`, which redacts first.
"""
