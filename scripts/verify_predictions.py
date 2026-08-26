from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from backend.app.verifiers.next_day import main as verify_direction
from backend.app.verifiers.tradeable_t1 import main as verify_tradeable
if __name__ == "__main__":
    verify_direction()
    verify_tradeable()
