from app.core.scene_detector import merge_boundaries, scene_list_to_boundaries


class FakeTimecode:
    def __init__(self, seconds):
        self.seconds = seconds

    def get_seconds(self):
        return self.seconds


def test_scene_list_to_boundaries_skips_start_and_end():
    scene_list = [
        (FakeTimecode(0.0), FakeTimecode(10.0)),
        (FakeTimecode(10.0), FakeTimecode(20.0)),
        (FakeTimecode(99.5), FakeTimecode(100.0)),
    ]

    boundaries = scene_list_to_boundaries(
        scene_list,
        duration=100.0,
        min_boundary_gap_seconds=1.0,
    )

    assert boundaries == [0.0, 10.0]


def test_merge_boundaries_keeps_existing_and_skips_near_duplicates():
    merged = merge_boundaries(
        existing=[0.0, 10.0],
        detected=[10.1, 20.0, 99.0],
        duration=60.0,
        tolerance_seconds=0.25,
    )

    assert merged == [0.0, 10.0, 20.0]
