#!/usr/bin/env python3
"""List and export a retained TickLog revision without modifying the spreadsheet."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'linux'))
from tick.google_auth import GoogleAccount
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


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spreadsheet',help='Spreadsheet ID or URL')
    parser.add_argument('--revision',help='Revision ID to export; omit to list revisions')
    parser.add_argument('--output',type=Path,help='New JSON output file (never overwritten)')
    args=parser.parse_args(argv)
    try:
        if bool(args.revision)!=bool(args.output):parser.error('--revision and --output must be provided together')
        account=GoogleAccount()
        try:account.access_token()
        except ValueError:account.sign_in()
        api=GoogleSheetsAPI(account)
        rows=api.request('GET',SHEETS+'/'+spreadsheet_id(args.spreadsheet)+'/values/TickLog!A:F').get('values',[])
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
