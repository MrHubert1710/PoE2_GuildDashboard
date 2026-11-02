#!/usr/bin/env python3
"""Import undated legacy prices or enqueue shared worker jobs; never date by mtime."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.database import connect,migrate
from backend.jobs import Queue
from backend.prices import import_legacy

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['import-legacy','refresh','value','alias'])
    parser.add_argument('--database',type=Path,default=ROOT/'data/poe2guild.sqlite')
    parser.add_argument('--league')
    parser.add_argument('--source-name')
    parser.add_argument('--target-name')
    args=parser.parse_args();migrate(args.database)
    if args.command=='alias':
        from backend.prices import name_key
        if not args.league or not args.source_name or not args.target_name:parser.error('alias requires --league, --source-name and --target-name')
        with connect(args.database) as c:
            c.execute('INSERT OR REPLACE INTO price_aliases VALUES(?,?,?)',(args.league,name_key(args.source_name),name_key(args.target_name)))
        print(json.dumps(Queue(args.database).enqueue(args.league,'valuations','manual')))
    if args.command=='import-legacy':print(json.dumps({'inserted':import_legacy(args.database,args.database.resolve().parent)}))
    if args.command in {'import-legacy','refresh','value'}:
        with connect(args.database,readonly=True) as c:leagues=list(c.execute('SELECT id,name FROM leagues'))
        queue=Queue(args.database)
        for league in leagues:print(json.dumps({'league':league['name'],**queue.enqueue(league['id'],'prices' if args.command=='refresh' else 'valuations','manual')}))
