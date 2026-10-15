#!/usr/bin/env python3
"""Prepare installed-app OAuth configuration without logging credential contents."""
import argparse
import json
import os
from pathlib import Path

DESKTOP_ID = '1048312430782-hprvc7al4c9mvfkqgv9cujns0hilees7.apps.googleusercontent.com'
ROOT = Path(__file__).resolve().parents[1]


def desktop_secret(source=None):
    secret = os.environ.get('TICK_GOOGLE_DESKTOP_CLIENT_SECRET')
    if secret: return secret
    files = [Path(source)] if source else sorted((ROOT / 'tick-credentials').glob('*.json'))
    for path in files:
        obj = json.loads(path.read_text(encoding='utf-8')).get('installed', {})
        if obj.get('client_id') == DESKTOP_ID and obj.get('client_secret'): return obj['client_secret']
    raise ValueError('Desktop OAuth configuration is missing. The maintainer must run tools/configure_google.py with the downloaded Desktop client JSON.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--format', choices=('json', 'swift', 'csharp'), default='json')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--allow-unconfigured', action='store_true', help='Build local-only clients when maintainer configuration is absent')
    args = parser.parse_args()
    try: secret = desktop_secret(args.source)
    except ValueError:
        if not args.allow_unconfigured: raise
        secret = ''
    literal = json.dumps(secret)
    if args.format == 'swift': text = 'enum GoogleDesktopClient { static let secret = ' + literal + ' }\n'
    elif args.format == 'csharp': text = 'namespace HoursCore;\ninternal static class GoogleDesktopClient { public const string Secret = ' + literal + '; }\n'
    else: text = json.dumps({'client_id': DESKTOP_ID, 'client_secret': secret}) + '\n'
    output = args.output or ROOT / 'linux/tick/google-client.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists() or output.read_text() != text: output.write_text(text, encoding='utf-8')


if __name__ == '__main__': main()
