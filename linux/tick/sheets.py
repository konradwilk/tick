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

    @property
    def base(self): return SHEETS + '/' + self.sheet_id

    def _read(self):
        metadata = self.api.request('GET', self.base + '?fields=sheets.properties,properties.title')
        self.metadata = metadata
        self.spreadsheet_name = metadata['properties']['title']
        tabs = [s['properties']['title'] for s in metadata.get('sheets', [])]
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

    def save(self, state):
        state = decode_data(json.dumps(state))
        state = dict(state, sessions=sorted(state['sessions'], key=lambda s: parse(s['startTimeUtc'])))
        _, latest = self._read()
        if latest != self.revision: raise ValueError('Data changed on another device. Reload before saving.')
        if not self.has_log:
            self.api.request('POST', self.base + ':batchUpdate', {'requests': [{'addSheet': {'properties': {'title': 'TickLog', 'gridProperties': {'rowCount': 1000, 'columnCount': 6}}}}]})
            self._read()
        revision = str(uuid4())
        raw = json.dumps(state, ensure_ascii=False)
        chunks = [raw[i:i+20000] for i in range(0, len(raw), 20000)]
        if len(chunks) > 1000: raise ValueError('This dataset is too large for a Tick revision in Google Sheets. Use Local file storage.')
        rows = [[MARKER, revision, self.revision or '', i, len(chunks), chunk] for i, chunk in enumerate(chunks)]
        requests = table_requests(state, self.metadata)
        log_id = next(s['properties'].get('sheetId', 0) for s in self.metadata['sheets'] if s['properties']['title'] == 'TickLog')
        requests.append({'appendCells': {'sheetId': log_id, 'rows': cell_rows(rows), 'fields': 'userEnteredValue'}})
        self.api.request('POST', self.base + ':batchUpdate', {'requests': requests})
        saved, confirmed = self._read()
        if confirmed != revision or saved != state: raise ValueError('Save could not be confirmed. Reload before retrying.')
        self.revision = revision

    def refresh_tables(self):
        """Upgrade an existing Tick sheet without appending or changing its history."""
        state, revision = self._read()
        if state is None: raise ValueError('No Tick data to display.')
        self.api.request('POST', self.base + ':batchUpdate', {'requests': table_requests(state, self.metadata)})
        saved, confirmed = self._read()
        if confirmed != revision or saved != state: raise ValueError('Data changed during the layout upgrade. Reload and retry.')
        self.verify_tables(state)
        self.revision = revision
        return state

    def verify_tables(self, state):
        for title, expected in zip(("Sessions", "Projects"), table_values(state)):
            expected = [[v[:20000] if isinstance(v, str) else v for v in row] for row in expected]
            end = "H" if title == "Sessions" else "C"
            actual = self.api.request("GET", self.base + f"/values/{title}!A1:{end}{len(expected)}?valueRenderOption=UNFORMATTED_VALUE").get("values", [])
            if actual != expected: raise ValueError(f"The {title} table could not be verified. Keep the spreadsheet and run --upgrade-existing to refresh it.")


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


def table_requests(state, metadata):
    import copy
    tabs = {s['properties']['title']: s['properties'] for s in metadata['sheets']}
    used = {s.get('sheetId', 0) for s in tabs.values()}
    requests = []
    for index, (title, rows) in enumerate(zip(('Sessions', 'Projects'), table_values(state))):
        if title in tabs:
            sheet_id = tabs[title].get('sheetId', 0)
            size = max(tabs[title].get('gridProperties', {}).get('rowCount', 1000), len(rows), 2)
        else:
            sheet_id = 174001 + index
            while sheet_id in used: sheet_id += 1
            used.add(sheet_id)
            size = max(1000, len(rows))
            requests.append({'addSheet': {'properties': {'sheetId': sheet_id, 'title': title, 'gridProperties': {'rowCount': size, 'columnCount': len(rows[0])}}}})
        requests.append({'updateSheetProperties': {'properties': {'sheetId': sheet_id, 'gridProperties': {'rowCount': size}}, 'fields': 'gridProperties.rowCount'}})
        # Text is always literal, even when a note starts with '='. Long text remains complete in TickLog.
        cells = cell_rows([[v[:20000] if isinstance(v, str) else v for v in row] for row in rows])
        cells[0]['values'][0]['note'] = 'Generated by Tick. Edit projects and sessions in Tick; these tables refresh on every save.'
        parts = copy.deepcopy(TABLE_STYLES[index])
        for part in parts:
            payload = next(iter(part.values()))
            if 'properties' in payload and 'sheetId' in payload['properties']: payload['properties']['sheetId'] = sheet_id
            if 'range' in payload: payload['range']['sheetId'] = sheet_id
            if 'filter' in payload:
                payload['filter']['range']['sheetId'] = sheet_id
                payload['filter']['range']['endRowIndex'] = max(2, len(rows))
        parts[1]['updateCells']['rows'] = cells
        requests.extend(parts)
        hours_column = 4 if index == 0 else 1
        requests.append({'repeatCell': {'range': {'sheetId': sheet_id, 'startRowIndex': 1, 'startColumnIndex': hours_column, 'endColumnIndex': hours_column+1}, 'cell': {'userEnteredFormat': {'numberFormat': {'type': 'NUMBER', 'pattern': '0.00'}}}, 'fields': 'userEnteredFormat.numberFormat'}})
        if index == 0:
            requests.append({'updateDimensionProperties': {'range': {'sheetId': sheet_id, 'dimension': 'COLUMNS', 'startIndex': 5, 'endIndex': 6}, 'properties': {'pixelSize': 420}, 'fields': 'pixelSize'}})
    for title in ('TickLog', 'TickData'):
        if title in tabs:
            requests.append({'updateSheetProperties': {'properties': {'sheetId': tabs[title].get('sheetId', 0), 'hidden': True}, 'fields': 'hidden'}})
    return requests


# Common presentation contract; keep native client layouts in sync.
TABLE_STYLES = [[{'updateSheetProperties': {'properties': {'sheetId': 0,
                                            'index': 0,
                                            'hidden': False,
                                            'gridProperties': {'frozenRowCount': 1}},
                             'fields': 'index,hidden,gridProperties.frozenRowCount'}},
  {'updateCells': {'range': {'sheetId': 0}, 'rows': [], 'fields': 'userEnteredValue,note'}},
  {'repeatCell': {'range': {'sheetId': 0, 'startRowIndex': 0, 'endRowIndex': 1},
                  'cell': {'userEnteredFormat': {'backgroundColor': {'red': 0.92,
                                                                     'green': 0.93,
                                                                     'blue': 0.94},
                                                 'textFormat': {'bold': True,
                                                                'foregroundColor': {'red': 0,
                                                                                    'green': 0,
                                                                                    'blue': 0}},
                                                 'wrapStrategy': 'WRAP'}},
                  'fields': 'userEnteredFormat'}},
  {'repeatCell': {'range': {'sheetId': 0, 'startRowIndex': 1},
                  'cell': {'userEnteredFormat': {'verticalAlignment': 'TOP', 'wrapStrategy': 'WRAP'}},
                  'fields': 'userEnteredFormat'}},
  {'updateDimensionProperties': {'range': {'sheetId': 0,
                                           'dimension': 'COLUMNS',
                                           'startIndex': 0,
                                           'endIndex': 8},
                                 'properties': {'pixelSize': 160},
                                 'fields': 'pixelSize'}},
  {'setBasicFilter': {'filter': {'range': {'sheetId': 0,
                                           'startRowIndex': 0,
                                           'endRowIndex': 1,
                                           'startColumnIndex': 0,
                                           'endColumnIndex': 8}}}}],
 [{'updateSheetProperties': {'properties': {'sheetId': 0,
                                            'index': 1,
                                            'hidden': False,
                                            'gridProperties': {'frozenRowCount': 1}},
                             'fields': 'index,hidden,gridProperties.frozenRowCount'}},
  {'updateCells': {'range': {'sheetId': 0}, 'rows': [], 'fields': 'userEnteredValue,note'}},
  {'repeatCell': {'range': {'sheetId': 0, 'startRowIndex': 0, 'endRowIndex': 1},
                  'cell': {'userEnteredFormat': {'backgroundColor': {'red': 0.92,
                                                                     'green': 0.93,
                                                                     'blue': 0.94},
                                                 'textFormat': {'bold': True,
                                                                'foregroundColor': {'red': 0,
                                                                                    'green': 0,
                                                                                    'blue': 0}},
                                                 'wrapStrategy': 'WRAP'}},
                  'fields': 'userEnteredFormat'}},
  {'repeatCell': {'range': {'sheetId': 0, 'startRowIndex': 1},
                  'cell': {'userEnteredFormat': {'verticalAlignment': 'TOP', 'wrapStrategy': 'WRAP'}},
                  'fields': 'userEnteredFormat'}},
  {'updateDimensionProperties': {'range': {'sheetId': 0,
                                           'dimension': 'COLUMNS',
                                           'startIndex': 0,
                                           'endIndex': 3},
                                 'properties': {'pixelSize': 160},
                                 'fields': 'pixelSize'}},
  {'setBasicFilter': {'filter': {'range': {'sheetId': 0,
                                           'startRowIndex': 0,
                                           'endRowIndex': 1,
                                           'startColumnIndex': 0,
                                           'endColumnIndex': 3}}}}]]

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
