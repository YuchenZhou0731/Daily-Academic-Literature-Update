"""Use explicit DPAPI files or the operating system's protected keyring."""
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request


HOSTS = {"openalex": "api.openalex.org", "scopus": "api.elsevier.com"}


def protect(data, decrypting=False):
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    operation = crypt.CryptUnprotectData if decrypting else crypt.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise OSError("Windows CurrentUser credential protection failed")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


def decrypt(data):
    return protect(data, decrypting=True).decode("utf-8")


def system_keyring():
    try:
        if sys.platform == "darwin":
            from keyring.backends.macOS import Keyring
        elif sys.platform.startswith("linux"):
            from keyring.backends.SecretService import Keyring
        else:
            raise RuntimeError("Use DPAPI on Windows")
        return Keyring()
    except ImportError:
        raise RuntimeError("Install requirements-keyring.txt and unlock the operating system keyring") from None


def keyring_service(workspace):
    digest = hashlib.sha256(str(Path(workspace).resolve()).encode()).hexdigest()[:24]
    return "literature-digest-skill:" + digest


def valid_key(value):
    return isinstance(value, str) and bool(value) and all(33 <= ord(character) <= 126 for character in value)


def save_key(workspace, source, value):
    if source not in HOSTS or not valid_key(value):
        raise ValueError("Invalid provider or API key")
    root = Path(workspace).resolve()
    if sys.platform == "win32":
        relative = ".credentials/" + source + ".dpapi"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = protect(json.dumps({"api_key": value}).encode())
        if json.loads(decrypt(encrypted))["api_key"] != value:
            raise RuntimeError("Credential encryption verification failed")
        temporary = path.with_suffix(".dpapi.tmp")
        temporary.write_bytes(encrypted)
        temporary.replace(path)
        return {"backend": "dpapi", "file": relative}
    keyring = system_keyring()
    service = keyring_service(root)
    keyring.set_password(service, source, value)
    if keyring.get_password(service, source) != value:
        raise RuntimeError("System keyring verification failed")
    return {"backend": "keyring"}


class Credentials:
    def __init__(self, workspace, config=None):
        self.root = Path(workspace).resolve()
        self.config = config or {}
        self.values = {}

    def configured(self, source):
        return source in self.config

    def headers(self, source, url):
        if not self.configured(source):
            if source in HOSTS:
                raise RuntimeError(f"{source} requires a configured API key")
            return {}
        parsed = urllib.parse.urlsplit(url)
        if (source not in HOSTS or parsed.scheme != "https" or parsed.hostname != HOSTS[source]
                or parsed.port not in (None, 443) or parsed.username or parsed.password):
            raise ValueError("Credential destination is not the official HTTPS API host")
        if source not in self.values:
            try:
                config = self.config[source]
                if config.get("backend", "dpapi") == "keyring":
                    value = system_keyring().get_password(keyring_service(self.root), source)
                else:
                    path = (self.root / config["file"]).resolve()
                    if not path.is_relative_to(self.root / ".credentials") or path.suffix != ".dpapi":
                        raise ValueError("Invalid credential file")
                    value = json.loads(decrypt(path.read_bytes()))["api_key"]
                if not valid_key(value):
                    raise ValueError("Invalid credential")
            except Exception:
                raise RuntimeError(f"{source}: protected credential unavailable; run as the owning Windows user or unlock the configured system keyring") from None
            self.values[source] = value
        value = self.values[source]
        return {"Authorization": "Bearer " + value} if source == "openalex" else {"X-ELS-APIKey": value}

    def redact(self, value):
        for secret in self.values.values():
            for variant in {secret, urllib.parse.quote(secret, safe=""), urllib.parse.quote_plus(secret)}:
                value = value.replace(variant, "[REDACTED]")
        return value


class AuthRedirectGuard(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        if any(name.lower() in {"authorization", "x-els-apikey"} for name, _ in request.header_items()):
            raise RuntimeError("Authenticated API redirect refused")
        return super().redirect_request(request, response, code, message, headers, newurl)
