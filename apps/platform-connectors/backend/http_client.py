"""Bounded public HTTP with DNS pinning and redirect revalidation."""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import ipaddress
import json
import socket
import ssl
from urllib.parse import urljoin, urlsplit, urlunsplit


class FetchError(RuntimeError):
    def __init__(self, code: str, detail: str, status: int = 502):
        super().__init__(detail)
        self.code,self.status = code,status


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    headers: dict[str,str]
    content: bytes

    def json(self):
        try:
            return json.loads(self.content)
        except (ValueError,UnicodeError) as error:
            raise FetchError("invalid_upstream_content","The source returned an invalid JSON response.") from error


def public_target(url: str, allowed_hosts: set[str] | None = None) -> tuple[str,str,int,str]:
    if not isinstance(url,str) or len(url)>8192 or "\\" in url or any(c.isspace() or ord(c)<32 for c in url):
        raise FetchError("invalid_url","A valid public HTTP URL is required.",400)
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").encode("idna").decode().lower().rstrip(".")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except (ValueError,UnicodeError):
        raise FetchError("invalid_url","Invalid URL.",400) from None
    if parsed.scheme not in {"http","https"} or not host or parsed.username or parsed.password or port not in {80,443}:
        raise FetchError("invalid_url","Only public HTTP/HTTPS URLs without credentials are allowed.",400)
    if allowed_hosts is not None and host not in allowed_hosts:
        raise FetchError("source_host_mismatch","The URL does not belong to the requested source.",400)
    if host in {"localhost","metadata.google.internal","instance-data"} or host.endswith((".local",".localhost",".internal",".lan")):
        raise FetchError("private_target_denied","Private targets are not accessible.",403)
    target = urlunsplit(("","",parsed.path or "/",parsed.query,""))
    return parsed.scheme,host,port,target


def public_addresses(host: str, port: int) -> list[str]:
    try:
        addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)))
    except OSError as error:
        raise FetchError("source_unreachable","The source cannot be resolved through DNS.") from error
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise FetchError("private_target_denied","The source resolves to a non-public address.",403)
    return addresses


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, address: str, timeout: int):
        super().__init__(host,port,timeout=timeout,context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address,self.port),self.timeout)
        self.sock = self._context.wrap_socket(sock,server_hostname=self.host)


def fetch(url: str, *, allowed_hosts: set[str] | None = None, max_bytes: int = 4*1024*1024,
          method: str = "GET", body: dict | None = None, headers: dict | None = None, timeout: int = 15) -> Response:
    original_host = public_target(url,allowed_hosts)[1]
    request_headers = {"User-Agent":"Loopino-Connectors/1.0","Accept":"application/json,text/plain,text/html,application/xml","Accept-Encoding":"identity",**(headers or {})}
    payload = json.dumps(body,ensure_ascii=False).encode() if body is not None else None
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
    for redirect in range(5):
        scheme,host,port,target = public_target(url,allowed_hosts)
        addresses = public_addresses(host,port)
        if host != original_host:
            request_headers = {k:v for k,v in request_headers.items() if k.lower() not in {"authorization","x-api-key","cookie"}}
        connection = PinnedHTTPSConnection(host,port,addresses[0],timeout) if scheme == "https" else http.client.HTTPConnection(addresses[0],port,timeout=timeout)
        try:
            connection.request(method,target,body=payload,headers={**request_headers,"Host":host})
            response = connection.getresponse()
            response_headers = {k.lower():v for k,v in response.getheaders()}
            if response.status in {301,302,303,307,308}:
                if redirect == 4 or "location" not in response_headers:
                    raise FetchError("redirect_limit","The source exceeded the redirect limit.")
                next_url = urljoin(url,response_headers["location"])
                if scheme == "https" and urlsplit(next_url).scheme != "https":
                    raise FetchError("insecure_redirect","Unsafe HTTPS redirect.",403)
                url = next_url
                if response.status == 303:
                    method,payload = "GET",None
                continue
            length = response_headers.get("content-length")
            if length and int(length)>max_bytes:
                raise FetchError("content_limit","The content exceeds the acquisition limit.",413)
            content = response.read(max_bytes+1)
            if len(content)>max_bytes:
                raise FetchError("content_limit","The content exceeds the acquisition limit.",413)
            if response.status == 429:
                raise FetchError("rate_limited","The source has rate limited requests. Try again later.",429)
            if response.status in {401,403}:
                raise FetchError("authentication_or_challenge","The source requires authorization or presents a verification challenge.",response.status)
            if response.status>=400:
                raise FetchError("upstream_error",f"The source returned HTTP {response.status}.",502)
            return Response(url,response.status,response_headers,content)
        except FetchError:
            raise
        except (OSError,http.client.HTTPException,ValueError) as error:
            raise FetchError("source_unreachable","The source request failed.") from error
        finally:
            connection.close()
    raise FetchError("redirect_limit","Too many redirects.")
