from .schemas import ForecastValues


def classify_risk(values: ForecastValues) -> tuple[str, str]:
    warnings: list[str] = []

    if values.co2 >= 1200:
        warnings.append("CO2")
    if values.pm25 >= 55:
        warnings.append("PM2.5")
    if values.temperature >= 30:
        warnings.append("temperature")
    if values.humidity >= 70:
        warnings.append("humidity")

    if not warnings:
        return "normal", "Forecast remains within the expected comfort and air quality range."

    risk = "critical" if len(warnings) >= 3 else "warning"
    if len(warnings) == 1:
        summary = f"{warnings[0]} is forecast to worsen within the selected horizon."
    else:
        lead = ", ".join(warnings[:-1])
        summary = f"{lead} and {warnings[-1]} are forecast to worsen within the selected horizon."
    return risk, summary
