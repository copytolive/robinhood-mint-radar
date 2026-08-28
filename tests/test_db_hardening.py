import os,tempfile,unittest
from radar.db import RadarDB

class DBHardeningTests(unittest.TestCase):
    def test_wal_integrity_and_backup(self):
        with tempfile.TemporaryDirectory() as td:
            path=os.path.join(td,'radar.sqlite')
            db=RadarDB(path)
            self.assertEqual(db.integrity_check(),'ok')
            self.assertIn(db.db_health()['journal_mode'].lower(),('wal','memory','delete'))
            out=db.backup(os.path.join(td,'backups'),keep=2)
            self.assertTrue(os.path.exists(out))
            db.close()
