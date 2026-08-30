"""Untrusted, no-network document-parsing runtime.

Deliberately independent of `ai_interviewer.candidate_inputs`: importing this package
must never pull in SQLAlchemy, boto3, cryptography, or FastAPI, because every module
reachable from here can be loaded inside the isolated child process that parses
attacker-controlled document bytes.
"""
