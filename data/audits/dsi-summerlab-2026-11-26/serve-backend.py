import os
from datetime import UTC,datetime
from pathlib import Path
from scripts.measure_match_latency import ISOLATION_ENV
os.environ.update(ISOLATION_ENV)
from backend.main import app
from src import evidence
import uvicorn
clock=Path(os.environ['DSI_TEST_CLOCK'])
class Simulated(datetime):
    @classmethod
    def now(cls,tz=None):
        if not clock.exists():return super().now(tz)
        value=datetime.fromisoformat(clock.read_text().strip())
        return value.astimezone(tz) if tz else value.astimezone(UTC).replace(tzinfo=None)
evidence.datetime=Simulated
uvicorn.run(app,host='127.0.0.1',port=39784,log_level='warning')
