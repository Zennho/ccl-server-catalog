import unittest
from unittest.mock import patch
import update_catalog as catalog


class CatalogTests(unittest.TestCase):
    def test_addresses(self):
        self.assertEqual(catalog.host_address("EXAMPLE.COM.", 25565), "example.com")
        self.assertEqual(catalog.host_address("example.com", 25566), "example.com:25566")
        self.assertEqual(catalog.host_address("example.com:25566", 25565), "example.com:25566")
        self.assertEqual(catalog.host_address("[2606:4700:4700::1111]:25566", 25565), "[2606:4700:4700::1111]:25566")
        self.assertNotIn("\ud835", catalog.text("broken\ud835name"))
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
            with patch.object(catalog, "OUT", output), patch.object(catalog, "fetch_source", side_effect=RuntimeError("network")):
                with self.assertRaises(RuntimeError):
                    catalog.update()
            self.assertEqual(output.read_text(), "old snapshot")


class MultiSourceTests(unittest.TestCase):
    def test_normalizes_each_source_and_rejects_private_addresses(self):
        samples = {
            "minecraftservers": {"host":"play.example.com","online":True,"players":{"online":2,"max":20},"tags":["survival"]},
            "mcsrvlist": {"host":"play.example.com","online":False,"players":1,"maxPlayers":20,"modes":["SMP"]},
            "msid": {"address":"play.example.com","status":"ONLINE","currentPlayers":4,"maxPlayers":50},
            "anyserver": {"address":"play.example.com","is_online":1,"player_count":3,"max_players":30},
            "cloudclient": {"address":"play.example.com","playersOnline":2,"playersMax":20},
            "msl": {"ipAddress":"play.example.com","isOnline":True,"currentPlayers":1,"maxPlayers":5},
        }
        for source, entry in samples.items():
            with self.subTest(source=source):
                record = catalog.normalize(entry, source)
                self.assertEqual(record["address"],"play.example.com")
                self.assertEqual(record["sourceIds"],[source])
                self.assertNotEqual(record["playersOnline"],None)
        self.assertIsNone(catalog.normalize({"address":"127.0.0.1"},"msid"))

    def test_merges_duplicates_without_losing_sources(self):
        a=catalog.normalize({"host":"PLAY.EXAMPLE.COM","name":"A"})
        b=catalog.normalize({"address":"play.example.com","description":"Hello","status":"ONLINE","currentPlayers":5,"maxPlayers":10},"msid")
        rows=catalog.merge([("minecraft-java-servers",[a]),("msid",[b])])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["sourceIds"],["minecraft-java-servers","msid"])
        self.assertTrue(rows[0]["description"].startswith("Hello"))
        self.assertEqual(rows[0]["playersOnline"],5)
        self.assertIn("minecraftserver.id", rows[0]["description"])

    def test_partial_outage_retains_previous_source_and_reports_stale(self):
        import tempfile,json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/"servers.json"
            previous={"updatedAt":"2025-01-01T00:00:00Z","servers":[catalog.normalize({"host":"old.example.com"})]}
            output.write_text(json.dumps(previous))
            def fetch(source):
                if source=="minecraft-java-servers": raise RuntimeError("offline")
                return ([{"address":"new.example.com","status":"ONLINE"}],False)
            sources={"minecraft-java-servers":catalog.SOURCES["minecraft-java-servers"],"msid":catalog.SOURCES["msid"]}
            with patch.object(catalog,"OUT",output),patch.object(catalog,"SOURCES",sources),patch.object(catalog,"fetch_source",side_effect=fetch):catalog.update()
            data=json.loads(output.read_text());self.assertEqual({x["address"] for x in data["servers"]},{"old.example.com","new.example.com"});self.assertEqual(data["sources"][0]["status"],"stale");self.assertEqual(data["sources"][0]["updatedAt"],previous["updatedAt"])

    def test_pagination_detects_missing_middle_pages(self):
        data=[{"records":[1],"pages":3},{"records":[],"pages":3}]
        with patch.object(catalog,"fetch_json",side_effect=data),patch.object(catalog.time,"sleep"):
            with self.assertRaises(ValueError):catalog.pages(lambda p:str(p),lambda d:d["records"],lambda d:d["pages"],10)


if __name__ == "__main__":
    unittest.main()
