"""Exception types raised by the visualizer."""


class SdrVisualizerError(Exception):
    """Base class for all sdr-visualizer errors."""


class InvalidSnapshotError(SdrVisualizerError):
    """Snapshot JSON does not conform to the expected shape."""


class UnknownPlatformError(SdrVisualizerError):
    """Auto-detection could not identify the platform; pass --platform to override."""
