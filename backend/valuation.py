"""Reproducible per-operation valuation, never backfilled with future prices."""
import hashlib
from .archive_import import canonical
from .database import connect,utc_now
from .prices import PriceIndex,price_revision,ATOMIC,CURRENCY
from .quantities import current_run

ALGORITHM='valuation-v1'


def current_valuation(c,league,mode):
    run=current_run(c,league)
    revision=price_revision(c,league['id'])
    value=c.execute('SELECT * FROM valuation_runs WHERE quantity_run_id=? AND price_revision=? AND mode=? AND algorithm_version=?',(run['id'],revision,mode,ALGORITHM)).fetchone() if run else None
    return value,revision


def money(value):return float(value/ATOMIC)


class ValuationAdapter:
    def stage(self,queue,job,stop):
        from .worker import AdapterFailure
        with connect(queue.path,readonly=True) as c:
            c.execute('BEGIN');league=queue.league(c,job['league_id']);run=current_run(c,league)
            if not run:raise AdapterFailure('quantity_projection_missing',retryable=False)
            revision=price_revision(c,league['id']);index=PriceIndex(c,league['id'])
            ledger=[dict(row) for row in c.execute('SELECT m.*,t.occurred_at FROM quantity_ledger m JOIN transactions t ON t.id=m.transaction_id WHERE m.run_id=? ORDER BY t.occurred_at,m.transaction_id,m.sequence',(run['id'],))]
            staged=[]
            for mode in ('historical','latest'):
                identity=hashlib.sha256(canonical([run['id'],revision,mode,ALGORITHM]).encode()).hexdigest();lines=[]
                for row in ledger:
                    if stop.is_set():raise AdapterFailure('interrupted')
                    result,reason=index.resolve(row['item_name'],row['occurred_at'],mode)
                    snapshot,quote=result if result else (None,None)
                    lines.append((identity,row['transaction_id'],row['sequence'],snapshot['id'] if snapshot else None,quote['quote_key'] if quote else None,
                                  quote['price_atomic'] if quote else None,str(row['quantity_delta']*int(quote['price_atomic'])) if quote else None,
                                  ('estimated_undated' if snapshot['effective_at'] is None else 'priced') if snapshot else reason))
                staged.append((identity,mode,lines))
        def publish(c):
            latest=current_run(c,league)
            if not latest or latest['id']!=run['id'] or price_revision(c,league['id'])!=revision:raise AdapterFailure('data_changed')
            for identity,mode,lines in staged:
                inserted=c.execute('INSERT OR IGNORE INTO valuation_runs VALUES(?,?,?,?,?,?,?)',(identity,run['id'],league['id'],revision,mode,ALGORITHM,utc_now())).rowcount
                if inserted:c.executemany('INSERT INTO valuation_lines VALUES(?,?,?,?,?,?,?,?)',lines)
            return dict(price_revision=revision,quantity_run_id=run['id'],modes=['historical','latest'])
        return publish
