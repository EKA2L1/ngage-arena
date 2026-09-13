"""Validate emulator host mapping targets without resolving them at setup time."""
import ipaddress
import re


def host_target(value):
    target = value.strip().lower().removesuffix('.')
    try:
        return str(ipaddress.ip_address(target))
    except ValueError:
        pass
    if (not target or len(target) > 253 or re.fullmatch(r'[0-9.]+', target)
            or any(not re.fullmatch(r'[a-z0-9_-]{1,63}', label) for label in target.split('.'))):
        raise ValueError('Expected an IP address or hostname without a URL scheme or port')
    return target
