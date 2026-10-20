"""경계 위, 구멍, 중첩 경계를 임의로 정상 처리하지 않는지 확인한다."""
import sys
from pathlib import Path
import unittest
import importlib.util

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "data_processing"))
AVAILABLE = all(importlib.util.find_spec(name) for name in ["shapely", "pyproj", "shapefile"])
if AVAILABLE:
    import pandas as pd
    from shapely.geometry import Polygon, box
    from validate_regions import classify_points


@unittest.skipUnless(AVAILABLE, "requirements.txt 설치 필요")
class SpatialValidationTests(unittest.TestCase):
    def test_inside_border_outside_and_wrong_code(self):
        attributes = pd.DataFrame({"SIGUNGU_CD": ["A", "B"]})
        result = classify_points([1, 0, 3, 1], [1, 1, 1, 1], ["A", "A", "A", "B"],
                                 attributes, [box(0, 0, 2, 2), box(5, 0, 7, 2)])
        self.assertEqual(result["공간판정"].tolist(),
                         ["interior_match", "boundary_match", "no_polygon", "code_mismatch"])

    def test_polygon_hole_is_not_inside(self):
        polygon = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)],
                          holes=[[(1, 1), (1, 3), (3, 3), (3, 1)]])
        result = classify_points([2], [2], ["A"], pd.DataFrame({"SIGUNGU_CD": ["A"]}), [polygon])
        self.assertEqual(result.loc[0, "공간판정"], "no_polygon")
        self.assertEqual(result.loc[0, "코드경계까지m"], 1)

    def test_shared_boundary_preserves_both_candidates(self):
        result = classify_points([2], [1], ["A"], pd.DataFrame({"SIGUNGU_CD": ["A", "B"]}),
                                 [box(0, 0, 2, 2), box(2, 0, 4, 2)])
        self.assertEqual(result.loc[0, "공간판정"], "multiple_polygons")
        self.assertEqual(result.loc[0, "좌표지역코드"], "A|B")


if __name__ == "__main__":
    unittest.main()
