"""tandem — turn a pair of books (L2 + L1) into interleaved bilingual audio.

Pipeline:  extract -> segment -> align -> synthesize
Each stage lives in its own module and can be run/tested independently.
"""

__version__ = "0.1.0"
