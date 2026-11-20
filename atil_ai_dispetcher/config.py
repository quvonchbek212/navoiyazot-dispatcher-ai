"""Only local runtime storage is writable; ATIL remains read-only."""
import os
from datetime import datetime
import pytz
from dotenv import load_dotenv
from atil_ai_dispetcher import PACKAGE_ROOT, PROJECT_ROOT

load_dotenv(PROJECT_ROOT / '.env')
TIMEZONE = pytz.timezone('Asia/Tashkent')
STATE_PATH = os.getenv('DISPETCHER_STATE_PATH') or str(PACKAGE_ROOT / 'runtime' / 'dispatch.sqlite3')
LLM_TIMEOUT = 90
def now():
    return datetime.now(TIMEZONE)

