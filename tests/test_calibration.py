import unittest
from radar.calibration import calibration_metrics,probability_from_score

class CalibrationTests(unittest.TestCase):
    def test_metrics_and_status(self):
        rows=[{'predicted_probability':0.8,'outcome':1} for _ in range(15)]+[{'predicted_probability':0.2,'outcome':0} for _ in range(15)]
        m=calibration_metrics(rows)
        self.assertEqual(m['status'],'CALIBRATION_WARMUP')
        self.assertLess(m['brier'],0.1)
    def test_score_probability_monotonic(self):
        self.assertLess(probability_from_score(60),probability_from_score(90))
