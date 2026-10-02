const SCHEMA_VERSION = 1;

function doGet(e) {
  return jsonResponse({ ok: true, schemaVersion: SCHEMA_VERSION });
}

function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents || '{}');
    validateSession(payload);

    const sheet = getSessionsSheet();
    const values = sheet.getDataRange().getValues();
    const headers = values.length ? values[0] : [];
    const idCol = headers.indexOf('sessionId');
    let rowIndex = -1;

    if (idCol >= 0) {
      for (let i = 1; i < values.length; i++) {
        if (values[i][idCol] === payload.sessionId) {
          rowIndex = i + 1;
          break;
        }
      }
    }

    const row = sessionToRow(payload);
    if (rowIndex > 0) {
      sheet.getRange(rowIndex, 1, 1, row.length).setValues([row]);
      return jsonResponse({ ok: true, sessionId: payload.sessionId, action: 'updated' });
    }

    sheet.appendRow(row);
    return jsonResponse({ ok: true, sessionId: payload.sessionId, action: 'inserted' });
  } catch (err) {
    return jsonResponse({ ok: false, error: String(err.message || err) });
  }
}

function getSessionsSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName('Sessions');
  if (!sheet) sheet = ss.insertSheet('Sessions');

  if (sheet.getLastRow() === 0) {
    sheet.appendRow([
      'sessionId', 'projectId', 'project', 'date', 'startTimeUtc',
      'endTimeUtc', 'durationSeconds', 'hours', 'notes', 'deviceId',
      'platform', 'updatedAtUtc'
    ]);
  }
  return sheet;
}

function sessionToRow(s) {
  const hours = s.durationSeconds == null ? '' : Number(s.durationSeconds) / 3600;
  const date = s.startTimeUtc ? String(s.startTimeUtc).slice(0, 10) : '';
  return [
    s.sessionId, s.projectId, s.project, date, s.startTimeUtc,
    s.endTimeUtc || '', s.durationSeconds == null ? '' : s.durationSeconds,
    hours, s.notes || '', s.deviceId, s.platform, s.updatedAtUtc
  ];
}

function validateSession(s) {
  const required = ['sessionId', 'projectId', 'project', 'startTimeUtc', 'deviceId', 'platform', 'updatedAtUtc'];
  required.forEach(k => {
    if (!s[k]) throw new Error('Missing required field: ' + k);
  });
}

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
