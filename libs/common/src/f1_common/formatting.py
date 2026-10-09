def format_lap_time(seconds: float) -> str:
    """81.432 -> '1:21.432' (timing-screen format)."""
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}:{rest:06.3f}"
