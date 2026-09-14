# Profiles validation

Native Launcher uploaded game history and Motto edits; clean-cache and restored-cache controls downloaded server edits after pending local writes completed. Dirty local profiles retain native upload precedence. Tests cover namespaces, ordered response fields, authenticated ownership, shared points, unknown UIDs and preservation of other game history. See `arena/services/profiles/tests/test_profiles.py` and [Launcher checks](../launcher/validation.md).
