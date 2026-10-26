"""Google desktop OAuth with PKCE, browser login, and operating-system credentials."""
import base64
import ctypes
import hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
import webbrowser

CLIENT_ID = '1048312430782-hprvc7al4c9mvfkqgv9cujns0hilees7.apps.googleusercontent.com'
SCOPE = 'https://www.googleapis.com/auth/drive.file'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
SERVICE = 'org.timeisclearlykept.google'


def desktop_client_secret():
    """Resolve installed-app configuration without exposing credential contents."""
    secret = os.environ.get('TICK_GOOGLE_DESKTOP_CLIENT_SECRET')
    if secret: return secret
    configuration = Path(__file__).with_name('google-client.json')
    if configuration.exists():
        try:
            data = json.loads(configuration.read_text(encoding='utf-8'))
        except (ValueError, OSError) as error:
            raise ValueError('Python Google OAuth configuration is unreadable. Run python3 tools/configure_google.py from the Tick project folder.') from error
        if not isinstance(data, dict) or data.get('client_id') != CLIENT_ID:
            raise ValueError('Python Google OAuth configuration belongs to a different client. Run python3 tools/configure_google.py from the Tick project folder.')
        secret = data.get('client_secret')
        if isinstance(secret, str) and secret.strip(): return secret
    raise ValueError('Python Google OAuth configuration is missing. Run python3 tools/configure_google.py from the Tick project folder, then retry. A distributed copy must include linux/tick/google-client.json.')


def post_token(fields):
    fields = dict(fields, client_secret=desktop_client_secret())
    try:
        with urlopen(Request(TOKEN_URL, data=urlencode(fields).encode(), headers={'Content-Type': 'application/x-www-form-urlencoded'}), timeout=30) as stream:
            result = json.load(stream)
    except HTTPError as error:
        # Never print Google's raw response: it can contain supplied credentials.
        try:
            response = json.loads(error.read(16384).decode('utf-8'))
            code = response.get('error') if isinstance(response, dict) else None
        except (ValueError, OSError, UnicodeError):
            code = None
        messages = {
            'invalid_client': 'Google rejected the app OAuth credentials (invalid_client). Run python3 tools/configure_google.py, then retry. If TICK_GOOGLE_DESKTOP_CLIENT_SECRET is set, check that it matches the Desktop client.',
            'invalid_grant': 'Google rejected an expired, revoked, or mismatched authorization (invalid_grant). Retry the migration with --sign-in to obtain a new authorization.',
            'unauthorized_client': 'Google rejected this OAuth client (unauthorized_client). Check that the configured credential is a Desktop app client enabled for Tick.',
            'redirect_uri_mismatch': 'Google rejected the sign-in callback (redirect_uri_mismatch). Check the Desktop OAuth client configuration.',
            'access_denied': 'Google denied authorization (access_denied). Allow Tick access or check your organization account policy.',
            'invalid_request': 'Google rejected the token request (invalid_request). Regenerate the Desktop OAuth configuration with python3 tools/configure_google.py and retry with --sign-in.',
        }
        message = messages.get(code) if isinstance(code, str) else None
        raise ValueError(message or f'Google authorization failed (HTTP {error.code}). Check the app OAuth configuration and retry with --sign-in.') from error
    if not result.get('access_token'):
        raise ValueError('Google did not grant access. Sign in and allow access to files used by Tick.')
    if 'scope' in result and SCOPE not in result['scope'].split():
        raise ValueError('Google Sheets permission was not granted.')
    return result


class CredentialVault:
    """No plaintext token files. Fail explicitly if a system credential store is unavailable."""
    def _windows(self, value=None, delete=False):
        from ctypes import wintypes
        class CREDENTIAL(ctypes.Structure):
            _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR),
                        ('Comment', wintypes.LPWSTR), ('LastWritten', wintypes.FILETIME),
                        ('CredentialBlobSize', wintypes.DWORD), ('CredentialBlob', ctypes.POINTER(ctypes.c_byte)),
                        ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD),
                        ('Attributes', ctypes.c_void_p), ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]
        api = ctypes.WinDLL('Advapi32', use_last_error=True)
        api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
        api.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredFree.argtypes = [ctypes.c_void_p]
        if delete:
            if not api.CredDeleteW(SERVICE, 1, 0) and ctypes.get_last_error() != 1168: raise OSError('Could not remove Google credentials.')
            return
        if value is not None:
            raw = value.encode('utf-8'); blob = (ctypes.c_byte * len(raw)).from_buffer_copy(raw)
            cred = CREDENTIAL(Type=1, TargetName=SERVICE, UserName='Tick', CredentialBlobSize=len(raw), CredentialBlob=blob, Persist=2)
            if not api.CredWriteW(ctypes.byref(cred), 0): raise OSError('Could not save Google credentials.')
            return
        pointer = ctypes.POINTER(CREDENTIAL)()
        if not api.CredReadW(SERVICE, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168: return None
            raise OSError('Could not read Google credentials.')
        try: return ctypes.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize).decode('utf-8')
        finally: api.CredFree(pointer)

    def _macos(self, value=None, delete=False):
        security = ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
        cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        pointer = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [pointer, ctypes.c_char_p, ctypes.c_uint32]; cf.CFStringCreateWithCString.restype = pointer
        cf.CFDataCreate.argtypes = [pointer, pointer, ctypes.c_long]; cf.CFDataCreate.restype = pointer
        cf.CFDictionaryCreate.argtypes = [pointer, pointer, pointer, ctypes.c_long, pointer, pointer]; cf.CFDictionaryCreate.restype = pointer
        cf.CFDataGetLength.argtypes = [pointer]; cf.CFDataGetLength.restype = ctypes.c_long
        cf.CFDataGetBytePtr.argtypes = [pointer]; cf.CFDataGetBytePtr.restype = pointer
        cf.CFRelease.argtypes = [pointer]
        security.SecItemCopyMatching.argtypes = [pointer, ctypes.POINTER(pointer)]
        security.SecItemUpdate.argtypes = [pointer, pointer]
        security.SecItemAdd.argtypes = [pointer, pointer]
        security.SecItemDelete.argtypes = [pointer]
        allocated = []
        def constant(name): return pointer.in_dll(security, name).value
        def string(text):
            obj = cf.CFStringCreateWithCString(None, text.encode(), 0x08000100); allocated.append(obj); return obj
        def dictionary(items):
            keys = (pointer * len(items))(*items.keys()); values = (pointer * len(items))(*items.values())
            obj = cf.CFDictionaryCreate(None, keys, values, len(items), ctypes.addressof(ctypes.c_byte.in_dll(cf, 'kCFTypeDictionaryKeyCallBacks')), ctypes.addressof(ctypes.c_byte.in_dll(cf, 'kCFTypeDictionaryValueCallBacks')))
            allocated.append(obj); return obj
        try:
            items = {constant('kSecClass'): constant('kSecClassGenericPassword'), constant('kSecAttrService'): string(SERVICE), constant('kSecAttrAccount'): string('Tick')}
            query = dictionary(items)
            if delete:
                status = security.SecItemDelete(query)
            elif value is not None:
                raw = value.encode(); data = cf.CFDataCreate(None, ctypes.c_char_p(raw), len(raw)); allocated.append(data)
                status = security.SecItemUpdate(query, dictionary({constant('kSecValueData'): data}))
                if status == -25300:
                    items[constant('kSecValueData')] = data
                    status = security.SecItemAdd(dictionary(items), None)
            else:
                items[constant('kSecReturnData')] = pointer.in_dll(cf, 'kCFBooleanTrue').value
                result = pointer()
                status = security.SecItemCopyMatching(dictionary(items), ctypes.byref(result))
                if status == -25300: return None
                if status != 0: raise ValueError('Could not read Google sign-in from Keychain.')
                try: return ctypes.string_at(cf.CFDataGetBytePtr(result), cf.CFDataGetLength(result)).decode()
                finally: cf.CFRelease(result)
            if status not in (0, -25300): raise ValueError('Could not update Google sign-in in Keychain.')
        finally:
            for obj in reversed(allocated): cf.CFRelease(obj)

    def read(self):
        if sys.platform == 'win32': return self._windows()
        if sys.platform == 'darwin': return self._macos()
        if not shutil.which('secret-tool'): raise ValueError('Google sign-in requires the system keyring (install libsecret-tools). Local file storage is available without it.')
        result = subprocess.run(['secret-tool', 'lookup', 'service', SERVICE], capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None

    def write(self, value):
        if sys.platform == 'win32': return self._windows(value=value)
        if sys.platform == 'darwin': return self._macos(value=value)
        if not shutil.which('secret-tool'): raise ValueError('Install libsecret-tools to save Google sign-in securely.')
        result = subprocess.run(['secret-tool', 'store', '--label=Tick Google sign-in', 'service', SERVICE], input=value.encode(), capture_output=True)
        if result.returncode: raise ValueError('Could not save Google sign-in in the system credential store.')

    def delete(self):
        if sys.platform == 'win32': return self._windows(delete=True)
        if sys.platform == 'darwin': return self._macos(delete=True)
        if shutil.which('secret-tool'): subprocess.run(['secret-tool', 'clear', 'service', SERVICE], capture_output=True)


class GoogleAccount:
    def __init__(self, vault=None):
        self.vault = vault or CredentialVault()
        self.token, self.expires = None, 0

    def sign_in(self, timeout=180, opener=webbrowser.open, cancelled=None):
        if cancelled is not None and cancelled.is_set(): raise ValueError('Google sign-in was cancelled.')
        desktop_client_secret()  # Fail before opening a browser when app configuration is missing.
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        state = secrets.token_urlsafe(32)
        received = {}
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parts = urlparse(self.path); query = parse_qs(parts.query)
                valid = parts.path == '/oauth2callback' and secrets.compare_digest(query.get('state', [''])[0], state)
                if not valid:
                    self.send_error(400, 'Invalid sign-in callback'); return
                received.update(query)
                self.send_response(200); self.send_header('Content-Type', 'text/plain; charset=utf-8'); self.end_headers()
                self.wfile.write(b'Return to Tick to finish connecting Google Sheets.')
            def log_message(self, *args): pass
        with HTTPServer(('127.0.0.1', 0), Handler) as server:
            server.timeout = 0.5
            redirect = f'http://127.0.0.1:{server.server_port}/oauth2callback'
            url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(dict(client_id=CLIENT_ID, redirect_uri=redirect,
                response_type='code', scope=SCOPE, code_challenge=challenge, code_challenge_method='S256',
                state=state, access_type='offline', prompt='consent select_account'))
            if not opener(url): raise ValueError('Could not open your browser for Google sign-in.')
            deadline = time.monotonic() + timeout
            while not received and time.monotonic() < deadline:
                if cancelled is not None and cancelled.is_set(): raise ValueError("Google sign-in was cancelled.")
                server.handle_request()
        if 'error' in received: raise ValueError('Google sign-in was cancelled or denied.')
        if not received.get('code'): raise ValueError('Google sign-in timed out. Try again.')
        result = post_token(dict(client_id=CLIENT_ID, redirect_uri=redirect, code=received['code'][0], code_verifier=verifier, grant_type='authorization_code'))
        if not result.get('refresh_token'): raise ValueError('Google did not return a persistent sign-in. Try again.')
        self.vault.write(result['refresh_token'])
        self._accept(result)
        return self

    def _accept(self, result):
        self.token = result['access_token']; self.expires = time.time() + float(result.get('expires_in', 3600)) - 60

    def access_token(self):
        refresh = self.vault.read()
        if not refresh: raise ValueError('Sign in with Google in Settings to reconnect your spreadsheet.')
        if self.token and time.time() < self.expires: return self.token
        self._accept(post_token(dict(client_id=CLIENT_ID, refresh_token=refresh, grant_type='refresh_token')))
        return self.token

    def sign_out(self):
        self.vault.delete(); self.token = None; self.expires = 0
