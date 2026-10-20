import ipaddress

from fastapi import HTTPException, Request
from shared.settings import settings

# The following are all private IPv4 ranges:
# 10.0.0.0/8 = class A
# 172.16.0.0/12 = class B
# 192.168.0.0/16 = class C
# 169.254.0.0/16 = link local
# reference: https://en.wikipedia.org/wiki/Private_network#Private_IPv4_addresses
#
# The following are private IPv6 ranges:
# fd00::/8 = private network
# fe80::/10 = link local
# reference: https://en.wikipedia.org/wiki/Private_network#Private_IPv6_addresses
PRIVATE_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fd00::/8"),
    ipaddress.ip_network("fe80::/10"),
]


async def require_private_ip_address(request: Request):
    """Whether the request is coming from a valid private IP address."""
    try:
        if not request.client or not request.client.host:
            raise ValueError("Host not defined")
        ip = ipaddress.ip_address(request.client.host)
    except ValueError as e:
        if settings.is_dev_like():
            return
        raise e

    for _range in PRIVATE_RANGES:
        if ip in _range:
            return
    raise HTTPException(status_code=401, detail="Not allowed")
