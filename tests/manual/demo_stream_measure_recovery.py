"""Watch one POV of the live hub as a late viewer for N seconds and report
when blocks arrive. Usage: python measure_recovery.py <ws url> <seconds> [out.dm_91]"""
import asyncio, struct, sys, time
import websockets

url, seconds = sys.argv[1], float(sys.argv[2])
out = sys.argv[3] if len(sys.argv) > 3 else None


async def main():
    start = time.monotonic()
    arrivals, sizes, seqs, data = [], [], [], bytearray()
    connects = 0
    while time.monotonic() - start < seconds:
        try:
            async with websockets.connect(url, max_size=None, open_timeout=3) as ws:
                connects += 1
                while True:
                    left = seconds - (time.monotonic() - start)
                    if left <= 0:
                        break
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=left)
                    except asyncio.TimeoutError:
                        break
                    arrivals.append(time.monotonic() - start)
                    seq, ln = struct.unpack_from("<ii", msg, 0)
                    seqs.append(seq)
                    sizes.append(ln)
                    data += msg
        except Exception as exc:  # hub down, slot closed: try again
            last = type(exc).__name__
            await asyncio.sleep(0.5)
    if out:
        open(out, "wb").write(bytes(data) + struct.pack("<ii", -1, -1))
    if not arrivals:
        print(f"connects={connects} blocks=0 in {seconds:.0f}s")
        return
    buckets = {}
    for t in arrivals:
        buckets[int(t // 5) * 5] = buckets.get(int(t // 5) * 5, 0) + 1
    jumps = [(a, b) for a, b in zip(seqs, seqs[1:]) if b != a + 1]
    print(f"connects={connects} blocks={len(arrivals)} first_at={arrivals[0]:.1f}s first_sizes={sizes[:3]} "
          f"seq={seqs[0]}..{seqs[-1]} jumps={len(jumps)} {jumps[:4]}")
    print("per 5 s:", " ".join(f"{k}s:{v}" for k, v in sorted(buckets.items())))


asyncio.run(main())
