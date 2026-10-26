#!/usr/bin/env python3
"""List and export retained Tick revisions without modifying the spreadsheet."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'linux'))
from tick.google_auth import GoogleAccount
from tick.core import decode_data
from tick.sheets import GoogleSheetsAPI, spreadsheet_id, SHEETS, decode_log


def revisions(rows):
    result=[];position=0
    while position<len(rows):
        row=rows[position]
        if len(row)!=6:raise ValueError('Invalid TickLog row.')
        count=int(row[4]);block=rows[position:position+count]
        state,revision=decode_log(block)
        if state is None or revision is None:raise ValueError('Incomplete Tick revision.')
        result.append((revision,state));position+=count
    return result


def row_revisions(rows, root):
    """Replay changed entities by parent, retaining sibling branches for recovery."""
    snapshots = {}; result = []; position = 0
    while position < len(rows):
        row = rows[position]
        if len(row) != 5: raise ValueError('Invalid TickChanges row.')
        identity, parent, index, count, _ = row; count = int(count)
        if identity in snapshots or not identity or int(index) != 0 or count < 1 or count > 1000 or position+count > len(rows): raise ValueError('Incomplete Tick change.')
        parts = []
        for n, part in enumerate(rows[position:position+count]):
            if len(part) != 5 or part[:4] != [identity,parent,n,count]: raise ValueError('Invalid Tick change chunks.')
            parts.append(part[4])
        if parent and parent not in snapshots: raise ValueError('Missing parent change; recovery requires the full TickChanges journal.')
        # Copy parent maps; each new change replaces only its affected entities.
        previous = snapshots[parent] if parent else {'Sessions': {}, 'Projects': {}}
        current = {title: dict(records) for title, records in previous.items()}
        for change in json.loads(''.join(parts))['changes']:
            title = change['table']; offset, key = (8,'sessionId') if title == 'Sessions' else (3,'id')
            if title not in current: raise ValueError('Unknown Tick row type.')
            values = change['row']; identity_in_row, _, deleted, chunks = values[offset:offset+4]
            if deleted not in ('0','1') or int(chunks) < 1 or len(values) != offset+4+int(chunks): raise ValueError('Invalid recovered row.')
            payload = json.loads(''.join(values[offset+4:]))
            if payload[key].lower() != identity_in_row.lower() or identity_in_row != change['id']: raise ValueError('Recovered row identity changed.')
            if deleted == '1': current[title].pop(identity_in_row,None)
            else: current[title][identity_in_row] = payload
        state = decode_data(json.dumps(dict(root, sessions=list(current['Sessions'].values()), nonprofits=list(current['Projects'].values()))))
        snapshots[identity] = current; result.append((identity,state)); position += count
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spreadsheet',help='Spreadsheet ID or URL')
    parser.add_argument('--legacy-backup',action='store_true',help='Read pre-migration TickLogBackup revisions instead of current row changes')
    parser.add_argument('--revision',help='Revision ID to export; omit to list revisions')
    parser.add_argument('--output',type=Path,help='New JSON output file (never overwritten)')
    args=parser.parse_args(argv)
    try:
        if bool(args.revision)!=bool(args.output):parser.error('--revision and --output must be provided together')
        account=GoogleAccount()
        try:account.access_token()
        except ValueError:account.sign_in()
        api=GoogleSheetsAPI(account)
        base=SHEETS+'/'+spreadsheet_id(args.spreadsheet)
        metadata=api.request('GET',base+'?fields=sheets.properties')
        titles=[s['properties']['title'] for s in metadata['sheets']]
        if 'TickMeta' in titles and not args.legacy_backup:
            meta=api.request('GET',base+'/values/TickMeta!A1:B1').get('values',[])
            if len(meta)!=1 or meta[0][0]!='tick-rows-v1':raise ValueError('Invalid Tick row storage.')
            rows=api.request('GET',base+'/values/TickChanges!A:E').get('values',[])
            values=row_revisions(rows,json.loads(meta[0][1]))
        else:
            title='TickLogBackup' if args.legacy_backup else ('TickLog' if 'TickLog' in titles else 'TickLogBackup')
            if title not in titles:raise ValueError('No retained TickLog backup is available in this spreadsheet.')
            rows=api.request('GET',base+'/values/'+title+'!A:F').get('values',[])
            values=revisions(rows)
        if not args.revision:
            for revision,state in values:print(f"{revision}: {len(state['nonprofits'])} projects, {len(state['sessions'])} sessions")
        else:
            state=next((state for revision,state in values if revision==args.revision),None)
            if state is None:raise ValueError('Revision not found.')
            with args.output.open('x',encoding='utf-8') as stream:json.dump(state,stream,ensure_ascii=False,indent=2)
            print('Exported retained revision. Original spreadsheet is unchanged.')
        return 0
    except (OSError,ValueError,KeyError,TypeError) as error:
        print('Recovery failed: '+str(error),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
