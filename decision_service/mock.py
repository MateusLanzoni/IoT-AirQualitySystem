import json
import time
from pathlib import Path

import logging
logger = logging.getLogger(__name__)
import config

MockMode = False

class MockService:

    def __init__(self):
        pass

    def load_mock_data(self):
        """
        read data/mock.json
        """
        file_path = Path(config.MOCK_DATA_FILE)

        if not file_path.exists():
            raise FileNotFoundError(f"This file does not exsit: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)


    def run(self, interval, mqtt_pub=None):
        try:
            mock_data = self.load_mock_data()
            config.mockMode = True
            logger.info("Mock service started. data: %s", mock_data)

            for data in mock_data:

                room_id = "room1"
                device_id = data.get("device_id")
                val = data.get("value")
                mqtt_pub.publish_mock_log(room_id, device_id, val)
               
                time.sleep(interval)

        except Exception as e:
            logger.exception("Mock sends data failed: error=%s", e)


    def stop(self):
        config.mockMode = False