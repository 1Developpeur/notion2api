import time
import threading
from typing import Dict, List

from app.logger import logger
from app.notion_client import NotionOpusAPI

class AccountPool:
    def __init__(self, accounts: List[dict]):
        """
        text dict text
        text
        """
        if not accounts:
            raise ValueError("text")
            
        self.clients = [NotionOpusAPI(acc) for acc in accounts]
        # text0 text
        self.cooldown_until = [0.0 for _ in self.clients]
        
        # text
        self._current_index = 0
        self._lock = threading.Lock()
        
    def get_client(self, wait_if_cooling: bool = True) -> NotionOpusAPI:
        """
        textRound-Robintext
        text

        text wait_if_cooling=Truetext
        text
        """
        now = time.time()
        with self._lock:
            start_index = self._current_index
            
            while True:
                idx = self._current_index
                # text
                if self.cooldown_until[idx] <= now:
                    # text
                    self._current_index = (self._current_index + 1) % len(self.clients)
                    return self.clients[idx]
                    
                # text
                self._current_index = (self._current_index + 1) % len(self.clients)
                
                # text
                if self._current_index == start_index:
                    next_available = min(self.cooldown_until)
                    wait_seconds = max(0.5, next_available - now)

                    if wait_if_cooling and wait_seconds <= 15:
                        # text
                        logger.info(
                            f"All accounts cooling, waiting {wait_seconds:.1f}s",
                            extra={
                                "request_info": {
                                    "event": "account_pool_wait_cooling",
                                    "wait_seconds": round(wait_seconds, 1),
                                }
                            },
                        )
                        # text sleeptext
                        self._lock.release()
                        try:
                            time.sleep(wait_seconds)
                        finally:
                            self._lock.acquire()
                        # text
                        now = time.time()
                        continue

                    raise RuntimeError(
                        f"text {max(1, int(wait_seconds))} text"
                    )

    def get_status_summary(self) -> Dict[str, int]:
        """text"""
        now = time.time()
        with self._lock:
            active = sum(1 for ts in self.cooldown_until if ts <= now)
            cooling = len(self.cooldown_until) - active
            return {
                "total": len(self.clients),
                "active": active,
                "cooling": cooling,
            }
                    
    def mark_failed(self, client: NotionOpusAPI, cooldown_seconds: int = 3):
        """
        text 3 text
        """
        with self._lock:
            try:
                idx = self.clients.index(client)
                # text
                self.cooldown_until[idx] = time.time() + cooldown_seconds
                logger.warning(
                    "Account marked as failed",
                    extra={
                        "request_info": {
                            "event": "account_failed",
                            "account": client.account_key,
                            "space_id": client.space_id,
                            "cooldown_seconds": cooldown_seconds,
                        }
                    },
                )
            except ValueError:
                logger.warning(
                    "Attempted to mark unknown account as failed",
                    extra={"request_info": {"event": "account_failed_unknown"}},
                )
