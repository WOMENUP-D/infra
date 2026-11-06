"""Regression checks adapted to project-only snapshot recovery."""
from pathlib import Path
import sys, tempfile, time, os, json
sys.path.insert(0, str(Path(__file__).parent))
from backup import prune
root=Path(__file__).parent
body=(root/'deploy.sh').read_text().split('deploy_backend() {',1)[1]
assert body.index('scripts/backup.sh') < body.index('c stop backend worker')
assert '--confirm' in (root/'restore.sh').read_text()
assert 'womanup-backup.timer' in (root/'bootstrap.sh').read_text()
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory)
    for i in range(5):
        snapshot=path / f'2026090{i+1}T000000Z-aaaaaaaa'
        snapshot.mkdir()
        for name in ('database.dump','media.tar.gz'): (snapshot/name).write_text('test')
        (snapshot/'manifest.json').write_text(json.dumps({'database':'womanup_db'}))
        age=time.time()-(20+i)*86400
        os.utime(snapshot,(age,age))
    prune(path)
    assert len(list(path.iterdir())) == 3
print('project backup ordering, confirmation, timer and minimum retention passed')
