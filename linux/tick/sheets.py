"""Direct Google Sheets API storage. No Apps Script or shared access keys."""
import json
from datetime import timezone
import re
from urllib.error import HTTPError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from uuid import uuid4
from .core import decode_data, parse

SHEETS = 'https://sheets.googleapis.com/v4/spreadsheets'
DRIVE = 'https://www.googleapis.com/drive/v3/files'
MARKER = 'tick-log-v1'


def spreadsheet_id(value):
    value = value.strip()
    match = re.fullmatch(r'https://docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)(?:/[^\s]*)?', value)
    if match: return match.group(1)
    if re.fullmatch(r'[A-Za-z0-9_-]+', value): return value
    raise ValueError('Choose a spreadsheet used by Tick.')


class GoogleSheetsAPI:
    def __init__(self, account): self.account = account
    def request(self, method, url, body=None):
        request = Request(url, method=method, data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + self.account.access_token(), 'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=30) as stream: return json.load(stream)
        except HTTPError as error:
            if error.code == 401: raise ValueError('Google sign-in expired. Reconnect in Settings.') from error
            if error.code in (403, 404): raise ValueError('Google denied access to this spreadsheet. Choose a spreadsheet authorized for Tick.') from error
            raise ValueError('Google Sheets could not confirm the request. Reload before retrying a save.') from error
        except (OSError, ValueError) as error:
            raise ValueError('Could not reach Google Sheets. Check your connection and reload before retrying.') from error

    def list_spreadsheets(self):
        files, page = [], None
        while True:
            query = dict(q="mimeType='application/vnd.google-apps.spreadsheet' and trashed=false", fields='nextPageToken,files(id,name)', pageSize=100)
            if page: query['pageToken'] = page
            result = self.request('GET', DRIVE + '?' + urlencode(query))
            files.extend(result.get('files', [])); page = result.get('nextPageToken')
            if not page: return sorted(files, key=lambda f: (f['name'].casefold(), f['id']))

    def create(self, name='Time is Clearly Kept'):
        name = name.strip()
        if not name or len(name) > 200: raise ValueError('Enter a spreadsheet name (1–200 characters).')
        result = self.request('POST', SHEETS, {'properties': {'title': name}, 'sheets': [{'properties': {'title': 'TickLog', 'gridProperties': {'rowCount': 1000, 'columnCount': 6}}}]})
        return SheetsStore(self, result['spreadsheetId'], name)


class SheetsStore:
    def __init__(self, api, sheet_id, spreadsheet_name='Time is Clearly Kept'):
        self.api, self.sheet_id = api, spreadsheet_id(sheet_id)
        self.spreadsheet_name = spreadsheet_name
        self.revision = None
        self.path = None
        self.has_log = False
        self.row_mode = False
        self.entities = {"Sessions": {}, "Projects": {}}
        self.log_count = 0
        self.log_revision = None

    @property
    def base(self): return SHEETS + '/' + self.sheet_id

    def _read(self):
        if self.row_mode:
            state, latest, count = self._read_rows()
            return state, latest
        metadata = self.api.request('GET', self.base + '?fields=sheets.properties,properties.title')
        self.metadata = metadata
        self.spreadsheet_name = metadata['properties']['title']
        tabs = [s['properties']['title'] for s in metadata.get('sheets', [])]
        if 'TickMeta' in tabs:
            self.row_mode = True
            state, latest, count = self._read_rows()
            return state, latest
        self.has_log = 'TickLog' in tabs
        if self.has_log:
            rows = self.api.request('GET', self.base + '/values/TickLog!A:F').get('values', [])
            if rows: return decode_log(rows)
        if 'TickData' in tabs:
            rows = self.api.request('GET', self.base + '/values/TickData!A1:A1002').get('values', [])
            if rows:
                if len(rows) < 3 or not rows[0] or not rows[1]: raise ValueError('Invalid previous Tick dataset.')
                count = int(rows[1][0])
                if count < 1 or count > 1000 or len(rows) < count + 2: raise ValueError('Invalid previous Tick dataset.')
                return decode_data(''.join(str(r[0]) for r in rows[2:count+2])), str(rows[0][0])
        # Never overwrite a spreadsheet containing unrelated data.
        if tabs and any(t not in ('TickLog', 'TickData') for t in tabs):
            raise ValueError('This spreadsheet has no Tick dataset. Create a new Tick spreadsheet instead.')
        return None, None

    def load(self, require_existing=False, connect=False):
        state, revision = self._read()
        if state is None and require_existing: raise ValueError('The Tick dataset is missing. Reconnect in Settings.')
        self.revision = revision
        return state

    def _batch_rows(self, ranges):
        url = self.base + '/values:batchGet?' + urlencode([('ranges', r) for r in ranges] + [('valueRenderOption', 'UNFORMATTED_VALUE')])
        values = self.api.request('GET', url).get('valueRanges', [])
        if len(values) != len(ranges): raise ValueError('Incomplete Google Sheets response. Reload before saving.')
        return [v.get('values', []) for v in values]

    def _read_rows(self):
        meta, sessions, projects, changes = self._batch_rows(['TickMeta!A1:B1', 'Sessions', 'Projects', 'TickChanges!A:D'])
        if len(meta) != 1 or len(meta[0]) != 2 or meta[0][0] != 'tick-rows-v1': raise ValueError('Invalid Tick row storage.')
        root = json.loads(meta[0][1])
        entities = {}
        for title, values, offset, key in [('Sessions', sessions, 8, 'sessionId'), ('Projects', projects, 3, 'id')]:
            records = {}
            if not values or values[0][offset:offset+4] != ['Tick ID', 'Version', 'Deleted', 'Chunks']: raise ValueError('Invalid Tick row headers.')
            for index, row in enumerate(values[1:], 1):
                if not row: continue
                if len(row) < offset+5: raise ValueError('Incomplete Tick row.')
                identity, version, deleted, count = row[offset:offset+4]
                count = int(count)
                if identity.lower() in records or not identity or not version or deleted not in ('0', '1') or not 1 <= count <= 1000 or len(row) != offset+4+count: raise ValueError('Invalid or duplicate Tick row.')
                payload = json.loads(''.join(row[offset+4:]))
                if payload[key].lower() != identity.lower(): raise ValueError('Tick row identity changed.')
                records[identity.lower()] = dict(index=index, version=version, deleted=deleted, payload=payload, row=row)
            entities[title] = records
        if not changes: raise ValueError('The Tick change journal is missing. Keep this spreadsheet for recovery.')
        latest = None
        position = 0
        seen = set()
        while position < len(changes):
            row = changes[position]
            if len(row) != 4: raise ValueError('Invalid Tick change journal.')
            identity, parent, chunk, count = row; count = int(count)
            if not identity or identity in seen or parent != (latest or '') or int(chunk) != 0 or not 1 <= count <= 1000 or position+count > len(changes): raise ValueError('Concurrent Google Sheets changes detected. Both changes remain in TickChanges; recover before continuing.')
            for n in range(count):
                if changes[position+n] != [identity, parent, n, count]: raise ValueError('Incomplete Tick change journal.')
            seen.add(identity)
            latest = identity; position += count
        root['sessions'] = [v['payload'] for v in entities['Sessions'].values() if v['deleted'] == '0']
        root['nonprofits'] = [v['payload'] for v in entities['Projects'].values() if v['deleted'] == '0']
        state = decode_data(json.dumps(root))
        state['sessions'].sort(key=lambda s: parse(s['startTimeUtc']))
        for title, field, key in [('Sessions','sessions','sessionId'),('Projects','nonprofits','id')]:
            for payload in state[field]: entities[title][payload[key].lower()]['payload'] = payload
        self.entities = entities
        self.log_count = len(changes)
        return state, latest, len(changes)

    def _initialize_rows(self, state):
        tabs = {s['properties']['title']: s['properties'] for s in self.metadata['sheets']}
        used = {p.get('sheetId', 0) for p in tabs.values()}
        requests = []
        for title in ('TickLog', 'TickData'):
            if title in tabs:
                backup = title + 'Backup'
                if backup in tabs: raise ValueError('A Tick migration backup already exists. Keep this spreadsheet for recovery.')
                requests.append({'updateSheetProperties': {'properties': {'sheetId': tabs[title].get('sheetId', 0), 'title': backup, 'hidden': True}, 'fields': 'title,hidden'}})
        for index, title in enumerate(('Sessions', 'Projects', 'TickMeta', 'TickChanges')):
            if title not in tabs:
                identity = 174001+index
                while identity in used: identity += 1
                used.add(identity)
                tabs[title] = {'sheetId': identity, 'title': title, 'gridProperties': {'rowCount': max(1000, len(state['sessions'])+1, len(state['nonprofits'])+1), 'columnCount': 26}}
                requests.append({'addSheet': {'properties': tabs[title]}})
        # Add visible tabs before hiding the old sole staging tab.
        requests.sort(key=lambda r: 0 if 'addSheet' in r else 1)
        self.metadata = {'sheets': [{'properties': p} for p in tabs.values()]}
        self.entities = {'Sessions': {}, 'Projects': {}}
        self.log_count = 0; self.log_revision = None
        root = {k: v for k, v in state.items() if k not in ('sessions', 'nonprofits')}
        requests.append(self._update('TickMeta', 0, [['tick-rows-v1', json.dumps(root)]]))
        headers = [table_values(state)[0][0], table_values(state)[1][0]]
        for title, header in zip(('Sessions', 'Projects'), headers):
            requests.append(self._update(title, 0, [header + ['Tick ID', 'Version', 'Deleted', 'Chunks', 'Tick data']]))
            identity = tabs[title]['sheetId']
            requests += [{'updateSheetProperties': {'properties': {'sheetId': identity, 'gridProperties': {'frozenRowCount': 1}}, 'fields': 'gridProperties.frozenRowCount'}},
                         {'repeatCell': {'range': {'sheetId': identity, 'startRowIndex': 0, 'endRowIndex': 1}, 'cell': {'userEnteredFormat': {'textFormat': {'bold': True}}}, 'fields': 'userEnteredFormat.textFormat'}},
                         {'updateDimensionProperties': {'range': {'sheetId': identity, 'dimension': 'COLUMNS', 'startIndex': len(header), 'endIndex': max(len(header)+5, tabs[title].get('gridProperties', {}).get('columnCount', 26))}, 'properties': {'hiddenByUser': True}, 'fields': 'hiddenByUser'}}]
        for title in ('TickMeta', 'TickChanges'):
            requests.append({'updateSheetProperties': {'properties': {'sheetId': tabs[title]['sheetId'], 'hidden': True}, 'fields': 'hidden'}})
        return requests

    def _update(self, title, index, rows):
        identity = next(s['properties'].get('sheetId', 0) for s in self.metadata['sheets'] if s['properties']['title'] == title)
        return {'updateCells': {'range': {'sheetId': identity, 'startRowIndex': index, 'endRowIndex': index+len(rows), 'startColumnIndex': 0, 'endColumnIndex': max(len(r) for r in rows)}, 'rows': cell_rows(rows), 'fields': 'userEnteredValue'}}

    def save(self, state):
        state = decode_data(json.dumps(state))
        state['sessions'].sort(key=lambda s: parse(s['startTimeUtc']))
        previous, latest = self._read()
        if latest != self.revision: raise ValueError('Data changed on another device. Reload before saving.')
        initializing = not self.row_mode
        requests = self._initialize_rows(state) if initializing else []
        revision = str(uuid4())
        changes = []
        display = table_values(state)
        for title, key, items, visible in [('Sessions', 'sessionId', state['sessions'], display[0][1:]), ('Projects', 'id', state['nonprofits'], display[1][1:])]:
            old = self.entities[title]
            incoming = {p[key].lower(): (p, v) for p, v in zip(items, visible)}
            next_index = max([v['index'] for v in old.values()] + [0])+1
            for identity in dict.fromkeys([*old, *incoming]):
                before = old.get(identity)
                payload, view = incoming.get(identity, (before['payload'] if before else None, [''] * (8 if title == 'Sessions' else 3)))
                deleted = '0' if identity in incoming else '1'
                view = [v[:20000] if isinstance(v,str) else v for v in view]
                # Project totals can change even when the project itself does not.
                if before and before['payload'] == payload and before['deleted'] == deleted and before['row'][:len(view)] == view: continue
                text = json.dumps(payload, ensure_ascii=False)
                chunks = [text[i:i+20000] for i in range(0, len(text), 20000)]
                if len(chunks) > 1000: raise ValueError('This Tick row is too large. Use Local file storage.')
                row = view + [identity, revision, deleted, len(chunks)] + chunks
                index = before['index'] if before else next_index
                if not before: next_index += 1
                # Clear obsolete chunks if a long note became shorter.
                width = max(len(row), len(before['row']) if before else 0)
                request = self._update(title, index, [row]); request['updateCells']['range']['endColumnIndex'] = width
                requests.append(request)
                changes.append({'table': title, 'id': identity, 'row': row})
        if not changes and not initializing: return
        audit = json.dumps({'changes': changes}, ensure_ascii=False)
        chunks = [audit[i:i+20000] for i in range(0, len(audit), 20000)]
        if len(chunks) > 1000: raise ValueError('This change is too large. Use Local file storage.')
        for tab in self.metadata['sheets']:
            props = tab['properties']; title = props['title']
            if title not in ('Sessions','Projects','TickChanges'): continue
            updates = [r['updateCells'] for r in requests if 'updateCells' in r and r['updateCells']['range']['sheetId'] == props.get('sheetId', 0)]
            required_rows = max([u['range']['endRowIndex'] for u in updates] + [self.log_count + len(chunks) if title == 'TickChanges' else 1])
            required_columns = max([u['range']['endColumnIndex'] for u in updates] + [5])
            grid = props.get('gridProperties', {})
            if required_rows > grid.get('rowCount',1000) or required_columns > grid.get('columnCount',26):
                requests.insert(next((i for i,r in enumerate(requests) if 'updateCells' in r), len(requests)), {'updateSheetProperties': {'properties': {'sheetId': props['sheetId'], 'gridProperties': {'rowCount': max(required_rows,grid.get('rowCount',1000)), 'columnCount': max(required_columns,grid.get('columnCount',26))}}, 'fields': 'gridProperties.rowCount,gridProperties.columnCount'}})
        for request in list(requests):
            props = request.get('updateSheetProperties', {}).get('properties', {})
            columns = props.get('gridProperties', {}).get('columnCount')
            if columns:
                title = next(s['properties']['title'] for s in self.metadata['sheets'] if s['properties']['sheetId'] == props['sheetId'])
                if title in ('Sessions', 'Projects'):
                    requests.append({'updateDimensionProperties': {'range': {'sheetId': props['sheetId'], 'dimension': 'COLUMNS', 'startIndex': 8 if title == 'Sessions' else 3, 'endIndex': columns}, 'properties': {'hiddenByUser': True}, 'fields': 'hiddenByUser'}})
        log_id = next(s['properties']['sheetId'] for s in self.metadata['sheets'] if s['properties']['title'] == 'TickChanges')
        requests.append({'appendCells': {'sheetId': log_id, 'rows': cell_rows([[revision, (latest or '') if not initializing else '', i, len(chunks), c] for i,c in enumerate(chunks)]), 'fields': 'userEnteredValue'}})
        self.api.request('POST', self.base + ':batchUpdate', {'requests': requests})
        self.row_mode = True
        saved, confirmed, count = self._read_rows()
        def normalized(value):
            return dict(value, nonprofits=sorted(value['nonprofits'], key=lambda p: p['id']))
        rows_confirmed = all(self.entities[c['table']].get(c['id'], {}).get('row') == c['row'] for c in changes)
        if confirmed != revision or normalized(saved) != normalized(state) or not rows_confirmed: raise ValueError('Save could not be confirmed. Reload before retrying.')
        for request in requests:
            props = request.get('updateSheetProperties', {}).get('properties', {})
            if 'gridProperties' in props:
                tab = next(s['properties'] for s in self.metadata['sheets'] if s['properties'].get('sheetId', 0) == props['sheetId'])
                tab.setdefault('gridProperties', {}).update(props['gridProperties'])
        self.revision = confirmed; self.log_revision = confirmed; self.log_count = count

    def refresh_tables(self):
        state = self.load(require_existing=True)
        self.save(state)
        self.verify_tables(state)
        return state

    def verify_tables(self, state):
        saved = self.load(require_existing=True)
        expected = decode_data(json.dumps(state)); expected['sessions'].sort(key=lambda s: parse(s['startTimeUtc']))
        if saved != expected: raise ValueError('Tick rows could not be verified. Reload before retrying.')


def cell_rows(rows):
    return [{'values': [{'userEnteredValue': {'numberValue' if isinstance(v, (int, float)) else 'stringValue': v}} for v in row]} for row in rows]


def table_values(state):
    projects = {p['id']: p['name'] for p in state['nonprofits']}
    sessions = [['Project', 'Started (UTC)', 'Ended (UTC)', 'Duration', 'Hours', 'Notes', 'Status', 'Platform']]
    totals = {key: [0, 0] for key in projects}
    for s in sorted(state['sessions'], key=lambda s: parse(s['startTimeUtc'])):
        seconds = s.get('durationSeconds')
        duration = '' if seconds is None else f'{int(seconds)//3600}:{int(seconds)//60%60:02d}:{int(seconds)%60:02d}'
        sessions.append([projects.get(s['projectId'], s['project']), parse(s['startTimeUtc']).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                         parse(s['endTimeUtc']).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S') if s.get('endTimeUtc') else '', duration,
                         '' if seconds is None else seconds / 3600, s['notes'], 'Running' if s.get('endTimeUtc') is None else 'Completed', s['platform']])
        if s['projectId'] in totals:
            totals[s['projectId']][0] += (seconds or 0) / 3600
            totals[s['projectId']][1] += 1
    summary = [['Project', 'Total hours', 'Sessions']]
    summary += [[name, *totals[key]] for key, name in projects.items()]
    return [sessions, summary]


def decode_log(rows):
    """Every revision remains available; concurrent branches are errors, never silent overwrites."""
    latest, state, seen, position = None, None, set(), 0
    while position < len(rows):
        row = rows[position]
        if len(row) != 6 or row[0] != MARKER: raise ValueError('Invalid Tick history in Google Sheets.')
        revision, parent = str(row[1]), str(row[2])
        try: count = int(row[4])
        except (TypeError, ValueError) as error: raise ValueError('Invalid Tick history.') from error
        if not revision or revision in seen or count < 1 or count > 1000 or position + count > len(rows): raise ValueError('Incomplete Tick history. Keep the sheet for recovery.')
        if latest is not None and parent != latest:
            raise ValueError('Concurrent Google Sheets changes detected. Both versions are preserved in TickLog; export/recover before continuing.')
        parts = []
        for index in range(count):
            chunk = rows[position+index]
            if len(chunk) != 6 or chunk[:3] != row[:3] or int(chunk[3]) != index or int(chunk[4]) != count: raise ValueError('Invalid Tick history chunks.')
            parts.append(chunk[5])
        state = decode_data(''.join(parts)); latest = revision; seen.add(revision); position += count
    return state, latest
