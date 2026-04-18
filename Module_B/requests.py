import json as _json
import urllib.error
import urllib.request


class Response:
    def __init__(self, status_code, body, headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.text = body.decode("utf-8", errors="replace")

    def json(self):
        if not self.text:
            return {}
        return _json.loads(self.text)


def request(method, url, json=None, headers=None, timeout=None):
    body = None
    req_headers = dict(headers or {})

    if json is not None:
        body = _json.dumps(json).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(
        url=url,
        data=body,
        headers=req_headers,
        method=method.upper(),
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return Response(resp.getcode(), resp.read(), dict(resp.headers.items()))
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.read(), dict(exc.headers.items()))


def get(url, headers=None, timeout=None):
    return request("GET", url, headers=headers, timeout=timeout)


def post(url, json=None, headers=None, timeout=None):
    return request("POST", url, json=json, headers=headers, timeout=timeout)


def put(url, json=None, headers=None, timeout=None):
    return request("PUT", url, json=json, headers=headers, timeout=timeout)
