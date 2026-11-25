"""
Polygraph Scoring Components Package

Contains ResultAggregator, ReportGenerator, and other scoring infrastructure
wired into Polygraph runner from #7b fixes.

This module was part of the uncommitted work product for Polygraph #13+#14.
Since the reset --hard removed it, we're recreating here before commit.
"""

from .aggregator import ResultAggregator
from .report_generator import ReportGenerator
