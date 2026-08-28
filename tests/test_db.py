import os,tempfile,unittest
from radar.db import RadarDB

class DBTests(unittest.TestCase):
    def test_checkpoint_survives_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            p=os.path.join(td,'radar.sqlite')
            db=RadarDB(p); db.set_meta('last_block',123); db.close()
            db=RadarDB(p); self.assertEqual(db.last_block(),123); db.close()

if __name__=='__main__': unittest.main()
