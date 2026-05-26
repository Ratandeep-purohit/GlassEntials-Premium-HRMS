from decimal import Decimal, InvalidOperation


def as_decimal(value, default="0.00"):
    try:
        return Decimal(str(value if value not in [None, ""] else default)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal(default).quantize(Decimal("0.01"))


def as_int(value, default=0):
    try:
        return int(value if value not in [None, ""] else default)
    except (TypeError, ValueError):
        return default


def checkbox(data, key):
    return data.get(key) == "on"


def request_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
