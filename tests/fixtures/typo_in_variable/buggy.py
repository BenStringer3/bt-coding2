def parse_response(raw):
    """Parse a raw HTTP-like response dict and return normalised fields."""
    recieved_at = raw.get("timestamp")
    status_code = raw.get("status", 200)
    payload = raw.get("body", {})

    return {
        "received_at": recieved_at,
        "status": status_code,
        "payload": payload,
    }
