import base64
import hashlib
import json
import io
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs, urlencode
from urllib.request import urlopen
from urllib.error import HTTPError
from tick.google_auth import GoogleAccount, CLIENT_ID, SCOPE, post_token, desktop_client_secret

class MemoryVault:
    def __init__(self):self.value=None
    def read(self):return self.value
    def write(self,value):self.value=value
    def delete(self):self.value=None

class GoogleAuthTests(unittest.TestCase):
    def test_browser_pkce_state_and_refresh(self):
        vault=MemoryVault();account=GoogleAccount(vault);captured={};threads=[]
        def opener(url):
            q=parse_qs(urlparse(url).query);captured.update(q)
            def callback():
                redirect=q['redirect_uri'][0]
                try:urlopen(redirect+'?'+urlencode({'state':'wrong','code':'attacker'}),timeout=3)
                except HTTPError as error:self.assertEqual(error.code,400)
                with urlopen(redirect+'?'+urlencode({'state':q['state'][0],'code':'valid'}),timeout=3) as response:self.assertEqual(response.status,200)
            thread=threading.Thread(target=callback);threads.append(thread);thread.start();return True
        def exchange(fields):
            if fields['grant_type']=='authorization_code':
                challenge=base64.urlsafe_b64encode(hashlib.sha256(fields['code_verifier'].encode()).digest()).decode().rstrip('=')
                self.assertEqual(challenge,captured['code_challenge'][0]);self.assertEqual(fields['code'],'valid')
                return {'access_token':'short-lived','refresh_token':'secure-refresh','expires_in':3600}
            self.assertEqual(fields['refresh_token'],'secure-refresh')
            return {'access_token':'renewed','expires_in':3600}
        with patch('tick.google_auth.desktop_client_secret',return_value='test-installed-app-config'), patch('tick.google_auth.post_token',exchange):
            account.sign_in(timeout=5,opener=opener)
            self.assertEqual(vault.value,'secure-refresh')
            self.assertEqual(captured['client_id'],[CLIENT_ID]);self.assertEqual(captured['scope'],[SCOPE])
            self.assertEqual(account.access_token(),'short-lived')
            account.expires=0;self.assertEqual(account.access_token(),'renewed')
            account.sign_out();self.assertIsNone(vault.value)
            with self.assertRaisesRegex(ValueError,'Sign in'):account.access_token()
        for thread in threads:thread.join(3)

    def test_cancelled_browser_does_not_save_credentials(self):
        account=GoogleAccount(MemoryVault());event=threading.Event();event.set()
        with self.assertRaisesRegex(ValueError,'cancelled'):account.sign_in(timeout=1,opener=lambda url:True,cancelled=event)
        self.assertIsNone(account.vault.value)

    def test_missing_configuration_fails_before_browser_opens(self):
        with patch('tick.google_auth.desktop_client_secret',side_effect=ValueError('configuration is missing')), patch('webbrowser.open') as browser:
            with self.assertRaisesRegex(ValueError,'configuration is missing'):
                GoogleAccount(MemoryVault()).sign_in(opener=browser)
            browser.assert_not_called()

    def test_token_errors_are_specific_without_leaking_google_response(self):
        for code, expected in [('invalid_client','app OAuth credentials'),('invalid_grant','--sign-in'),('invalid_request','configure_google'),('unknown','HTTP 400')]:
            with self.subTest(code=code):
                body=json.dumps({'error':code,'error_description':'private-token-and-secret'}).encode()
                failure=HTTPError('https://oauth2.googleapis.com/token',400,'Bad request',{},io.BytesIO(body))
                with patch('tick.google_auth.desktop_client_secret',return_value='private-client-secret'),patch('tick.google_auth.urlopen',side_effect=failure):
                    with self.assertRaisesRegex(ValueError,expected) as caught:post_token({'grant_type':'authorization_code','code':'private-code'})
                self.assertNotIn('private-',str(caught.exception))

    def test_token_request_includes_desktop_configuration(self):
        captured={}
        def send(request,timeout):
            captured.update(parse_qs(request.data.decode()))
            return io.BytesIO(json.dumps({'access_token':'accepted'}).encode())
        with patch('tick.google_auth.desktop_client_secret',return_value='installed-config'),patch('tick.google_auth.urlopen',side_effect=send):
            self.assertEqual(post_token({'client_id':CLIENT_ID,'grant_type':'refresh_token'})['access_token'],'accepted')
        self.assertEqual(captured['client_secret'],['installed-config'])

    def test_configuration_checks_client_id_and_environment_override(self):
        from pathlib import Path
        with patch.dict('os.environ',{},clear=True),patch.object(Path,'exists',return_value=False):
            with self.assertRaisesRegex(ValueError,'configuration is missing'):desktop_client_secret()
        with patch.dict('os.environ',{},clear=True),patch.object(Path,'exists',return_value=True),patch.object(Path,'read_text',return_value=json.dumps({'client_id':'other','client_secret':'private-secret'})):
            with self.assertRaisesRegex(ValueError,'different client'):desktop_client_secret()
        with patch.dict('os.environ',{'TICK_GOOGLE_DESKTOP_CLIENT_SECRET':'test-override'}):
            self.assertEqual(desktop_client_secret(),'test-override')
