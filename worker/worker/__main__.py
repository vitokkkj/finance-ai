from __future__ import annotations

import logging
import signal
import threading

from app.database import SessionLocal
from app.recurrences import extend_active_occurrences


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("finance_ai.worker")
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stopping.set())
    signal.signal(signal.SIGINT, lambda _signum, _frame: stopping.set())
    logger.info("Worker iniciado para manter ocorrências recorrentes futuras.")
    while not stopping.is_set():
        wait_seconds = 24 * 60 * 60
        try:
            with SessionLocal() as db:
                created = extend_active_occurrences(db)
            logger.info(
                "Atualização do horizonte recorrente concluída: %s nova(s) ocorrência(s).",
                created,
            )
        except Exception:
            wait_seconds = 60
            logger.error(
                "Falha ao atualizar o horizonte recorrente; haverá nova tentativa em 60 segundos."
            )
        if stopping.wait(wait_seconds):
            break
    logger.info("Worker encerrado.")


if __name__ == "__main__":
    main()
