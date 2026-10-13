"""Rebuildable daily parent totals; authoritative daily records are untouched."""
import time
from datetime import date,timedelta
LEVELS=(8,11,14)
COUNTS=('observation_count','passage_count','below_1200_ft','1200_to_17999_ft','18000_ft_and_above','unknown')
FIELDS=COUNTS+('min_ft','max_ft','first_observed','last_observed','history_complete')
def q(name):return '"'+name+'"'

def schema():
    columns=', '.join(q(k)+(' INTEGER NOT NULL' if k in COUNTS or k=='history_complete' else ' REAL') for k in FIELDS)
    statements=[f'CREATE TABLE IF NOT EXISTS density_rollups(cell TEXT NOT NULL, day TEXT NOT NULL,{columns},PRIMARY KEY(cell,day))',
        'CREATE INDEX IF NOT EXISTS density_rollups_day ON density_rollups(day)',
        'CREATE TABLE IF NOT EXISTS density_rollup_locations(cell TEXT PRIMARY KEY,zoom INTEGER NOT NULL,x INTEGER NOT NULL,y INTEGER NOT NULL)',
        'CREATE INDEX IF NOT EXISTS density_rollup_xy ON density_rollup_locations(zoom,x,y,cell)',
        'CREATE TABLE IF NOT EXISTS density_rollup_ready(zoom INTEGER NOT NULL,day TEXT NOT NULL,PRIMARY KEY(zoom,day))',
        'CREATE TABLE IF NOT EXISTS density_rollup_dirty(zoom INTEGER NOT NULL,day TEXT NOT NULL,PRIMARY KEY(zoom,day))']
    monotonic=' AND '.join('NEW.'+q(k)+'>=OLD.'+q(k) for k in COUNTS)
    monotonic+=' AND NEW.cell=OLD.cell AND NEW.day=OLD.day AND NEW.last_observed>=OLD.last_observed AND NEW.history_complete<=OLD.history_complete'
    monotonic+=' AND (OLD.min_ft IS NULL OR (NEW.min_ft IS NOT NULL AND NEW.min_ft<=OLD.min_ft)) AND (OLD.max_ft IS NULL OR (NEW.max_ft IS NOT NULL AND NEW.max_ft>=OLD.max_ft))'
    monotonic+=' AND (OLD.first_observed IS NULL OR NEW.first_observed IS NULL OR NEW.first_observed<=OLD.first_observed)'
    for level in LEVELS:
        shift=17-level
        def xy(prefix):
            cell=prefix+'.cell'
            return (f'(CAST(substr({cell},4,instr(substr({cell},4),\'/\')-1) AS INTEGER) >> {shift})',f'(CAST(substr({cell},4+instr(substr({cell},4),\'/\')) AS INTEGER) >> {shift})')
        x,y=xy('NEW');parent=f"'{level}/' || {x} || '/' || {y}"
        ready=f'EXISTS(SELECT 1 FROM density_rollup_ready WHERE zoom={level} AND day=NEW.day) AND NOT EXISTS(SELECT 1 FROM density_rollup_dirty WHERE zoom={level} AND day=NEW.day)'
        updates=[q(k)+'='+q(k)+'+excluded.'+q(k) for k in COUNTS]
        updates+=['min_ft=CASE WHEN min_ft IS NULL THEN excluded.min_ft WHEN excluded.min_ft IS NULL THEN min_ft ELSE min(min_ft,excluded.min_ft) END',
            'max_ft=CASE WHEN max_ft IS NULL THEN excluded.max_ft WHEN excluded.max_ft IS NULL THEN max_ft ELSE max(max_ft,excluded.max_ft) END',
            'first_observed=CASE WHEN history_complete=0 OR excluded.history_complete=0 THEN NULL ELSE min(first_observed,excluded.first_observed) END',
            'last_observed=max(last_observed,excluded.last_observed)','history_complete=min(history_complete,excluded.history_complete)']
        def insert(delta=False):
            values=[('NEW.'+q(k)+'-OLD.'+q(k) if delta and k in COUNTS else 'NEW.'+q(k)) for k in FIELDS]
            return f'INSERT INTO density_rollups SELECT {parent},NEW.day,'+','.join(values)+f' WHERE {ready} ON CONFLICT(cell,day) DO UPDATE SET '+','.join(updates)+';'
        loc=f'INSERT INTO density_rollup_locations SELECT {parent},{level},{x},{y} WHERE {ready} ON CONFLICT(cell) DO NOTHING;'
        statements.append(f'CREATE TRIGGER IF NOT EXISTS density_rollup_insert_{level} AFTER INSERT ON daily BEGIN '+loc+insert()+' END')
        statements.append(f'CREATE TRIGGER IF NOT EXISTS density_rollup_update_{level} AFTER UPDATE ON daily WHEN '+monotonic+' BEGIN '+loc+insert(True)+' END')
        dirty=f'INSERT INTO density_rollup_dirty SELECT {level},OLD.day WHERE EXISTS(SELECT 1 FROM density_rollup_ready WHERE zoom={level} AND day=OLD.day) ON CONFLICT(zoom,day) DO NOTHING;'
        newdirty=f'INSERT INTO density_rollup_dirty SELECT {level},NEW.day WHERE EXISTS(SELECT 1 FROM density_rollup_ready WHERE zoom={level} AND day=NEW.day) ON CONFLICT(zoom,day) DO NOTHING;'
        statements.append(f'CREATE TRIGGER IF NOT EXISTS density_rollup_replace_{level} AFTER UPDATE ON daily WHEN NOT ({monotonic}) BEGIN '+dirty+newdirty+' END')
        statements.append(f'CREATE TRIGGER IF NOT EXISTS density_rollup_delete_{level} AFTER DELETE ON daily BEGIN '+dirty+' END')
    return ';\n'.join(statements)+';'


def ensure(db,level,start,end,month):
    """Atomic backfill of absent/invalid day totals. Caller holds collection lock."""
    month_start=date.fromisoformat(month+'-01')
    month_end=(month_start.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)
    lower=max(date.fromisoformat(start),month_start)
    upper=min(date.fromisoformat(end),month_end)
    ready={r[0] for r in db.execute('SELECT day FROM density_rollup_ready WHERE zoom=? AND day BETWEEN ? AND ?',(level,start,end))}
    dirty={r[0] for r in db.execute('SELECT day FROM density_rollup_dirty WHERE zoom=? AND day BETWEEN ? AND ?',(level,start,end))}
    # Consult at most 31 readiness records, rather than rescan fine daily history
    # to discover its dates on every view. Empty days also get readiness markers;
    # later observations maintain those parents through the same insert trigger.
    days=[]
    while lower<=upper:
        day=lower.isoformat()
        if day not in ready or day in dirty:days.append(day)
        lower+=timedelta(days=1)
    if not days:return {'rebuilt_days':0,'seconds':0.0}
    started=time.perf_counter()
    print(f'[INFO] Density parent rebuild started: month={month} zoom={level} days={len(days)}',flush=True)
    shift=17-level
    for day in days:
        with db:
            db.execute('DELETE FROM density_rollups WHERE day=? AND cell LIKE ?',(day,f'{level}/%'))
            db.execute('''INSERT INTO density_rollups SELECT ? || '/' || (l.x >> ?) || '/' || (l.y >> ?),d.day,
                sum(observation_count),sum(passage_count),sum(below_1200_ft),sum("1200_to_17999_ft"),sum("18000_ft_and_above"),sum(unknown),
                min(min_ft),max(max_ft),CASE WHEN min(history_complete)=0 THEN NULL ELSE min(first_observed) END,max(last_observed),min(history_complete)
                FROM daily d JOIN cell_locations l ON l.cell=d.cell WHERE d.day=? GROUP BY (l.x >> ?),(l.y >> ?),d.day''',(level,shift,shift,day,shift,shift))
            db.execute('''INSERT OR IGNORE INTO density_rollup_locations SELECT DISTINCT cell,?,
                CAST(substr(cell,instr(cell,'/')+1,instr(substr(cell,instr(cell,'/')+1),'/')-1) AS INTEGER),
                CAST(substr(cell,instr(cell,'/')+instr(substr(cell,instr(cell,'/')+1),'/')+1) AS INTEGER)
                FROM density_rollups WHERE day=? AND cell LIKE ?''',(level,day,f'{level}/%'))
            db.execute('INSERT OR IGNORE INTO density_rollup_ready VALUES (?,?)',(level,day))
            db.execute('DELETE FROM density_rollup_dirty WHERE zoom=? AND day=?',(level,day))
    elapsed=round(time.perf_counter()-started,4)
    print(f'[INFO] Density parent rebuild completed: month={month} zoom={level} days={len(days)} seconds={elapsed}',flush=True)
    return {'rebuilt_days':len(days),'seconds':elapsed}
