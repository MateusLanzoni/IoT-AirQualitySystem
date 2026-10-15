
mockMode = False

MOCK_DATA_FILE = "data/mock.json"

MOCK_PREDICTION_DATA = {
    "data": {
        "room_id": "room1",
        "predictions": {
            "temperature": {
                "value": 27.46,
                "horizon_minutes": 15,
                "generated_at": "2026-08-29T09:13:21.890797+00:00"
            },
            "humidity": {
                "value": 57.87,
                "horizon_minutes": 15,
                "generated_at": "2026-08-29T09:13:21.890797+00:00"
            },
            "co2": {
                "value": 635.9,
                "horizon_minutes": 15,
                "generated_at": "2026-08-29T09:13:21.890797+00:00"
            },
            "pm25": {
                "value": 37.71,
                "horizon_minutes": 15,
                "generated_at": "2026-08-29T09:13:21.890797+00:00"
            }
        },
        "risk": "warning",
        "summary": "Forecast remains within the expected comfort and air quality range."
    }
}