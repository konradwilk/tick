import base64
import hashlib
import json
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs, urlencode
from urllib.request import urlopen
from urllib.error import HTTPError
from tick.google_auth import GoogleAccount, CLIENT_ID, SCOPE

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
        with patch('tick.google_auth.post_token',exchange):
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
