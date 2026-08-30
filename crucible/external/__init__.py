"""Adapters that let Crucible's detectors read traces produced by external benchmarks.

These exist to answer one question honestly: do the detectors agree with an independent
ground truth, on agents we did not write? Nothing in here reimplements a detector - the
adapter builds real Crucible spans and the shipped `check()` runs against them unchanged.
"""
