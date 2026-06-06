from pathlib import Path

from lbh.core.config import init_config, Config
from lbh.indexer.builder import RepoIndexer
from lbh.search.ranker import SearchRanker


def test_index_and_search(tmp_path):
    (tmp_path / "src/payments").mkdir(parents=True)
    (tmp_path / "src/notifications").mkdir(parents=True)
    (tmp_path / "src/payments/checkout.py").write_text(
        "from src.notifications.bus import notification_bus\n\ndef complete_checkout(order_id):\n    notification_bus.publish({'type':'payment_succeeded'})\n",
        encoding="utf-8",
    )
    (tmp_path / "src/notifications/bus.py").write_text("class NotificationBus:\n    def publish(self, event): pass\nnotification_bus=NotificationBus()\n", encoding="utf-8")
    init_config(tmp_path)
    stats = RepoIndexer(tmp_path, Config.load(tmp_path)).rebuild()
    assert stats["files"] >= 2
    ranked = SearchRanker(tmp_path).rank("결제 후 알림", limit=5)
    paths = [r.path for r in ranked]
    assert "src/payments/checkout.py" in paths
