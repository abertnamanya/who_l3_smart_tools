import datetime
import os
import unittest
from unittest.mock import MagicMock

import pandas as pd
from who_l3_smart_tools.core.indicator_testing.bundle_generator import BundleGenerator


class TestBundleGenerator(unittest.TestCase):

    def test_generate_all_data(self):
        # Create a mock data file path and output directory
        input_path = "tests/data/test_data_file.xlsx"
        output_directory = "tests/output/fhir_data"

        # Make sure output directory exists
        if not os.path.exists(output_directory):
            os.makedirs(output_directory)

        # Get some general stats on input file
        input_file = pd.read_excel(input_path, sheet_name=None)
        num_sheets = len(input_file.keys())
        num_rows = {}
        for sheet in input_file.keys():
            num_rows[sheet] = len(input_file[sheet])

        # Create bundle with 1 year reporting period
        system_date = datetime.datetime.now(datetime.timezone.utc)
        start_date = (system_date - datetime.timedelta(days=365)).isoformat()
        end_date = system_date.isoformat()
        bundle_generator = BundleGenerator(
            input_path, output_directory, start_date, end_date
        )

        # Call the generate_all_data method
        all_data = bundle_generator.generate_all_data()

        # Check all data
        self.assertIsInstance(all_data, dict)
        self.assertEqual(len(all_data), num_sheets)
        for indicator, bundles in all_data.items():
            self.assertIsInstance(indicator, str)
            self.assertIsInstance(bundles, list)
            self.assertEqual(len(bundles), num_rows[indicator])
            for bundle in bundles:
                self.assertEqual(bundle.resource_type, "Bundle")
                self.assertIsInstance(bundle.entry, list)
                self.assertGreater(len(bundle.entry), 0)


if __name__ == "__main__":
    unittest.main()
