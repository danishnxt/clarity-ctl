"""Write a synthetic access log: python gen_log.py N > big.log"""

import random
import sys
from datetime import datetime, timedelta

PATHS = ["/", "/login", "/api/items", "/api/items/42", "/static/app.js", "/health"]
AGENTS = ["curl/8.4.0", "Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0", "Go-http-client/2.0"]
STATUSES = [200, 200, 200, 301, 404, 500]

n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
t = datetime(2026, 10, 1)
for _ in range(n):
    t += timedelta(seconds=random.randint(0, 5))
    print(f'10.0.{random.randint(0, 9)}.{random.randint(1, 254)} - - '
          f'[{t:%d/%b/%Y:%H:%M:%S} +0000] "GET {random.choice(PATHS)} HTTP/1.1" '
          f'{random.choice(STATUSES)} {random.randint(100, 9000)} "-" "{random.choice(AGENTS)}"')
