"""logstat: summarise nginx "combined" access logs."""

import argparse
import re
import sys
from collections import Counter
from datetime import datetime

LINE = r'(\S+) \S+ \S+ \[([^\]]+)\] "(\S+) (\S+) [^"]*" (\d{3}) (\d+|-) "[^"]*" "([^"]*)"'


def parse_line(line):
    m = re.match(LINE, line)
    if not m:
        return None
    ip, ts, method, path, status, size, agent = m.groups()
    return {
        "ip": ip,
        "time": datetime.strptime(ts.split()[0], "%d/%b/%Y:%H:%M:%S"),
        "method": method,
        "path": path,
        "status": int(status),
        "size": 0 if size == "-" else int(size),
        "agent": agent,
    }


def summarise(lines):
    records = [r for r in map(parse_line, lines) if r]
    return {
        "requests": len(records),
        "bytes": sum(r["size"] for r in records),
        "unique_ips": len({r["ip"] for r in records}),
        "paths": Counter(r["path"] for r in records),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="logstat")
    ap.add_argument("logfile")
    args = ap.parse_args(argv)
    with open(args.logfile) as f:
        s = summarise(f)
    print(f"requests    {s['requests']}")
    print(f"bytes       {s['bytes']}")
    print(f"unique ips  {s['unique_ips']}")


if __name__ == "__main__":
    sys.exit(main())
