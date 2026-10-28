import unittest
from unittest.mock import patch
import update_catalog as catalog


class CatalogTests(unittest.TestCase):
    def test_addresses(self):
        self.assertEqual(catalog.host_address("EXAMPLE.COM.", 25565), "example.com")
        self.assertEqual(catalog.host_address("example.com", 25566), "example.com:25566")
        self.assertIsNone(catalog.host_address("127.0.0.1", 25565))
        self.assertIsNone(catalog.host_address("localhost", 25565))
        self.assertIsNone(catalog.host_address("evil.com/path", 25565))
        self.assertIsNone(catalog.host_address("example.com", 0))

    def test_normalization_preserves_unknowns(self):
        value = catalog.normalize({"host": "play.example.com", "name": "  A   server ", "status": "online", "players_online": None, "requires_mods": None})
        self.assertEqual(value["name"], "A server")
        self.assertIsNone(value["playersOnline"])
        self.assertIsNone(value["requiresMods"])

    def test_failed_update_preserves_previous_file(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / "servers.json"
            output.write_text("old snapshot")
            with patch.object(catalog, "OUT", output), patch.object(catalog, "fetch_page", side_effect=RuntimeError("network")):
                with self.assertRaises(RuntimeError):
                    catalog.update()
            self.assertEqual(output.read_text(), "old snapshot")


if __name__ == "__main__":
    unittest.main()
