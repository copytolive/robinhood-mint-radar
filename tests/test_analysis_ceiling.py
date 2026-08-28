import unittest
from radar.live_scanner import activity_core,cheap_analysis_class


def metrics(core_velocity=0,accel=0,unique=0,velocity5=0):
    return {
        'velocity_1m':core_velocity,
        'acceleration_5m':accel,
        'unique_recent_minters':unique,
        'velocity_5m':velocity5,
    }


class AnalysisCeilingTests(unittest.TestCase):
    def test_regular_qualification_boundary_is_not_pruned(self):
        # velocity score 20 + acceleration 0 + holders 10 = core 30.
        m=metrics(core_velocity=20,unique=20)
        self.assertEqual(activity_core(m),30)
        self.assertEqual(cheap_analysis_class(m,has_market=True),'REGULAR_POSSIBLE')

    def test_below_regular_boundary_can_still_be_watch(self):
        # core 29 cannot mathematically reach score 85, even with every
        # expensive regular component maxed, but may still be worth WATCH.
        m=metrics(core_velocity=13,unique=20)  # int(19.5)+10 = 29
        self.assertEqual(activity_core(m),29)
        self.assertEqual(cheap_analysis_class(m,has_market=True),'WATCH')

    def test_early_boundary_requires_activity_and_hoodsea_gates(self):
        # core 40: velocity 20 + accel 10 + holders 10.
        m=metrics(core_velocity=20,accel=1.34,unique=20,velocity5=2)
        self.assertEqual(activity_core(m),40)
        self.assertEqual(cheap_analysis_class(m,known_launch=True),'EARLY_POSSIBLE')
        self.assertNotEqual(cheap_analysis_class(m,known_launch=False),'EARLY_POSSIBLE')

    def test_low_ceiling_is_skipped_without_market_or_launch(self):
        m=metrics(core_velocity=1,unique=1)
        self.assertLess(activity_core(m),20)
        self.assertEqual(cheap_analysis_class(m),'SKIP')


if __name__=='__main__':unittest.main()
