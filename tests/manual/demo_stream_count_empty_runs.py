"""Count blocks without a snapshot in a dump written by measure_recovery.py.

The dump is the viewer's stream as the hub sent it: records of <int32 sequence, int32 length,
body>, ended by a (-1, -1) record. A block of 4 bytes or less carries no snapshot (the hub's
transcoder wrote the block's commands only, because it could not decode the snapshot).

Usage: python demo_stream_count_empty_runs.py <dump.dm_91> [min run length, default 20]
"""
import struct
import sys


def read_blocks(data):
    pos, out = 0, []
    while pos + 8 <= len(data):
        seq, length = struct.unpack_from("<ii", data, pos)
        pos += 8
        if seq == -1 and length == -1:
            break
        if length < 0 or pos + length > len(data):
            raise SystemExit("bad record at byte {}".format(pos - 8))
        out.append((seq, length))
        pos += length
    return out


def empty_runs(lengths, min_run):
    runs, run = [], 0
    for length in lengths:
        if length <= 4:
            run += 1
            continue
        if run >= min_run:
            runs.append(run)
        run = 0
    if run >= min_run:
        runs.append(run)
    return runs


def main():
    path = sys.argv[1]
    min_run = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    blocks = read_blocks(open(path, "rb").read())
    lengths = [length for _, length in blocks]
    empty = sum(1 for length in lengths if length <= 4)
    runs = empty_runs(lengths, min_run)
    print("blocks={} with_snapshot={} without_snapshot={} runs_of_{}_or_more={} {}".format(
        len(blocks), len(blocks) - empty, empty, min_run, len(runs), runs))


if __name__ == "__main__":
    main()
