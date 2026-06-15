import tempfile
import unittest
from pathlib import Path

import database


class DatabaseSecurityTest(unittest.TestCase):
    def setUp(self):
        self.old_db_path = database.DB_PATH
        self.old_database_url = database.DATABASE_URL
        self.tempdir = tempfile.TemporaryDirectory()
        database.DATABASE_URL = ""
        database.DB_PATH = str(Path(self.tempdir.name) / "security-test.db")
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.old_db_path
        database.DATABASE_URL = self.old_database_url
        self.tempdir.cleanup()

    def test_user_lookup_treats_sql_like_username_as_plain_value(self):
        username = "alice' OR 1=1 --"
        self.assertTrue(database.create_user(username, "alice@example.test", "hash"))

        self.assertIsNone(database.get_user_by_username("' OR 1=1 --"))
        self.assertEqual(database.get_user_by_username(username)["username"], username)

    def test_delete_portfolio_cannot_remove_assets_from_another_user(self):
        database.create_user("owner", "owner@example.test", "hash")
        database.create_user("other", "other@example.test", "hash")
        owner = database.get_user_by_username("owner")
        other = database.get_user_by_username("other")

        owner_portfolio_id = database.save_portfolio(
            owner["id"],
            "Owner Portfolio",
            1000,
            [{"symbol": "AAPL", "name": "Apple", "anteil": 100, "regeln": {}}],
        )
        database.save_portfolio(
            other["id"],
            "Other Portfolio",
            1000,
            [{"symbol": "MSFT", "name": "Microsoft", "anteil": 100, "regeln": {}}],
        )

        database.delete_portfolio(owner_portfolio_id, other["id"])

        owner_portfolios = database.get_portfolios(owner["id"])
        self.assertEqual(len(owner_portfolios), 1)
        self.assertEqual(owner_portfolios[0]["assets"][0]["symbol"], "AAPL")

    def test_postgres_mode_uses_psycopg_placeholders_and_normalized_url(self):
        database.DATABASE_URL = "postgres://user:pass@example.test:5432/dbname"

        self.assertEqual(database._param(), "%s")
        self.assertEqual(database._placeholders(3), "%s, %s, %s")
        self.assertEqual(
            database._normalize_database_url(database.DATABASE_URL),
            "postgresql://user:pass@example.test:5432/dbname",
        )


if __name__ == "__main__":
    unittest.main()
