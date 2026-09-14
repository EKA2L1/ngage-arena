# SNAP UDP validation

Native High Seize completed SNAP login and two-client room entry; movement, attack and surrender evidence is in its game validation file. `arena/services/snap/tests/test_protocol.py` covers transport framing, credential ownership, malformed input and lifecycle. HTTP login and UDP login use the shared account ID.
